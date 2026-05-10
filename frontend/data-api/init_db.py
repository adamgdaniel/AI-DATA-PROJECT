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

cur.execute("""
    CREATE TABLE IF NOT EXISTS parcelas_usuario (
        id             SERIAL PRIMARY KEY,
        usuario_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        parcela_id     VARCHAR(50) NOT NULL,
        provincia      INTEGER,
        municipio      INTEGER,
        poligono       INTEGER,
        parcela        INTEGER,
        recinto        INTEGER,
        nombre         VARCHAR(100),
        cultivo        VARCHAR(100),
        variedad       VARCHAR(100),
        edad_cultivo   VARCHAR(20),
        superficie     NUMERIC(10,4),
        lat            NUMERIC(10,6),
        lng            NUMERIC(10,6),
        geometria      JSONB,
        zonas          JSONB DEFAULT '[]'::jsonb,
        grid           JSONB DEFAULT '{}'::jsonb,
        fecha_registro TIMESTAMP DEFAULT NOW(),
        UNIQUE(usuario_id, parcela_id)
    )
""")

cur.execute("ALTER TABLE parcelas_usuario ADD COLUMN IF NOT EXISTS nombre VARCHAR(100)")

cur.execute("""
    CREATE TABLE IF NOT EXISTS invernaderos (
        id                    SERIAL PRIMARY KEY,
        usuario_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        nombre                VARCHAR(100) NOT NULL,
        temperatura_entity_id VARCHAR(200),
        hum_amb_entity_id     VARCHAR(200),
        created_at            TIMESTAMP DEFAULT NOW()
    )
""")

cur.execute("""
    CREATE TABLE IF NOT EXISTS plantas_invernadero (
        id             SERIAL PRIMARY KEY,
        invernadero_id INTEGER NOT NULL REFERENCES invernaderos(id) ON DELETE CASCADE,
        tipo           VARCHAR(50) NOT NULL,
        variedad       VARCHAR(100),
        grid_col       INTEGER NOT NULL,
        grid_row       INTEGER NOT NULL,
        soil_entity_id VARCHAR(200),
        created_at     TIMESTAMP DEFAULT NOW()
    )
""")

conn.commit()
cur.close()
conn.close()
