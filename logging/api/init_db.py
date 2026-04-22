from dotenv import load_dotenv
import psycopg2
import bcrypt
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
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL
    )
""")

cur.execute("""
    CREATE TABLE IF NOT EXISTS parcelas_usuario (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        parcela_id VARCHAR(50) NOT NULL,
        provincia INTEGER,
        municipio INTEGER,
        poligono INTEGER,
        parcela INTEGER,
        recinto INTEGER,
        cultivo VARCHAR(100),
        superficie NUMERIC(10,4),
        lat NUMERIC(10,6),
        lng NUMERIC(10,6),
        fecha_registro TIMESTAMP DEFAULT NOW(),
        UNIQUE(usuario_id, parcela_id)
    )
""")

password_hash = bcrypt.hashpw(os.environ['TEST_PASSWORD'].encode(), bcrypt.gensalt()).decode()
cur.execute(
    "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
    (os.environ['TEST_USERNAME'], password_hash)
)

conn.commit()
cur.close()
conn.close()
