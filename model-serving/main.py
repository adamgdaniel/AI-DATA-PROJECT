import os
import json
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from google.cloud import secretmanager

app = FastAPI()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "project-7f8b4dee-2b72-40f2-941")

# ── SECRET MANAGER ─────────────────────────────────────────────────────────────
def get_database_url() -> str:
    local_url = os.environ.get("DATABASE_URL")
    if local_url:
        return local_url
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/aemet-db-url/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        raise RuntimeError(f"Error obteniendo secret: {e}")

DATABASE_URL = get_database_url()

# ── CONTRATO DE DATOS ──────────────────────────────────────────────────────────
class DiaMeteo(BaseModel):
    fecha: str
    et0_mm: float
    precipitacion_mm: float
    prob_precipitacion: Optional[float] = 0
    estado_cielo_desc: Optional[str] = None

class SolicitudRiego(BaseModel):
    parcela_id: str
    codigo_ine: str
    cultivo: str
    fase: str
    prevision: Optional[List[DiaMeteo]] = None

# ── MÓDULO 1: COEFICIENTES KC ──────────────────────────────────────────────────
def obtener_kc(cultivo: str, fase: str) -> float:
    try:
        with open("data/cultivos_referencia.json", "r") as f:
            cultivos = json.load(f)
        if cultivo not in cultivos:
            raise ValueError(f"Cultivo '{cultivo}' no encontrado")
        mapa_fases = {
            "inicial":    "kc_inicio",
            "desarrollo": "kc_desarrollo",
            "mediados":   "kc_medio",
            "final":      "kc_final"
        }
        if fase not in mapa_fases:
            raise ValueError(f"Fase '{fase}' no válida")
        return float(cultivos[cultivo][mapa_fases[fase]])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en Kc: {e}")

# ── MÓDULO 2: LECTURA DE PREVISIÓN DESDE BD ────────────────────────────────────
def get_prevision_db(codigo_ine: str) -> List[DiaMeteo]:
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        fecha_prevision,
                        et0_evapotranspiracion,
                        precipitacion_mm,
                        prob_precipitacion,
                        estado_cielo_desc
                    FROM prevision_meteorologica
                    WHERE codigo_ine = %s
                    ORDER BY fecha_prevision ASC
                """, (codigo_ine,))
                rows = cur.fetchall()
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"Sin datos de previsión para municipio {codigo_ine}"
            )
        return [
            DiaMeteo(
                fecha=str(row[0]),
                et0_mm=float(row[1] or 0),
                precipitacion_mm=float(row[2] or 0),
                prob_precipitacion=float(row[3] or 0),
                estado_cielo_desc=row[4]
            )
            for row in rows
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo previsión: {e}")

# ── MÓDULO 3: MOTOR AGRONÓMICO ─────────────────────────────────────────────────
def calcular_deficit(et0_mm: float, kc: float, precipitacion_mm: float) -> dict:
    """
    Balance hídrico FAO-56:
      ETc  = ET0 * Kc          (necesidad hídrica real del cultivo)
      Déficit = ETc - Lluvia   (agua que hay que aportar mediante riego)
    """
    etc_mm = round(et0_mm * kc, 2)
    deficit_mm = round(max(etc_mm - precipitacion_mm, 0), 2)
    return {"etc_mm": etc_mm, "deficit_mm": deficit_mm}

# ── ENDPOINT PRINCIPAL ─────────────────────────────────────────────────────────
@app.post("/recomendar")
def recomendar_riego(solicitud: SolicitudRiego):
    kc = obtener_kc(solicitud.cultivo, solicitud.fase)
    prevision = solicitud.prevision or get_prevision_db(solicitud.codigo_ine)

    resultados = []
    for dia in prevision:
        balance = calcular_deficit(dia.et0_mm, kc, dia.precipitacion_mm)
        resultados.append({
            "fecha":             dia.fecha,
            "et0_mm":            dia.et0_mm,
            "etc_mm":            balance["etc_mm"],
            "precipitacion_mm":  dia.precipitacion_mm,
            "deficit_mm":        balance["deficit_mm"],
            "prob_precipitacion": dia.prob_precipitacion,
            "estado_cielo":      dia.estado_cielo_desc,
            "kc_aplicado":       kc,
        })

    return {
        "parcela_id":          solicitud.parcela_id,
        "cultivo":             solicitud.cultivo,
        "fase":                solicitud.fase,
        "recomendacion_dias":  resultados,
    }

@app.get("/health")
def health():
    return {"status": "ok"}