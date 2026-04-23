import os
import math
import json
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
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
    tmax: float
    tmin: float
    humedad_max: float
    humedad_min: float
    viento_velocidad: float
    uv_max: float | None = None
    prob_precipitacion: float = 0

class SolicitudRiego(BaseModel):
    parcela_id: str
    codigo_ine: str
    cultivo: str
    fase: str
    prevision: List[DiaMeteo] | None = None

# ── MÓDULO 1: PENMAN-MONTEITH ──────────────────────────────────────────────────
def calcular_et0(dia: DiaMeteo, latitud: float = 39.5) -> float:
    try:
        tmedia = (dia.tmax + dia.tmin) / 2
        hr_media = (dia.humedad_max + dia.humedad_min) / 2
        viento_ms = dia.viento_velocidad / 3.6
        es = 0.6108 * math.exp((17.27 * tmedia) / (tmedia + 237.3))
        ea = es * (hr_media / 100)
        vpd = es - ea
        if dia.uv_max:
            rs = dia.uv_max * 2.0
        else:
            rs = 0.16 * math.sqrt(abs(dia.tmax - dia.tmin)) * 35
        delta = (4098 * es) / ((tmedia + 237.3) ** 2)
        gamma = 0.067
        et0 = (0.408 * delta * rs + gamma * (900 / (tmedia + 273)) * viento_ms * vpd) / \
              (delta + gamma * (1 + 0.34 * viento_ms))
        return round(max(et0, 0), 2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en ET0: {e}")

# ── MÓDULO 2: RAG — COEFICIENTES KC ───────────────────────────────────────────
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

# ── MÓDULO 3: CONEXIÓN A BASE DE DATOS ────────────────────────────────────────
def get_prevision_db(codigo_ine: str) -> list:
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT fecha_prevision, tmax, tmin,
                           humedad_max, humedad_min,
                           viento_velocidad, uv_max, prob_precipitacion
                    FROM prevision_meteorologica
                    WHERE codigo_ine = %s
                    ORDER BY fecha_prevision ASC
                """, (codigo_ine,))
                rows = cur.fetchall()
        return [
            DiaMeteo(
                fecha=str(row[0]),
                tmax=row[1] or 20.0,
                tmin=row[2] or 10.0,
                humedad_max=row[3] or 70.0,
                humedad_min=row[4] or 40.0,
                viento_velocidad=row[5] or 10.0,
                uv_max=row[6],
                prob_precipitacion=row[7] or 0
            )
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo previsión: {e}")

# ── MÓDULO 4: ENDPOINT PRINCIPAL ──────────────────────────────────────────────
@app.post("/recomendar")
def recomendar_riego(solicitud: SolicitudRiego):
    kc = obtener_kc(solicitud.cultivo, solicitud.fase)
    prevision = solicitud.prevision or get_prevision_db(solicitud.codigo_ine)
    resultados = []
    for dia in prevision:
        et0 = calcular_et0(dia)
        etc = round(et0 * kc, 2)
        resultados.append({
            "fecha": dia.fecha,
            "et0_mm": et0,
            "etc_mm": etc,
            "kc_aplicado": kc,
            "nota": "Lluvia no disponible en mm — limitación AEMET"
        })
    return {
        "parcela_id": solicitud.parcela_id,
        "cultivo": solicitud.cultivo,
        "fase": solicitud.fase,
        "recomendacion_7dias": resultados
    }

@app.get("/health")
def health():
    return {"status": "ok"}