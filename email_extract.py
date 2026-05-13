import re
from urllib.parse import urlparse, unquote

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

# Domains (and their subdomains) that produce false positives
JUNK_DOMAINS = {
    'example.com', 'example.org', 'test.com', 'sentry.io', 'wixpress.com',
    'squarespace.com', 'w3.org', 'schema.org', 'google.com',
    'googletagmanager.com', 'googleapis.com', 'cloudflare.com', 'wordpress.org',
    'jquery.com', 'bootstrapcdn.com', 'fontawesome.com', 'gravatar.com',
    'placeholder.com', 'domain.com', 'youremail.com', 'email.com',
    'web.com', 'emailservices.com', 'myemail.com', 'yourname.com',
    'company.com', 'name.com', 'hostname.com', 'aliaswire.com',
}

# Extensions that indicate the @ is inside a filename, not an email
JUNK_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.woff',
                   '.woff2', '.ttf', '.eot', '.otf', '.ico', '.mp4', '.mp3'}


def _is_junk(email: str) -> bool:
    try:
        local, domain = email.rsplit('@', 1)
    except ValueError:
        return True
    domain_lower = domain.lower()
    # Check for file extensions in local part or domain
    for ext in JUNK_EXTENSIONS:
        if local.lower().endswith(ext) or domain_lower.endswith(ext):
            return True
    # Check junk domains including subdomains (e.g. sentry.wixpress.com matches wixpress.com)
    for junk in JUNK_DOMAINS:
        if domain_lower == junk or domain_lower.endswith('.' + junk):
            return True
    # Must have at least one dot in domain
    if '.' not in domain_lower:
        return True
    # Reject domains that are just numbers
    if re.fullmatch(r'[\d.]+', domain_lower):
        return True
    # Reject no-reply and automated addresses
    if re.match(r'(noreply|no-reply|donotreply|do-not-reply|mailer-daemon|postmaster)@', local.lower()):
        return True
    return False


def extract_emails(html: str, site_domain: str = '') -> list[str]:
    """Extract and deduplicate emails from HTML. Prioritize emails on site_domain."""
    from bs4 import BeautifulSoup

    found = set()

    # First pass: extract from mailto: links (most reliable)
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup.find_all('a', href=True):
        href = tag['href']
        if href.lower().startswith('mailto:'):
            addr = unquote(href[7:].split('?')[0].strip())
            if addr:
                found.add(addr.lower())

    # Second pass: Cloudflare email protection (data-cfemail attribute)
    for tag in soup.find_all(attrs={'data-cfemail': True}):
        try:
            encoded = tag['data-cfemail']
            data = bytes.fromhex(encoded)
            key = data[0]
            decoded = ''.join(chr(b ^ key) for b in data[1:])
            if '@' in decoded:
                found.add(decoded.lower())
        except Exception:
            pass

    # Third pass: regex on full text
    for match in EMAIL_RE.finditer(html):
        found.add(unquote(match.group(0)).lower())

    # Filter junk
    clean = [e for e in found if not _is_junk(e)]

    # Sort: site domain emails first, then alphabetical
    def sort_key(email):
        domain = email.split('@')[1] if '@' in email else ''
        on_site = site_domain and (domain == site_domain or domain.endswith('.' + site_domain))
        return (0 if on_site else 1, email)

    clean.sort(key=sort_key)
    return clean
