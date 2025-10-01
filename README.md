# AI Outreach Personalization Agent — Step 1 (Website Enrichment)

This is a **config-driven enrichment engine** that reads a CSV of prospects, visits company websites,
extracts relevant text (home/about/products/research/pipeline/etc.), summarizes it with an LLM into **structured notes**,
and writes those notes back to a CSV. This is the *agent* legwork (act → perceive → summarize).

## Run locally

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...  # or set in your env
python main.py enrich --config configs/weclick.yaml --input data/prospects.sample.csv --output data/enriched.weclick.csv
python main.py enrich --config configs/drugengine.yaml --input data/prospects.sample.csv --output data/enriched.drugengine.csv
```

> Note: This environment cannot fetch the web; run locally to crawl real sites.

## Files
- `main.py` — CLI entrypoint (Typer)
- `app/config.py` — YAML → EnrichmentConfig
- `app/fetcher.py` — Website fetch + internal link discovery
- `app/parser.py` — HTML → clean text
- `app/summarizer.py` — Chooses prompt by enrichment mode (`general`|`pipeline`|`social`), OpenAI JSON output
- `app/pipeline.py` — Orchestrates CSV rows → pages → summary → CSV
- `prompts/` — Three summarizer templates (general, pipeline, social)
- `configs/weclick.yaml` — WeClick (social/brand voice)
- `configs/drugengine.yaml` — Drug Engine Pharma (pipeline focus)
- `data/prospects.sample.csv` — Demo input
- `quickstart_agent.py` — One-file minimal runner (no configs, general mode)
