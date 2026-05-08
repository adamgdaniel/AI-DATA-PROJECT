import os
import logging
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime, timezone
from google.cloud import firestore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARS = ",".join([
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "shortwave_radiation",
    "et0_fao_evapotranspiration",
])

DAILY_VARS = ",".join([
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "shortwave_radiation_sum",
    "weathercode",
])

# WMO weather codes → texto en español
WMO_ES = {
    0: "Despejado",
    1: "Principalmente despejado", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Niebla", 48: "Niebla con escarcha",
    51: "Llovizna ligera", 53: "Llovizna moderada", 55: "Llovizna intensa",
    61: "Lluvia ligera", 63: "Lluvia moderada", 65: "Lluvia intensa",
    71: "Nevada ligera", 73: "Nevada moderada", 75: "Nevada intensa",
    77: "Granizo",
    80: "Chubascos ligeros", 81: "Chubascos moderados", 82: "Chubascos intensos",
    85: "Chubascos de nieve", 86: "Chubascos de nieve intensos",
    95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta con granizo intenso",
}


def get_db():
    return psycopg2.connect(
        host=f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}",
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def get_municipios_con_parcelas(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                municipio,
                AVG(lat)::float  AS lat,
                AVG(lng)::float  AS lng,
                JSON_AGG(
                    JSON_BUILD_OBJECT(
                        'parcela_id', parcela_id,
                        'usuario_id', usuario_id::text
                    )
                ) AS parcelas
            FROM parcelas_usuario
            WHERE lat IS NOT NULL AND lng IS NOT NULL
            GROUP BY municipio
        """)
        return cur.fetchall()


def fetch_meteo(lat, lng):
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": HOURLY_VARS,
        "daily": DAILY_VARS,
        "past_hours": 2,
        "forecast_days": 16,
        "timezone": "Europe/Madrid",
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extraer_hora_actual(data):
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return None

    hora_actual = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
    idx = times.index(hora_actual) if hora_actual in times else len(times) - 1

    return {
        "temperatura": hourly["temperature_2m"][idx],
        "humedad_ambiental": hourly["relative_humidity_2m"][idx],
        "precipitacion_mm": hourly["precipitation"][idx],
        "radiacion_solar": hourly["shortwave_radiation"][idx],
        "et0": hourly["et0_fao_evapotranspiration"][idx],
    }


def extraer_forecast(data):
    daily = data.get("daily", {})
    times = daily.get("time", [])
    forecast = []
    for i, fecha in enumerate(times):
        wmo = daily["weathercode"][i]
        forecast.append({
            "fecha": fecha,
            "temp_max": daily["temperature_2m_max"][i],
            "temp_min": daily["temperature_2m_min"][i],
            "precipitacion_mm": daily["precipitation_sum"][i],
            "et0": daily["et0_fao_evapotranspiration"][i],
            "radiacion_solar": daily["shortwave_radiation_sum"][i],
            "estado_cielo": WMO_ES.get(wmo, "Desconocido"),
        })
    return forecast


def escribir_firestore(db, parcelas, estado_actual, forecast):
    batch = db.batch()
    datos = {
        **estado_actual,
        "forecast": forecast,
        "meteo_updated_at": datetime.now(timezone.utc),
    }
    for p in parcelas:
        ref = (
            db.collection("usuarios")
            .document(p["usuario_id"])
            .collection("parcelas")
            .document(p["parcela_id"])
        )
        batch.set(ref, datos, merge=True)
    batch.commit()


def main():
    log.info("Iniciando ingesta Open-Meteo")
    conn = get_db()
    db = firestore.Client()

    try:
        municipios = get_municipios_con_parcelas(conn)
        log.info(f"{len(municipios)} municipios con parcelas")

        for m in municipios:
            municipio_id = m["municipio"]
            try:
                meteo = fetch_meteo(m["lat"], m["lng"])
                estado = extraer_hora_actual(meteo)
                if not estado:
                    log.warning(f"Sin datos actuales para municipio {municipio_id}")
                    continue
                forecast = extraer_forecast(meteo)
                escribir_firestore(db, m["parcelas"], estado, forecast)
                log.info(f"Municipio {municipio_id}: {len(m['parcelas'])} parcelas actualizadas")
            except requests.RequestException as e:
                log.error(f"Open-Meteo error municipio {municipio_id}: {e}")
            except Exception as e:
                log.error(f"Error municipio {municipio_id}: {e}")
    finally:
        conn.close()

    log.info("Ingesta completada")


if __name__ == "__main__":
    main()
