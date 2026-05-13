# Lead Email Enricher

A small Python CLI that takes a CSV of business leads (with a `website` column)
and tries to find an email address for each one by scraping the company's site.

## How it works

For each row, the scraper tries (in order, stopping as soon as it finds emails):

1. The homepage
2. Common subpages: `/contact`, `/contact-us`, `/about`, `/about-us`, `/team`, `/staff`, privacy/terms pages
3. Any on-page link containing the word "contact" + same-site iframes
4. `.html` variants like `/contact.html`
5. Path-based variants (if the input URL has a non-root path)
6. The company's Facebook page (if linked from the site)
7. **GPT fallback** — catches obfuscated formats like `info [at] domain [dot] com`. Requires an OpenAI API key. Skipped if no key is set.

Results are written to a new CSV (`enriched_<input>.csv`) with up to 5 emails per row plus an `emails_source` column showing where each was found.

## Setup

```bash
pip install -r requirements.txt
```

If you want the GPT obfuscated-email fallback (optional):

```bash
cp .env.example .env
# then edit .env and paste your OpenAI key after OPENAI_API_KEY=
```

Without a key, the scraper still works fine — it just skips step 7.

## Usage

```bash
python main.py leads.csv
```

The CSV must have a `website` column (case-insensitive; `url`, `site`, `web`
also work). A `name` / `company` column is optional but used for nicer logs.

### Options

| Flag | Default | Description |
|---|---|---|
| `--output PATH` | `enriched_<input>.csv` | Where to write results |
| `--workers N` | `5` | Parallel threads |
| `--delay SECS` | `1.5` | Base delay between requests (politeness) |
| `--website-col NAME` | auto-detect | Override the website column name |
| `--name-col NAME` | auto-detect | Override the company-name column name |

Example:

```bash
python main.py my-leads.csv --workers 10 --delay 1.0 --output results.csv
```

## Notes

- The `.env` file and any `*.csv` files are gitignored — don't commit your
  API keys or your lead lists.
- Playwright is listed in `requirements.txt` but JS-rendering is disabled by
  default in [scraper.py](scraper.py) for speed. You can re-enable the
  `_fetch_js_fallback` call if you need it.
