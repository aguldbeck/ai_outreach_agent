# quickstart_agent.py
# Minimal single-file runner for Step 1 (website-only enrichment, general mode).

import csv, os, requests, json
from bs4 import BeautifulSoup
from openai import OpenAI

PROMPT = """You are a research assistant preparing structured notes.
Sources:
{sources}
Output strict JSON with keys: {{"company_focus": "...", "recent_activity": "...", "positioning_hook": "..."}}"""

def fetch(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0 OutreachAgent"}, timeout=10)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

def html_to_text(html: str, max_chars: int = 3000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    bits = [t.get_text(" ", strip=True) for t in soup.find_all(["h1","h2","h3","p","li"])]
    return (" ".join(bits))[:max_chars]

def summarize(sources_text: str) -> dict:
    api = os.getenv("OPENAI_API_KEY")
    if not api:
        return {"company_focus":"Unknown","recent_activity":"Unknown","positioning_hook":"General benefits"}
    client = OpenAI(api_key=api)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":PROMPT.format(sources=sources_text)}],
        temperature=0.3,
        response_format={"type":"json_object"}
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {"raw": resp.choices[0].message.content}

def run(input_csv: str, output_csv: str):
    out_rows = []
    with open(input_csv, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("website","")
            html = fetch(url) if url else ""
            text = html_to_text(html) if html else ""
            sources = f"URL: {url}\nTEXT: {text}"
            summary = summarize(sources)
            out = {**row, **{
                "company_focus": summary.get("company_focus",""),
                "recent_activity": summary.get("recent_activity",""),
                "positioning_hook": summary.get("positioning_hook",""),
            }}
            out_rows.append(out)
    fieldnames = list(out_rows[0].keys()) if out_rows else []
    with open(output_csv, "w", newline='', encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames); w.writeheader(); w.writerows(out_rows)
    print("Wrote", output_csv)

if __name__ == "__main__":
    run("data/prospects.sample.csv", "data/enriched.quickstart.csv")
