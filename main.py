import typer
from app.pipeline import run_enrichment
from app.config import load_config

app = typer.Typer(help="AI Outreach Personalization Agent — Step 1 (Website Enrichment)")

@app.command()
def enrich(config: str = typer.Argument(..., help="Path to YAML config"),
           input: str = typer.Argument(..., help="Path to input prospects CSV"),
           output: str = typer.Argument(..., help="Path to write enriched CSV")):
    cfg = load_config(config)
    run_enrichment(cfg, input, output)

if __name__ == "__main__":
    app()
