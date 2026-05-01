import os
import uuid
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")
DATASET    = "rag_data"
TABLE      = "document_chunks"
FULL_TABLE = f"{PROJECT_ID}.{DATASET}.{TABLE}"

_client = None


def _bq() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=PROJECT_ID)
    return _client


def insert_chunks(chunks: list[dict]) -> int:
    """
    chunks: lista de dicts con claves doc_path, cultivo, tipo_doc, titulo, texto, embedding
    """
    rows = [
        {
            "chunk_id":  uuid.uuid4().hex,
            "doc_path":  c["doc_path"],
            "cultivo":   c.get("cultivo"),
            "tipo_doc":  c.get("tipo_doc"),
            "titulo":    c.get("titulo"),
            "texto":     c["texto"],
            "embedding": c["embedding"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for c in chunks
    ]
    errors = _bq().insert_rows_json(FULL_TABLE, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")
    return len(rows)


def search(query_vector: list[float], cultivo: str = None, tipo_doc: str = None, top_k: int = 3) -> list[dict]:
    filters = []
    params = [
        bigquery.ArrayQueryParameter("query_vector", "FLOAT64", query_vector),
        bigquery.ScalarQueryParameter("top_k", "INT64", top_k),
    ]

    if cultivo:
        filters.append("cultivo = @cultivo")
        params.append(bigquery.ScalarQueryParameter("cultivo", "STRING", cultivo))
    if tipo_doc:
        filters.append("tipo_doc = @tipo_doc")
        params.append(bigquery.ScalarQueryParameter("tipo_doc", "STRING", tipo_doc))

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = f"""
        SELECT chunk_id, doc_path, cultivo, tipo_doc, titulo, texto,
               ML.DISTANCE(embedding, @query_vector, 'COSINE') AS distance
        FROM `{FULL_TABLE}`
        {where}
        ORDER BY distance ASC
        LIMIT @top_k
    """
    rows = _bq().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return [
        {
            "chunk_id": r.chunk_id,
            "doc_path": r.doc_path,
            "cultivo":  r.cultivo,
            "tipo_doc": r.tipo_doc,
            "titulo":   r.titulo,
            "texto":    r.texto,
            "score":    round(1 - float(r.distance), 4),
        }
        for r in rows
    ]


def delete_document(doc_path: str) -> int:
    sql = f"DELETE FROM `{FULL_TABLE}` WHERE doc_path = @doc_path"
    job = _bq().query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("doc_path", "STRING", doc_path)]
        )
    )
    job.result()
    return job.num_dml_affected_rows


def list_documents() -> list[dict]:
    sql = f"""
        SELECT doc_path, cultivo, tipo_doc, COUNT(*) AS chunks, MAX(created_at) AS indexed_at
        FROM `{FULL_TABLE}`
        GROUP BY doc_path, cultivo, tipo_doc
        ORDER BY indexed_at DESC
    """
    rows = _bq().query(sql).result()
    return [
        {
            "doc_path":   r.doc_path,
            "cultivo":    r.cultivo,
            "tipo_doc":   r.tipo_doc,
            "chunks":     r.chunks,
            "indexed_at": r.indexed_at.isoformat() if r.indexed_at else None,
        }
        for r in rows
    ]
