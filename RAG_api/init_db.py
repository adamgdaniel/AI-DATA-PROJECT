from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()

conn = psycopg2.connect(
    host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
    database=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD']
)
cur = conn.cursor()

# pgvector extension — disponible en Cloud SQL PostgreSQL 15
cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

# Tabla de chunks con embedding de 768 dimensiones (text-multilingual-embedding-002)
cur.execute("""
    CREATE TABLE IF NOT EXISTS document_chunks (
        id         SERIAL PRIMARY KEY,
        chunk_id   VARCHAR(100) UNIQUE NOT NULL,
        doc_path   VARCHAR(500) NOT NULL,
        cultivo    VARCHAR(100),
        tipo_doc   VARCHAR(50),
        titulo     VARCHAR(500),
        texto      TEXT NOT NULL,
        embedding  vector(768),
        created_at TIMESTAMP DEFAULT NOW()
    )
""")

# Índice de similitud coseno para búsqueda vectorial
cur.execute("""
    CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50)
""")

# Índice para filtrar por cultivo sin escanear toda la tabla
cur.execute("""
    CREATE INDEX IF NOT EXISTS document_chunks_cultivo_idx
    ON document_chunks (cultivo)
""")

conn.commit()
cur.close()
conn.close()
print("RAG tables ready")
