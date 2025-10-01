import os, json
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

TEMPLATES = {
    "general": "email_general.txt",
    "pipeline": "email_pipeline.txt",
    "social": "email_social.txt",
}

def load_template(mode: str) -> str:
    fname = TEMPLATES.get(mode, "email_general.txt")
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", fname)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def call_openai(prompt: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"email_subject":"[Demo subject]","email_body":"[Demo body: no API key set]"}
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.5,
        response_format={"type":"json_object"}
    )
    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content}

def generate_email(enrichment: str, notes: dict, client_name: str, cta: str) -> dict:
    template = load_template(enrichment)
    prompt = template.format(
        client_name=client_name,
        cta=cta,
        company_focus=notes.get("company_focus",""),
        pipeline_summary=notes.get("pipeline_summary",""),
        recent_activity=notes.get("recent_activity",""),
        social_voice=notes.get("social_voice",""),
        positioning_hook=notes.get("positioning_hook","")
    )
    return call_openai(prompt)
