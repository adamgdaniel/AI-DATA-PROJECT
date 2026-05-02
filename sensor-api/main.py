import os
import psycopg2
from fastapi import FastAPI, HTTPException
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")

_bq = None


def bq() -> bigquery.Client:
    global _bq
    if _bq is None:
        _bq = bigquery.Client(project=PROJECT_ID)
    return _bq


def get_db():
    return psycopg2.connect(
        host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD']
    )


def get_parcela_info(parcela_usuario_id: str) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT parcela_id, cultivo, variedad, superficie, lat, lng
        FROM parcelas_usuario WHERE parcela_id = %s
    """, (parcela_usuario_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "parcela_id": row[0],
        "cultivo":    row[1],
        "variedad":   row[2],
        "superficie": float(row[3]) if row[3] else None,
        "lat":        float(row[4]) if row[4] else None,
        "lng":        float(row[5]) if row[5] else None,
    }


def get_sensor_stats(parcel_id: str) -> dict:
    params = [bigquery.ScalarQueryParameter("parcel_id", "STRING", parcel_id)]
    job_cfg = bigquery.QueryJobConfig(query_parameters=params)

    sql_24h = f"""
        SELECT
          AVG(temperatura)       AS temperatura_avg,
          MIN(temperatura)       AS temperatura_min,
          MAX(temperatura)       AS temperatura_max,
          AVG(humedad_ambiental) AS humedad_ambiental_avg,
          AVG(humedad_suelo)     AS humedad_suelo_avg
        FROM `{PROJECT_ID}.agri_data.lecturas_parcelas`
        WHERE parcel_id = @parcel_id
          AND timestamp >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 24 HOUR)
    """
    sql_7d = f"""
        SELECT
          AVG(temperatura)       AS temperatura_avg,
          AVG(humedad_ambiental) AS humedad_ambiental_avg,
          AVG(humedad_suelo)     AS humedad_suelo_avg
        FROM `{PROJECT_ID}.agri_data.lecturas_parcelas`
        WHERE parcel_id = @parcel_id
          AND timestamp >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 168 HOUR)
    """

    row_24h = next(iter(bq().query(sql_24h, job_config=job_cfg).result()), None)
    row_7d  = next(iter(bq().query(sql_7d,  job_config=job_cfg).result()), None)

    def _f(val):
        return round(float(val), 2) if val is not None else None

    stats_24h = {
        "temperatura":       {"avg": _f(row_24h.temperatura_avg),       "min": _f(row_24h.temperatura_min), "max": _f(row_24h.temperatura_max)},
        "humedad_ambiental": {"avg": _f(row_24h.humedad_ambiental_avg)},
        "humedad_suelo":     {"avg": _f(row_24h.humedad_suelo_avg)},
    } if row_24h else {}
    stats_7d = {
        "temperatura":       {"avg": _f(row_7d.temperatura_avg)},
        "humedad_ambiental": {"avg": _f(row_7d.humedad_ambiental_avg)},
        "humedad_suelo":     {"avg": _f(row_7d.humedad_suelo_avg)},
    } if row_7d else {}

    return {"ultimas_24h": stats_24h, "ultimos_7d": stats_7d}


def get_ultimas_acciones(parcela_usuario_id: str) -> list:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT tipo, fecha_accion, notas
            FROM acciones
            WHERE parcela_id = %s
            ORDER BY fecha_accion DESC LIMIT 5
        """, (parcela_usuario_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"tipo": r[0], "fecha": r[1].isoformat(), "notas": r[2]} for r in rows]
    except Exception:
        # La tabla acciones puede no existir aún
        return []


@app.get("/sensores/contexto")
def get_contexto(parcela_id: str):
    """
    Devuelve el estado actual de una parcela: métricas (24h y 7d)
    y últimas acciones del agricultor. Usado como contexto por el agente.
    """
    parcela = get_parcela_info(parcela_id)
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada")

    sensor_stats = get_sensor_stats(parcela_id)
    acciones     = get_ultimas_acciones(parcela_id)
    fuente       = "sensores" if sensor_stats["ultimas_24h"] else "openmeteo"

    return {
        "parcela_usuario_id": parcela_id,
        "parcela_info":       parcela,
        "fuente":             fuente,
        "ultimas_24h":        sensor_stats["ultimas_24h"],
        "ultimos_7d":         sensor_stats["ultimos_7d"],
        "ultimas_acciones":   acciones,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
