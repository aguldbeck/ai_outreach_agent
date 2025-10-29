from pydantic import BaseModel
from typing import List
import yaml

class EnrichmentConfig(BaseModel):
    client_name: str
    positioning: str
    tone: str
    cta: str
    enrichment: str = "general"  # general | pipeline | social
    target_paths: List[str] = [
        "about", "company", "team", "mission",
        "product", "products", "solutions", "platform",
        "research", "pipeline", "clinical", "trial",
        "news", "press", "blog", "insights", "publications"
    ]
    max_pages: int = 5
    max_chars_per_page: int = 4000

def load_config(path: str) -> EnrichmentConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return EnrichmentConfig(**data)
