import os
import math
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI()

# ── CONTRATO DE DATOS ──────────────────────────────────────────────────────────
class DiaMeteo(BaseModel):
    fecha: str
    tmax: float
    tmin: float
    humedad_max: float
    humedad_min: float
    viento_velocidad: float  # km/h
    uv_max: float | None = None
    prob_precipitacion: float = 0  # % — limitación conocida, no tenemos mm

class SolicitudRiego(BaseModel):
    parcela_id: str
    codigo_ine: str
    cultivo: str       # "citrico" o "tomate"
    fase: str          # "inicial", "desarrollo", "mediados" o "final"
    prevision: List[DiaMeteo]

# ── MÓDULO 1: PENMAN-MONTEITH ──────────────────────────────────────────────────
def calcular_et0(dia: DiaMeteo, latitud: float = 39.5) -> float:
    """
    Calcula ET0 diaria (mm/día) con Penman-Monteith simplificado FAO-56.
    Latitud por defecto: Valencia (39.5°N)
    """
    try:
        # Temperatura media
        tmedia = (dia.tmax + dia.tmin) / 2

        # Humedad relativa media
        hr_media = (dia.humedad_max + dia.humedad_min) / 2

        # Viento: convertir km/h a m/s
        viento_ms = dia.viento_velocidad / 3.6

        # Presión de vapor de saturación (kPa)
        es = 0.6108 * math.exp((17.27 * tmedia) / (tmedia + 237.3))

        # Presión de vapor real (kPa)
        ea = es * (hr_media / 100)

        # Déficit de presión de vapor
        vpd = es - ea

        # Radiación solar estimada desde UV (MJ/m²/día)
        # Si no hay uv_max usamos estimación por temperatura
        if dia.uv_max:
            rs = dia.uv_max * 2.0
        else:
            rs = 0.16 * math.sqrt(dia.tmax - dia.tmin) * 35

        # Pendiente de la curva de presión de vapor
        delta = (4098 * es) / ((tmedia + 237.3) ** 2)

        # Constante psicrométrica (kPa/°C) — asumimos altitud media
        gamma = 0.067

        # ET0 Penman-Monteith simplificado (FAO-56)
        et0 = (0.408 * delta * rs + gamma * (900 / (tmedia + 273)) * viento_ms * vpd) / \
              (delta + gamma * (1 + 0.34 * viento_ms))

        return round(max(et0, 0), 2)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en ET0: {e}")


def obtener_kc(cultivo: str, fase: str) -> float:
    """Recupera el Kc del CSV — esto es la capa RAG."""
    try:
        df = pd.read_csv("../model-training/data/kc_coeficientes.csv")
        fila = df[(df["cultivo"] == cultivo) & (df["fase"] == fase)]
        if fila.empty:
            raise ValueError(f"Cultivo '{cultivo}' fase '{fase}' no encontrado")
        return float(fila["kc"].values[0])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en Kc: {e}")


# ── ENDPOINT PRINCIPAL ─────────────────────────────────────────────────────────
@app.post("/recomendar")
def recomendar_riego(solicitud: SolicitudRiego):
    kc = obtener_kc(solicitud.cultivo, solicitud.fase)
    resultados = []

    for dia in solicitud.prevision:
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