import re
import time
import random
import requests
from email_extract import extract_emails

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}


def _normalize_fb_url(url: str) -> str:
    """Strip query params and trailing slashes from a Facebook URL."""
    url = url.split('?')[0].rstrip('/')
    return url


def scrape_facebook(fb_url: str, delay: float = 1.5) -> list[str]:
    """
    Try to find emails on a Facebook page.
    Checks the /about sub-path first, then the main page.
    Returns a list of email strings.
    """
    base = _normalize_fb_url(fb_url)
    urls_to_try = [base + '/about', base]

    emails = []
    seen_urls = set()

    for url in urls_to_try:
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            time.sleep(delay + random.uniform(0.3, 0.8))
            resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code != 200:
                continue
            found = extract_emails(resp.text, site_domain='')
            emails.extend(found)
        except Exception:
            continue

        if emails:
            break

    # Deduplicate while preserving order
    seen = set()
    result = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


def find_facebook_url(html: str):
    """
    Scan page HTML for a link to a Facebook page.
    Returns the URL if found, else None.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup.find_all('a', href=True):
        href = tag['href']
        if re.match(r'https?://(www\.)?facebook\.com/[^/\s"\']+', href):
            # Skip facebook.com/sharer and other non-profile pages
            path = href.split('facebook.com/', 1)[-1].split('?')[0].strip('/')
            if path and path not in ('sharer', 'sharer.php', 'share', 'login', 'dialog'):
                return href
    return None
