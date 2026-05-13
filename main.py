#!/usr/bin/env python3
"""
Lead Email Enricher
Usage: python main.py leads.csv [--output enriched.csv] [--workers 5] [--delay 1.5]
"""

import argparse
import csv
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                os.environ.setdefault(key.strip(), val.strip())

_load_env()

import pandas as pd

from scraper import enrich_lead


def parse_args():
    parser = argparse.ArgumentParser(description='Enrich a leads CSV with email addresses.')
    parser.add_argument('input', help='Path to input CSV file')
    parser.add_argument('--output', help='Path to output CSV (default: enriched_<input>)')
    parser.add_argument('--workers', type=int, default=5,
                        help='Number of parallel threads (default: 5)')
    parser.add_argument('--delay', type=float, default=1.5,
                        help='Base delay in seconds between requests (default: 1.5)')
    parser.add_argument('--website-col', default=None,
                        help='Name of the website column (auto-detected if not set)')
    parser.add_argument('--name-col', default=None,
                        help='Name of the company name column (auto-detected if not set)')
    return parser.parse_args()


def detect_column(columns, candidates):
    """Case-insensitive column name detection."""
    lower = {c.lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return None


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        print(f'Error: file not found: {args.input}')
        sys.exit(1)

    df = pd.read_csv(args.input, dtype=str)
    columns = list(df.columns)

    # Auto-detect key columns
    website_col = args.website_col or detect_column(
        columns, ['website', 'Website', 'url', 'URL', 'site', 'web'])
    name_col = args.name_col or detect_column(
        columns, ['name', 'Name', 'company', 'Company', 'business', 'Business Name'])

    if not website_col:
        print(f'Error: could not find a website column. Columns found: {columns}')
        print('Use --website-col to specify the column name.')
        sys.exit(1)

    print(f'Input:       {args.input} ({len(df)} rows)')
    print(f'Website col: {website_col}')
    print(f'Name col:    {name_col or "(not found)"}')
    print(f'Workers:     {args.workers}')
    print(f'Delay:       {args.delay}s')
    print()

    # Set up output file
    output_path = args.output or f'enriched_{os.path.basename(args.input)}'
    email_cols = [f'email_{i}' for i in range(1, 6)]
    out_columns = list(df.columns) + email_cols + ['emails_source']

    # Always start fresh — write header now
    write_lock = threading.Lock()
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=out_columns)
        writer.writeheader()

    completed = 0
    total = len(df)

    def process_row(idx_row):
        idx, row = idx_row
        website = str(row.get(website_col, '')).strip()
        name = str(row.get(name_col, idx)) if name_col else str(idx)

        out_row = row.to_dict()
        for col in email_cols:
            out_row[col] = ''
        out_row['emails_source'] = ''

        if website and website.lower() not in ('nan', 'none', ''):
            try:
                emails, sources = enrich_lead(website, delay=args.delay)
                for i, email in enumerate(emails):
                    out_row[f'email_{i + 1}'] = email
                out_row['emails_source'] = ', '.join(sources)
            except Exception as e:
                pass  # Leave blank on unexpected error

        return idx, name, out_row, len([v for k, v in out_row.items()
                                        if k.startswith('email_') and v])

    futures = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for idx, row in df.iterrows():
            future = executor.submit(process_row, (idx, row))
            futures[future] = idx

        for future in as_completed(futures):
            idx, name, out_row, found_count = future.result()
            completed += 1

            # Write row to output CSV
            with write_lock:
                with open(output_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=out_columns)
                    writer.writerow(out_row)

            status = f'found {found_count} email(s)' if found_count else 'no emails found'
            print(f'[{completed}/{total}] {name} — {status}')

    print(f'\nDone. Output saved to: {output_path}')


if __name__ == '__main__':
    main()
