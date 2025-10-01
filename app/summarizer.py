import os, json
from typing import Dict, List
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

TEMPLATES = {
    "general": "summarize_general.txt",
    "pipeline": "summarize_pipeline.txt",
    "social": "summarize_social.txt",
}

def load_template(enrichment: str) -> str:
    name = TEMPLATES.get(enrichment, "summarize_general.txt")
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def build_sources(pages: List[Dict[str, str]], limit_pages: int = 5, limit_chars: int = 1200) -> str:
    tops = []
    for p in pages[:limit_pages]:
        tops.append(f"URL: {p['url']}\nTEXT: {p['text'][:limit_chars]}")
    return "\n\n".join(tops)

def format_prompt(pages: List[Dict[str, str]], client_name: str, enrichment: str) -> str:
    template = load_template(enrichment)
    sources = build_sources(pages)
    return template.format(client_name=client_name, sources=sources)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def call_openai(prompt: str) -> Dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"company_focus":"Unknown","recent_activity":"Unknown","positioning_hook":"General benefits"}
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3,
        response_format={"type":"json_object"}
    )
    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content}

def summarize_pages(pages: List[Dict[str, str]], client_name: str, enrichment: str) -> Dict:
    prompt = format_prompt(pages, client_name, enrichment)
    return call_openai(prompt)
