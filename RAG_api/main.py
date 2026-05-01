import os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

from chunker import chunk_pdf
from embedder import embed, embed_batch
import bq_store
import gcs_store

app = FastAPI()


class QueryRequest(BaseModel):
    query: str
    cultivo: Optional[str] = None
    tipo_doc: Optional[str] = None
    top_k: int = 3


# ── Ingestión ──────────────────────────────────────────────────────────────────

@app.post("/rag/ingest", status_code=201)
async def ingest(
    file: UploadFile = File(...),
    cultivo: str = Form(...),
    tipo_doc: Optional[str] = Form(None),
    titulo: Optional[str] = Form(None),
):
    """
    Flujo completo de ingestión:
      1. Guarda el PDF original en Cloud Storage  (gs://bucket/docs/cultivo/filename.pdf)
      2. Descarga el PDF de GCS y lo parte en chunks
      3. Genera embeddings con textembedding-gecko@003 (Vertex AI)
      4. Guarda los chunks con embeddings en BigQuery (rag_data.document_chunks)
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan ficheros PDF")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="El fichero está vacío")

    # 1. Cloud Storage — guardar el PDF original
    gcs_path = gcs_store.upload_pdf(pdf_bytes, cultivo, file.filename)

    # 2. Chunking — partir el texto en fragmentos de ~500 palabras
    chunks = chunk_pdf(pdf_bytes)
    if not chunks:
        raise HTTPException(status_code=422, detail="No se pudo extraer texto del PDF")

    # 3. Embeddings — generar vectores con Vertex AI
    embeddings = embed_batch(chunks)

    # 4. BigQuery — guardar chunks con su embedding y el path GCS como doc_path
    rows = [
        {
            "doc_path": gcs_path,   # gs://... para poder relocalizar el original
            "cultivo":  cultivo,
            "tipo_doc": tipo_doc,
            "titulo":   titulo or file.filename,
            "texto":    chunk,
            "embedding": emb,
        }
        for chunk, emb in zip(chunks, embeddings)
    ]
    inserted = bq_store.insert_chunks(rows)

    return {
        "gcs_path":         gcs_path,
        "chunks_insertados": inserted,
    }


@app.post("/rag/reingest")
async def reingest(gcs_path: str, cultivo: str, tipo_doc: Optional[str] = None, titulo: Optional[str] = None):
    """
    Reprocesa un PDF que ya está en Cloud Storage (útil si cambia el modelo de embeddings).
    Borra los chunks antiguos en BQ y genera los nuevos desde el fichero en GCS.
    """
    pdf_bytes = gcs_store.download_pdf(gcs_path)
    chunks    = chunk_pdf(pdf_bytes)
    if not chunks:
        raise HTTPException(status_code=422, detail="No se pudo extraer texto del PDF")

    # Borrar chunks anteriores del mismo documento
    bq_store.delete_document(gcs_path)

    embeddings = embed_batch(chunks)
    rows = [
        {"doc_path": gcs_path, "cultivo": cultivo, "tipo_doc": tipo_doc,
         "titulo": titulo, "texto": chunk, "embedding": emb}
        for chunk, emb in zip(chunks, embeddings)
    ]
    inserted = bq_store.insert_chunks(rows)
    return {"gcs_path": gcs_path, "chunks_insertados": inserted}


# ── Consulta ───────────────────────────────────────────────────────────────────

@app.post("/rag/query")
def query(req: QueryRequest):
    """
    Búsqueda semántica en BigQuery con ML.DISTANCE.
    Filtra por cultivo para evitar mezclar documentación de cultivos distintos.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query no puede estar vacía")

    vector  = embed(req.query)
    results = bq_store.search(vector, cultivo=req.cultivo, tipo_doc=req.tipo_doc, top_k=req.top_k)
    return results


# ── Gestión de documentos ──────────────────────────────────────────────────────

@app.get("/rag/documentos")
def list_documentos():
    """Lista los documentos indexados en BigQuery y los PDFs almacenados en GCS."""
    bq_docs  = bq_store.list_documents()
    gcs_docs = gcs_store.list_pdfs()
    return {"indexados_bq": bq_docs, "pdfs_gcs": gcs_docs}


@app.delete("/rag/documento")
def delete_documento(gcs_path: str):
    """Elimina el PDF de Cloud Storage y sus chunks de BigQuery."""
    chunks_eliminados = bq_store.delete_document(gcs_path)
    gcs_store.delete_pdf(gcs_path)
    return {"gcs_path": gcs_path, "chunks_eliminados": chunks_eliminados}


@app.get("/health")
def health():
    return {"status": "ok"}
