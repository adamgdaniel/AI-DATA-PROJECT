"""
Sensor API — API 1: Contexto de Sensores
=========================================
Endpoint GET /sensores/contexto?parcela_id=X

Lee métricas de BigQuery (agri_data.lecturas_parcelas) y acciones
del agricultor (agri_data.eventos_agricolas) para devolver el contexto
numérico que consume el Agente Vertex AI.
"""

import os
import logging
from fastapi import FastAPI, Query
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sensor API — AgroMétrica",
    description="Devuelve contexto de parcela (métricas 24h/7d + acciones recientes) para el agente.",
    version="1.0.0",
)

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")
BQ_DATASET = os.environ.get("BQ_DATASET", "agri_data")

# ── CLIENTE BIGQUERY (singleton lazy) ──────────────────────────────────────────

_bq = None


def bq() -> bigquery.Client:
    """Devuelve un cliente BQ reutilizable (stateless container friendly)."""
    global _bq
    if _bq is None:
        _bq = bigquery.Client(project=PROJECT_ID)
    return _bq


def _run_query(sql: str, params: list) -> list:
    """Ejecuta una query parametrizada y devuelve las filas como dicts."""
    job_cfg = bigquery.QueryJobConfig(query_parameters=params)
    try:
        results = bq().query(sql, job_config=job_cfg).result()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error("Error ejecutando query BQ: %s", e)
        raise


def _safe_round(val, decimals=2):
    """Redondea un valor numérico; devuelve None si es None."""
    return round(float(val), decimals) if val is not None else None


# ── MÉTRICAS ÚLTIMAS 24 HORAS ─────────────────────────────────────────────────

def get_stats_24h(parcela_id: str) -> dict:
    """
    Calcula medias de temperatura, humedad_suelo y humedad_ambiental
    de las últimas 24 horas para una parcela.
    """
    sql = f"""
        SELECT
            AVG(temperatura)       AS temp_media,
            AVG(humedad_suelo)     AS humedad_suelo_media,
            AVG(humedad_ambiental) AS humedad_ambiental_media
        FROM `{PROJECT_ID}.{BQ_DATASET}.lecturas_parcelas`
        WHERE parcel_id = @parcela_id
          AND timestamp >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 24 HOUR)
    """
    params = [bigquery.ScalarQueryParameter("parcela_id", "STRING", parcela_id)]
    rows = _run_query(sql, params)

    if not rows or rows[0].get("temp_media") is None:
        return {
            "temp_media": None,
            "humedad_suelo_media": None,
            "humedad_ambiental_media": None,
        }

    row = rows[0]
    return {
        "temp_media": _safe_round(row["temp_media"]),
        "humedad_suelo_media": _safe_round(row["humedad_suelo_media"]),
        "humedad_ambiental_media": _safe_round(row["humedad_ambiental_media"]),
    }


# ── MÉTRICAS ÚLTIMOS 7 DÍAS ──────────────────────────────────────────────────

def get_stats_7d(parcela_id: str) -> dict:
    """
    Calcula métricas acumuladas/medias de los últimos 7 días:
    - temp_media, precipitacion_acumulada, et0_acumulado
    """
    sql = f"""
        SELECT
            AVG(temperatura)        AS temp_media,
            SUM(precipitacion_mm)   AS precipitacion_acumulada,
            SUM(et0)                AS et0_acumulado
        FROM `{PROJECT_ID}.{BQ_DATASET}.lecturas_parcelas`
        WHERE parcel_id = @parcela_id
          AND timestamp >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 168 HOUR)
    """
    params = [bigquery.ScalarQueryParameter("parcela_id", "STRING", parcela_id)]
    rows = _run_query(sql, params)

    if not rows or rows[0].get("temp_media") is None:
        return {
            "temp_media": None,
            "precipitacion_acumulada": None,
            "et0_acumulado": None,
        }

    row = rows[0]
    return {
        "temp_media": _safe_round(row["temp_media"]),
        "precipitacion_acumulada": _safe_round(row["precipitacion_acumulada"]),
        "et0_acumulado": _safe_round(row["et0_acumulado"]),
    }


