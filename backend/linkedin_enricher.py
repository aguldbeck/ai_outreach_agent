# linkedin_enricher.py
"""
DuckDuckGo-based LinkedIn profile enricher.
Given a name and company, finds a best-guess LinkedIn profile URL.
Integrates with pipeline.py -> enrich_profiles().
"""

import time
import random
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

def _clean_linkedin_url(raw_url: str) -> str:
    """Ensure we return a clean LinkedIn URL (no redirect wrappers or params)."""
    if not raw_url:
        return None
    # DuckDuckGo wraps URLs in /l/?kh=-1&uddg=encoded_url
    if "uddg=" in raw_url:
        try:
            from urllib.parse import unquote, urlparse, parse_qs
            parsed = urlparse(raw_url)
            qs = parse_qs(parsed.query)
            real = unquote(qs.get("uddg", [""])[0])
            if "linkedin.com/" in real:
                return real.split("?")[0].rstrip("/")
        except Exception:
            pass
    # Direct linkedin.com link
    if "linkedin.com/" in raw_url:
        return raw_url.split("?")[0].rstrip("/")
    return None

def find_linkedin_profile(name: str, company: str = "") -> Optional[str]:
    """Find the first plausible LinkedIn profile URL for a given person."""
    if not name:
        return None

    q = f'{name} {company} site:linkedin.com/in OR site:linkedin.com/pub'
    url = f"https://duckduckgo.com/html/?q={requests.utils.quote(q)}"

    for attempt in range(2):  # retry once
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a.result__a[href]"):
                href = a["href"]
                clean = _clean_linkedin_url(href)
                if clean and ("linkedin.com/in" in clean or "linkedin.com/pub" in clean):
                    return clean
            return None
        except Exception as e:
            print(f"[LinkedIn Enricher] DuckDuckGo error for {name} @ {company}: {e}")
            time.sleep(random.uniform(2.0, 3.5))
        finally:
            time.sleep(random.uniform(1.5, 2.5))
    return None

def enrich_profiles(profiles: List[Dict]) -> List[Dict]:
    """
    Takes a list of dicts (each with 'name' and 'company' keys).
    Adds 'linkedin_url' field to each record.
    Returns updated list.
    """
    enriched = []
    for i, p in enumerate(profiles):
        name = p.get("name") or p.get("full_name") or ""
        company = p.get("company") or p.get("organization") or ""
        print(f"[{i+1}/{len(profiles)}] Searching LinkedIn for: {name} @ {company}")
        url = find_linkedin_profile(name, company)
        enriched.append({**p, "linkedin_url": url})
    return enriched

if __name__ == "__main__":
    # simple local test
    sample = [{"name": "Jane Doe", "company": "Google"}]
    out = enrich_profiles(sample)
    print(out)