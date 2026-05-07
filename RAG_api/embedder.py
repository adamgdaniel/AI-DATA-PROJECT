import os
import time
import vertexai
from vertexai.language_models import TextEmbeddingModel

vertexai.init(
    project=os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941"),
    location="us-central1"
)

_model = None

def _get_model() -> TextEmbeddingModel:
    global _model
    if _model is None:
        _model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    return _model

def embed(text: str) -> list[float]:
    return _get_model().get_embeddings([text])[0].values

def embed_batch(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    results = []
    for i in range(0, len(texts), 125):
        batch = texts[i:i + 125]
        batch_results = model.get_embeddings(batch)
        results.extend([r.values for r in batch_results])
        time.sleep(15)  # para evitar 20k tokens/min
    return results