import time
from typing import List, Tuple
import tldextract
import requests
from bs4 import BeautifulSoup
from .parser import html_to_text

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OutreachAgent/1.0; +https://example.com/agent)"
}

def normalize_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u.lstrip("/")
    return u.rstrip("/")

def same_domain(url: str, base: str) -> bool:
    u = tldextract.extract(url)
    b = tldextract.extract(base)
    return (u.domain == b.domain) and (u.suffix == b.suffix)

def fetch(url: str, timeout: int = 12) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return ""
        return resp.text
    except Exception:
        return ""

def discover_internal_links(html: str, base_url: str, target_paths: List[str]) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        if not href.startswith("http"):
            continue
        if not same_domain(href, base_url):
            continue
        low = href.lower()
        if any(tp in low for tp in target_paths):
            links.append(href)
    # dedupe preserve order
    seen, deduped = set(), []
    for l in links:
        if l not in seen:
            seen.add(l); deduped.append(l)
    return deduped

def crawl_relevant_pages(base_url: str, target_paths: List[str], max_pages: int, max_chars_per_page: int) -> List[Tuple[str, str]]:
    base_url = normalize_url(base_url)
    if not base_url:
        return []
    pages: List[Tuple[str, str]] = []
    home_html = fetch(base_url)
    if not home_html:
        return []
    pages.append((base_url, html_to_text(home_html, max_chars=max_chars_per_page)))
    links = discover_internal_links(home_html, base_url, target_paths)
    for link in links[: max_pages - 1]:  # we already took homepage
        time.sleep(0.8)  # be polite
        html = fetch(link)
        if not html:
            continue
        pages.append((link, html_to_text(html, max_chars=max_chars_per_page)))
    return pages