# ── ACCIONES RECIENTES (BigQuery: eventos_agricolas) ──────────────────────────

def get_acciones_recientes(parcela_id: str, limit: int = 5) -> list:
    """
    Lee las últimas acciones del agricultor (riego, abonado, poda)
    desde BigQuery (agri_data.eventos_agricolas).
    """
    sql = f"""
        SELECT
            tipo_evento AS tipo,
            timestamp   AS fecha,
            valor       AS detalle
        FROM `{PROJECT_ID}.{BQ_DATASET}.eventos_agricolas`
        WHERE entity_type = 'parcela'
          AND entity_id   = @parcela_id
        ORDER BY timestamp DESC
        LIMIT @limit
    """
    params = [
        bigquery.ScalarQueryParameter("parcela_id", "STRING", parcela_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    try:
        rows = _run_query(sql, params)
        return [
            {
                "tipo": row["tipo"],
                "fecha": row["fecha"].isoformat() if row.get("fecha") else None,
                "detalle": row.get("detalle"),
            }
            for row in rows
        ]
    except Exception:
        # La tabla puede no tener datos aún
        logger.warning("No se pudieron obtener acciones para parcela %s", parcela_id)
        return []


# ── INFORMACIÓN DE CULTIVO (de la propia tabla de lecturas) ───────────────────

def get_cultivo_info(parcela_id: str) -> str | None:
    """
    Obtiene el tipo de cultivo de la parcela leyendo la última fila
    de lecturas_parcelas (campo tipo_cultivo).
    """
    sql = f"""
        SELECT tipo_cultivo
        FROM `{PROJECT_ID}.{BQ_DATASET}.lecturas_parcelas`
        WHERE parcel_id = @parcela_id
          AND tipo_cultivo IS NOT NULL
        ORDER BY timestamp DESC
        LIMIT 1
    """
    params = [bigquery.ScalarQueryParameter("parcela_id", "STRING", parcela_id)]
    rows = _run_query(sql, params)
    if rows:
        return rows[0].get("tipo_cultivo")
    return None


# ── ENDPOINT PRINCIPAL ────────────────────────────────────────────────────────

@app.get("/sensores/contexto")
def get_contexto(
    parcela_id: str = Query(..., description="ID de la parcela a consultar"),
):
    """
    Devuelve el contexto completo de una parcela:
    - Métricas de las últimas 24h (temp, humedad suelo, humedad ambiental)
    - Métricas de los últimos 7d (temp media, precipitación acumulada, ET₀ acumulado)
    - Acciones recientes del agricultor (riego, abonado, poda)

    Este contexto se inyecta en el system prompt del agente Vertex AI.
    """
    # 1. Obtener métricas (pueden ser None si aún no hay datos en BigQuery)
    stats_24h = get_stats_24h(parcela_id)
    stats_7d = get_stats_7d(parcela_id)

    # 2. Obtener cultivo y acciones
    cultivo = get_cultivo_info(parcela_id)
    acciones = get_acciones_recientes(parcela_id)

    # 3. Construir respuesta alineada con el contrato del plan
    return {
        "parcela_id": parcela_id,
        "cultivo": cultivo,
        "ultimas_24h": {
            "temp_media": stats_24h["temp_media"],
            "humedad_suelo_media": stats_24h["humedad_suelo_media"],
            "humedad_ambiental_media": stats_24h["humedad_ambiental_media"],
        },
        "ultimos_7d": {
            "temp_media": stats_7d["temp_media"],
            "precipitacion_acumulada": stats_7d["precipitacion_acumulada"],
            "et0_acumulado": stats_7d["et0_acumulado"],
        },
        "acciones_recientes": acciones,
    }


@app.get("/health")
def health():
    """Health check para Cloud Run."""
    return {"status": "ok"}
