# linkedin_scraper.py
"""
DuckDuckGo-based LinkedIn content scraper.
Finds up to 3 recent public posts for a LinkedIn profile,
plus headline/about info from Jina proxy snapshot.
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

JINA_PROXY_PREFIX = "https://r.jina.ai/http://"

# -------------------------------------------------------------------
# Fetch readable text snapshot (Jina)
# -------------------------------------------------------------------
def fetch_profile_text(linkedin_url: str) -> str:
    """Fetch readable plain text from a LinkedIn profile via Jina proxy."""
    if not linkedin_url:
        return ""
    proxied = JINA_PROXY_PREFIX + linkedin_url.replace("https://", "").replace("http://", "")
    try:
        r = requests.get(proxied, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[LinkedIn Scraper] Jina proxy failed for {linkedin_url}: {e}")
        return ""

# -------------------------------------------------------------------
# Extract structured profile info from text
# -------------------------------------------------------------------
def extract_profile_structured(text: str) -> Dict:
    """Parse Jina text snapshot for headline/about heuristics."""
    if not text:
        return {"headline": "", "about": "", "posts": []}

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    joined = "\n".join(lines)

    # Headline: first line with " at " or dash
    headline = next((ln for ln in lines[:50] if " at " in ln or " – " in ln or " — " in ln), "")

    # About/Summary block
    about_match = re.search(r"(About|Summary)\s*\n+(.{120,800})", joined, re.IGNORECASE | re.DOTALL)
    about = about_match.group(2).split("\n\n")[0].strip() if about_match else ""

    return {"headline": headline[:200], "about": about[:800], "posts": []}

# -------------------------------------------------------------------
# DuckDuckGo search for recent posts
# -------------------------------------------------------------------
def find_recent_posts(name: str, company: str = "") -> List[Dict[str, str]]:
    """
    Uses DuckDuckGo to find up to 3 recent posts by a person.
    Returns a list of dicts: [{"snippet": "...", "url": "..."}]
    """
    q = f'site:linkedin.com/posts "{name}" "{company}"'
    url = f"https://duckduckgo.com/html/?q={requests.utils.quote(q)}"
    posts = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result__a[href]"):
            href = a["href"]
            snippet_tag = a.find_parent("div", class_="result__snippet")
            snippet = snippet_tag.text.strip() if snippet_tag else a.text.strip()
            if "linkedin.com/posts" in href:
                posts.append({"url": href.split("?")[0], "snippet": snippet[:300]})
            if len(posts) >= 3:
                break
        time.sleep(random.uniform(1.8, 3.2))
        return posts
    except Exception as e:
        print(f"[LinkedIn Scraper] DDG post search failed for {name}@{company}: {e}")
        return []

# -------------------------------------------------------------------
# High-level scraper
# -------------------------------------------------------------------
def scrape_profile(linkedin_url: str, name: str = "", company: str = "") -> Dict:
    """
    Combines Jina profile snapshot + DuckDuckGo post search.
    Returns structured dict with headline, about, and up to 3 posts.
    """
    text = fetch_profile_text(linkedin_url)
    data = extract_profile_structured(text)
    posts = find_recent_posts(name, company)
    data["posts"] = posts
    return data

# -------------------------------------------------------------------
# Batch mode for pipeline integration
# -------------------------------------------------------------------
def scrape_profiles(profiles: List[Dict]) -> List[Dict]:
    """
    Expects profiles containing 'name', 'company', and 'linkedin_url'.
    Returns list with additional post data merged in.
    """
    results = []
    for i, p in enumerate(profiles):
        name = p.get("name") or p.get("full_name") or ""
        company = p.get("company") or ""
        url = p.get("linkedin_url")
        print(f"[{i+1}/{len(profiles)}] Scraping LinkedIn posts for: {name} ({company})")
        result = scrape_profile(url, name, company)
        results.append({**p, **result})
    return results

if __name__ == "__main__":
    sample = [{"name": "Jane Doe", "company": "Google", "linkedin_url": "https://linkedin.com/in/janedoe"}]
    print(scrape_profiles(sample))