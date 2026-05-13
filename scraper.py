import json
import os
import re
import time
import random
import requests
from urllib.parse import urlparse, urljoin
from email_extract import extract_emails
from facebook import find_facebook_url, scrape_facebook

SUBPAGES = [
    '/contact', '/contact-us', '/about', '/about-us', '/team', '/staff',
    '/privacy', '/privacy-policy', '/terms', '/terms-of-service', '/terms-and-conditions',
]

USER_AGENTS = [
    ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'),
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'),
    ('Mozilla/5.0 (X11; Linux x86_64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
]


def _headers() -> dict:
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }


def _fetch(url: str, timeout: int = 10):
    """Fetch a URL and return HTML text, or None on failure."""
    try:
        session = requests.Session()
        session.max_redirects = 5
        resp = session.get(url, headers=_headers(), timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and 'text/html' in resp.headers.get('Content-Type', ''):
            return resp.text
    except Exception:
        pass
    return None


def _normalize_url(url: str) -> str:
    """Ensure URL has a scheme."""
    url = url.strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _site_domain(url: str) -> str:
    """Extract the bare domain (no www) from a URL."""
    try:
        host = urlparse(url).hostname or ''
        return host.removeprefix('www.')
    except Exception:
        return ''


def _same_site(url_a: str, url_b: str) -> bool:
    """Return True if both URLs belong to the same site, ignoring www prefix."""
    return _site_domain(url_a) == _site_domain(url_b)


def enrich_lead(website_url: str, delay: float = 1.5) -> tuple[list[str], list[str]]:
    """
    Scrape a lead's website for email addresses.

    Returns:
        (emails, sources) — up to 5 emails and the page they were found on.
    """
    url = _normalize_url(website_url)
    if not url:
        return [], []

    domain = _site_domain(url)
    all_emails: list[str] = []
    sources: list[str] = []
    visited: set[str] = set()
    fb_url = None

    def _add(emails: list[str], source: str):
        for e in emails:
            if e not in all_emails:
                all_emails.append(e)
                sources.append(source)

    # 1. Main page
    time.sleep(random.uniform(delay * 0.5, delay))
    html = _fetch(url)
    if html:
        visited.add(url)
        _add(extract_emails(html, domain), 'website')
        if not fb_url:
            fb_url = find_facebook_url(html)

    # 2. Subpages
    for path in SUBPAGES:
        if len(all_emails) >= 5:
            break
        sub_url = urljoin(url, path)
        if sub_url in visited:
            continue
        time.sleep(random.uniform(delay * 0.5, delay))
        sub_html = _fetch(sub_url)
        if sub_html:
            visited.add(sub_url)
            new = extract_emails(sub_html, domain)
            _add(new, f'website{path}')
            if not fb_url:
                fb_url = find_facebook_url(sub_html)

    # 3. Fallback: contact-linked pages + iframes (only when nothing found yet)
    if not all_emails and html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')

        # 3a. Follow any on-site links whose href contains 'contact' or 'ContactUs'
        contact_urls = []
        for tag in soup.find_all('a', href=True):
            href = tag['href']
            if re.search(r'contact', href, re.IGNORECASE):
                full = urljoin(url, href)
                if _same_site(full, url) and full not in visited:
                    contact_urls.append(full)

        for contact_url in contact_urls[:5]:  # cap at 5 attempts
            if len(all_emails) >= 5:
                break
            time.sleep(random.uniform(delay * 0.5, delay))
            contact_html = _fetch(contact_url)
            if contact_html:
                visited.add(contact_url)
                _add(extract_emails(contact_html, domain), 'website/contact-link')

        # 3b. Fetch iframe src URLs on the same host
        if not all_emails:
            for iframe in soup.find_all('iframe', src=True):
                if len(all_emails) >= 5:
                    break
                iframe_url = urljoin(url, iframe['src'])
                if _same_site(iframe_url, url) and iframe_url not in visited:
                    time.sleep(random.uniform(delay * 0.5, delay))
                    iframe_html = _fetch(iframe_url)
                    if iframe_html:
                        visited.add(iframe_url)
                        _add(extract_emails(iframe_html, domain), 'website/iframe')

    # 4. Fallback: .html subpage variants (only when nothing found yet)
    HTML_SUBPAGES = [
        '/contact.html', '/contact-us.html', '/about.html', '/about-us.html',
        '/contactus.html', '/contact_us.html',
    ]
    if not all_emails:
        for path in HTML_SUBPAGES:
            if len(all_emails) >= 5:
                break
            html_url = urljoin(url, path)
            if html_url in visited:
                continue
            time.sleep(random.uniform(delay * 0.5, delay))
            html_page = _fetch(html_url)
            if html_page:
                visited.add(html_url)
                _add(extract_emails(html_page, domain), f'website{path}')

    # 6. Fallback: path-based subpages (only when input URL has a non-root path)
    #    e.g. given https://example.com/new-york, also try https://example.com/new-york/contact-us
    if not all_emails:
        parsed_input = urlparse(url)
        input_path = parsed_input.path.rstrip('/')
        if input_path and input_path != '':
            path_subpages = ['/contact-us', '/contact', '/about', '/about-us']
            for path in path_subpages:
                if len(all_emails) >= 5:
                    break
                path_url = parsed_input._replace(path=input_path + path, query='').geturl()
                if path_url not in visited:
                    time.sleep(random.uniform(delay * 0.5, delay))
                    path_html = _fetch(path_url)
                    if path_html:
                        visited.add(path_url)
                        _add(extract_emails(path_html, domain), f'website{path}')

    # 7. Playwright JS rendering — disabled for speed (re-enable for deeper crawl)
    # 8. Full site crawl — disabled for speed (re-enable for deeper crawl)

    # 9. Facebook
    if fb_url and len(all_emails) < 5:
        fb_emails = scrape_facebook(fb_url, delay=delay)
        _add(fb_emails, 'facebook')

    # 10. GPT fallback: catches obfuscated emails like "info [at] domain [dot] com"
    if not all_emails:
        gpt_emails, gpt_sources = _gpt_email_fallback(url, domain, html, visited, delay)
        for e, s in zip(gpt_emails, gpt_sources):
            if e not in all_emails:
                all_emails.append(e)
                sources.append(s)

    # Cap at 5
    return all_emails[:5], sources[:5]


def _fetch_js_fallback(url: str, domain: str, visited: set, delay: float):
    """
    Fallback: use Playwright headless browser to render JS and find mailto: links.
    Tries the given URL plus /contact-us appended to the input path.
    Only called when static scraping found nothing.
    """
    emails = []
    sources = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return emails, sources

    parsed = urlparse(url)
    input_path = parsed.path.rstrip('/')
    urls_to_try = [url]
    # Also try path-based contact-us if URL has a non-root path
    if input_path:
        path_contact = parsed._replace(path=input_path + '/contact-us', query='').geturl()
        if path_contact not in visited:
            urls_to_try.append(path_contact)
    # And root-level contact-us
    root_contact = parsed._replace(path='/contact-us', query='').geturl()
    if root_contact not in visited and root_contact not in urls_to_try:
        urls_to_try.append(root_contact)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({'Accept-Language': 'en-US,en;q=0.9'})

            for try_url in urls_to_try:
                if len(emails) >= 5:
                    break
                try:
                    time.sleep(random.uniform(delay * 0.5, delay))
                    page.goto(try_url, timeout=20000, wait_until='domcontentloaded')
                    page.wait_for_timeout(3000)
                    html = page.content()
                    found = extract_emails(html, domain)
                    # Also grab mailto: links directly from rendered DOM
                    mailto_hrefs = page.eval_on_selector_all(
                        'a[href^="mailto:"]',
                        'els => els.map(e => e.getAttribute("href"))'
                    )
                    for href in mailto_hrefs:
                        addr = href[7:].split('?')[0].strip().lower()
                        if addr and addr not in found:
                            found.insert(0, addr)
                    for e in found:
                        if e not in emails:
                            emails.append(e)
                            sources.append('website/js')
                except Exception:
                    continue

            browser.close()
    except Exception:
        pass

    return emails[:5], sources[:5]


def _html_to_text(html: str) -> str:
    """Strip tags and scripts to produce plain text for GPT."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        for tag in soup(['script', 'style']):
            tag.decompose()
        return soup.get_text(separator=' ', strip=True)
    except Exception:
        return re.sub(r'<[^>]+>', ' ', html)


def _gpt_email_fallback(url: str, domain: str, homepage_html,
                        visited: set, delay: float) -> tuple[list[str], list[str]]:
    """
    Level 10: GPT-powered fallback for obfuscated or non-standard email formats.
    Catches patterns like 'info [at] domain [dot] com' that regex misses.
    Only called when all prior levels found nothing.
    Requires OPENAI_API_KEY in environment. Silently skips if not set.
    """
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        return [], []

    try:
        from openai import OpenAI
    except ImportError:
        return [], []

    snippets = []
    if homepage_html:
        snippets.append(('homepage', _html_to_text(homepage_html)[:2500]))

    # Fetch one contact page (skip if already visited)
    for path in ('/contact', '/contact-us', '/about'):
        contact_url = urljoin(url, path)
        if contact_url not in visited:
            time.sleep(random.uniform(delay * 0.3, delay * 0.6))
            contact_html = _fetch(contact_url)
            if contact_html:
                visited.add(contact_url)
                snippets.append((f'contact{path}', _html_to_text(contact_html)[:2500]))
                break

    if not snippets:
        return [], []

    combined = '\n\n---\n\n'.join(f'[{label}]\n{text}' for label, text in snippets)

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Extract all email addresses from the webpage text. '
                        'Include obfuscated formats like "name [at] domain [dot] com", '
                        '"name(at)domain.com", "name AT domain DOT com", or emails split '
                        'by spaces or punctuation — convert them to standard format. '
                        'Return ONLY a JSON array of email strings, e.g. ["info@example.com"]. '
                        'Return [] if none found. No explanation, no other text.'
                    ),
                },
                {'role': 'user', 'content': combined},
            ],
            max_tokens=150,
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content.strip())
        if not isinstance(raw, list):
            return [], []

        # Validate through existing junk filter
        fake_html = ' '.join(
            f'<a href="mailto:{e}">{e}</a>' for e in raw if isinstance(e, str) and '@' in e
        )
        validated = extract_emails(fake_html, domain) if fake_html else []
        return validated[:5], ['website/gpt'] * len(validated[:5])
    except Exception:
        return [], []


def _full_site_crawl(url: str, domain: str, visited: set, delay: float, max_pages: int = 25):
    """
    Last-resort fallback: crawl all internal links on the site up to max_pages.
    Discovers pages that no fixed subpage list would guess (e.g. /board-of-directors).
    Only called when all other methods have found nothing.
    """
    from bs4 import BeautifulSoup
    from collections import deque

    emails = []
    sources = []
    base_parsed = urlparse(url)
    queue = deque()

    # Seed queue with homepage (already fetched earlier, so just collect its links)
    seed_html = _fetch(url)
    pages_checked = len(visited)

    if seed_html:
        seed_soup = BeautifulSoup(seed_html, 'lxml')
        for tag in seed_soup.find_all('a', href=True):
            full = urljoin(url, tag['href'])
            p = urlparse(full)
            # Same site (www-insensitive), no file downloads
            if (_same_site(full, url)
                    and full not in visited
                    and not re.search(r'\.(pdf|jpg|png|gif|svg|zip|docx?|xlsx?)$', p.path, re.I)):
                queue.append(full)

    seen_in_queue = set(queue)

    while queue and pages_checked < max_pages:
        next_url = queue.popleft()
        if next_url in visited:
            continue

        time.sleep(random.uniform(delay * 0.3, delay * 0.7))
        page_html = _fetch(next_url)
        pages_checked += 1

        if not page_html:
            continue

        visited.add(next_url)
        found = extract_emails(page_html, domain)
        for e in found:
            if e not in emails:
                emails.append(e)
                sources.append('website/crawl')

        if emails:
            break  # Stop as soon as we find anything

        # Add new internal links to queue
        page_soup = BeautifulSoup(page_html, 'lxml')
        for tag in page_soup.find_all('a', href=True):
            full = urljoin(next_url, tag['href'])
            p = urlparse(full)
            if (_same_site(full, url)
                    and full not in visited
                    and full not in seen_in_queue
                    and not re.search(r'\.(pdf|jpg|png|gif|svg|zip|docx?|xlsx?)$', p.path, re.I)):
                queue.append(full)
                seen_in_queue.add(full)

    return emails[:5], sources[:5]
