import os
from google.cloud import storage

PROJECT_ID  = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")
BUCKET_NAME = os.environ.get("GCS_BUCKET", f"{PROJECT_ID}-agro-docs")

_client = None


def _gcs() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client(project=PROJECT_ID)
    return _client


def upload_pdf(pdf_bytes: bytes, cultivo: str, filename: str) -> str:
    """
    Sube el PDF a Cloud Storage y devuelve la ruta GCS (gs://bucket/docs/cultivo/filename.pdf).
    La ruta GCS se usa como doc_path en BigQuery para poder relocalizar el fichero original.
    """
    blob_name = f"docs/{cultivo}/{filename}"
    bucket = _gcs().bucket(BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(pdf_bytes, content_type="application/pdf")
    return f"gs://{BUCKET_NAME}/{blob_name}"


def download_pdf(gcs_path: str) -> bytes:
    """Descarga un PDF desde su ruta GCS y devuelve los bytes."""
    # gcs_path tiene formato gs://bucket/blob_name
    path = gcs_path.removeprefix("gs://")
    bucket_name, blob_name = path.split("/", 1)
    bucket = _gcs().bucket(bucket_name)
    return bucket.blob(blob_name).download_as_bytes()


def list_pdfs() -> list[dict]:
    """Lista todos los PDFs subidos al bucket."""
    bucket = _gcs().bucket(BUCKET_NAME)
    blobs = bucket.list_blobs(prefix="docs/")
    return [
        {
            "gcs_path":   f"gs://{BUCKET_NAME}/{b.name}",
            "size_kb":    round(b.size / 1024, 1),
            "updated_at": b.updated.isoformat(),
        }
        for b in blobs
        if b.name.endswith(".pdf")
    ]


def delete_pdf(gcs_path: str) -> None:
    path = gcs_path.removeprefix("gs://")
    bucket_name, blob_name = path.split("/", 1)
    _gcs().bucket(bucket_name).blob(blob_name).delete()
