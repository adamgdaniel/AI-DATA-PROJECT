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


def get_parcela_info(parcela_usuario_id: int) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT parcela_id, cultivo, variedad, superficie, lat, lng
        FROM parcelas_usuario WHERE id = %s
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


def get_sensor_stats(parcela_usuario_id: int) -> dict:
    params = [bigquery.ScalarQueryParameter("parcela_id", "INT64", parcela_usuario_id)]
    job_cfg = bigquery.QueryJobConfig(query_parameters=params)

    sql_24h = f"""
        SELECT variable, AVG(value_avg) AS avg_val,
               MIN(value_min) AS min_val, MAX(value_max) AS max_val
        FROM `{PROJECT_ID}.iot_data.sensor_aggregated`
        WHERE parcela_usuario_id = @parcela_id
          AND window_start >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        GROUP BY variable
    """
    sql_7d = f"""
        SELECT variable, AVG(value_avg) AS avg_val
        FROM `{PROJECT_ID}.iot_data.sensor_aggregated`
        WHERE parcela_usuario_id = @parcela_id
          AND window_start >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 168 HOUR)
        GROUP BY variable
    """

    stats_24h = {
        r.variable: {"avg": round(float(r.avg_val), 2),
                     "min": round(float(r.min_val), 2),
                     "max": round(float(r.max_val), 2)}
        for r in bq().query(sql_24h, job_config=job_cfg).result()
    }
    stats_7d = {
        r.variable: {"avg": round(float(r.avg_val), 2)}
        for r in bq().query(sql_7d, job_config=job_cfg).result()
    }
    return {"ultimas_24h": stats_24h, "ultimos_7d": stats_7d}


def get_ultimas_acciones(parcela_usuario_id: int) -> list:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT tipo, fecha_accion, notas
            FROM acciones
            WHERE parcela_usuario_id = %s
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
def get_contexto(parcela_id: int):
    """
    Devuelve el estado actual de una parcela: datos de sensores (24h y 7d)
    y últimas acciones del agricultor. Usado como contexto por el agente.
    """
    parcela = get_parcela_info(parcela_id)
    if not parcela:
        raise HTTPException(status_code=404, detail="Parcela no encontrada")

    sensor_stats = get_sensor_stats(parcela_id)
    acciones     = get_ultimas_acciones(parcela_id)
    fuente       = "sensores" if sensor_stats["ultimas_24h"] else "aemet"

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
