import os
import vertexai
from vertexai.language_models import TextEmbeddingModel

vertexai.init(
    project=os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941"),
    location=os.environ.get("GCP_REGION", "us-central1")
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
    # gecko@003 acepta hasta 250 textos por llamada
    results = _get_model().get_embeddings(texts)
    return [r.values for r in results]
