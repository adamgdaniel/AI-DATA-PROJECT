"""
AgroMétrica — Pipeline de datos meteorológicos
================================================
Descarga datos históricos y forecast de Open-Meteo para las parcelas del MVP.
Genera 3 archivos listos para el equipo de IA:
- datos_diarios_parcela.csv  (histórico + forecast)
- cultivos_referencia.json   (Kc y metadata por cultivo)
- parcelas.json              (metadata de cada parcela)

Uso:
python agrometrica_data_pipeline.py

Sin API key. Sin registro. Sin coste.
"""

import requests
import pandas as pd
import json
import time
from datetime import datetime, timedelta

# ============================================================
# CONFIGURACIÓN DE PARCELAS
# ============================================================
# Añade más parcelas aquí cuando las tengáis localizadas.
# Solo necesitas: coordenadas, cultivo, y referencia catastral.

PARCELAS = {
    "valencia_citricos": {
        "ref_catastral": "46017A018000410000IE",
        "subparcela": "b",
        "municipio": "Aigües Vives",
        "provincia": "Valencia",
        "comunidad": "Comunitat Valenciana",
        "cultivo": "citricos",
        "superficie_ha": 4.96,
        "superficie_total_parcela_ha": 7.5,
        "regadio": True,
        "lat": 39.0790,
        "lon": -0.3240,
        "notas": "Para datos meteorológicos se usa el centroide general (resolución 1km, equivalente para toda la parcela). Para procesamiento satelital (NDVI), recortar únicamente la subparcela b (naranjos, zona rectangular con filas regulares). La parcela catastral completa incluye zona de monte al sureste que se excluye del análisis."
    },
    # --- DESCOMENTAR CUANDO TENGÁIS LAS PARCELAS ---
    # "rioja_vinedo": {
    #     "ref_catastral": "PENDIENTE",
    #     "municipio": "Alfaro",
    #     "provincia": "La Rioja",
    #     "comunidad": "La Rioja",
    #     "cultivo": "vinedo",
    #     "superficie_ha": 0,
    #     "regadio": True,
    #     "lat": 42.1780,
    #     "lon": -1.7490,
    #     "notas": ""
    # },
    # "jaen_olivar": {
    #     "ref_catastral": "PENDIENTE",
    #     "municipio": "Martos",
    #     "provincia": "Jaén",
    #     "comunidad": "Andalucía",
    #     "cultivo": "olivar",
    #     "superficie_ha": 0,
    #     "regadio": False,
    #     "lat": 37.7210,
    #     "lon": -3.9680,
    #     "notas": ""
    # },
    # "castilla_cereal": {
    #     "ref_catastral": "PENDIENTE",
    #     "municipio": "Medina de Rioseco",
    #     "provincia": "Valladolid",
    #     "comunidad": "Castilla y León",
    #     "cultivo": "cereal",
    #     "superficie_ha": 0,
    #     "regadio": False,
    #     "lat": 41.8870,
    #     "lon": -5.0590,
    #     "notas": ""
    # },
    # "murcia_almendro": {
    #     "ref_catastral": "PENDIENTE",
    #     "municipio": "Cieza",
    #     "provincia": "Murcia",
    #     "comunidad": "Región de Murcia",
    #     "cultivo": "almendro",
    #     "superficie_ha": 0,
    #     "regadio": True,
    #     "lat": 38.2390,
    #     "lon": -1.4180,
    #     "notas": ""
    # },
}

# ============================================================
# DATOS ESTÁTICOS DE CULTIVOS (FAO-56)
# ============================================================

CULTIVOS = {
    "citricos": {
        "nombre": "Naranjo",
        "nombre_cientifico": "Citrus sinensis",
        "tipo": "perenne",
        "kc_inicio": 0.70,
        "kc_desarrollo": 0.65,
        "kc_medio": 0.70,
        "kc_final": 0.70,
        "profundidad_raiz_m": 1.2,
        "tolerancia_sequia": "baja",
        "riego_tipico": "goteo",
        "ciclo_dias": 365,
        "notas": "Perenne, NDVI estable todo el año. Kc relativamente constante."
    },
    "vinedo": {
        "nombre": "Viña (regadío)",
        "nombre_cientifico": "Vitis vinifera",
        "tipo": "caduco",
        "kc_inicio": 0.30,
        "kc_desarrollo": 0.50,
        "kc_medio": 0.70,
        "kc_final": 0.45,
        "profundidad_raiz_m": 1.5,
        "tolerancia_sequia": "media",
        "riego_tipico": "goteo",
        "ciclo_dias": 200,
        "notas": "Caduco. Brotación marzo, envero julio-agosto, vendimia sept-oct. NDVI muy variable."
    },
    "olivar": {
        "nombre": "Olivo",
        "nombre_cientifico": "Olea europaea",
        "tipo": "perenne",
        "kc_inicio": 0.65,
        "kc_desarrollo": 0.65,
        "kc_medio": 0.70,
        "kc_final": 0.70,
        "profundidad_raiz_m": 1.7,
        "tolerancia_sequia": "alta",
        "riego_tipico": "goteo_deficitario",
        "ciclo_dias": 365,
        "notas": "Muy tolerante a sequía. El riego deficitario controlado mejora calidad del aceite."
    },
    "cereal": {
        "nombre": "Trigo blando",
        "nombre_cientifico": "Triticum aestivum",
        "tipo": "anual",
        "kc_inicio": 0.30,
        "kc_desarrollo": 0.70,
        "kc_medio": 1.15,
        "kc_final": 0.25,
        "profundidad_raiz_m": 1.0,
        "tolerancia_sequia": "baja",
        "riego_tipico": "aspersion_o_secano",
        "ciclo_dias": 180,
        "notas": "Anual. Siembra noviembre, espigado abril-mayo, cosecha junio-julio. NDVI muy dramático."
    },
    "almendro": {
        "nombre": "Almendro",
        "nombre_cientifico": "Prunus dulcis",
        "tipo": "caduco",
        "kc_inicio": 0.40,
        "kc_desarrollo": 0.65,
        "kc_medio": 0.90,
        "kc_final": 0.65,
        "profundidad_raiz_m": 1.5,
        "tolerancia_sequia": "media",
        "riego_tipico": "goteo",
        "ciclo_dias": 240,
        "notas": "Caduco. Floración febrero (muy temprana), cosecha agosto-septiembre."
    }
}

# ============================================================
# VARIABLES A DESCARGAR DE OPEN-METEO
# ============================================================

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "rain_sum",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "wind_speed_10m_mean",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
]

# Variables horarias para suelo (se agregarán a diario)
HOURLY_SOIL_VARS = [
    "soil_moisture_0_to_7cm",
    "soil_temperature_0cm",
]


def descargar_historico(lat, lon, fecha_inicio, fecha_fin):
    """Descarga datos históricos de Open-Meteo (ERA5 reanalysis)."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": fecha_inicio,
        "end_date": fecha_fin,
        "daily": ",".join(DAILY_VARS),
        "timezone": "Europe/Madrid",
    }
    
    print(f"  Descargando histórico {fecha_inicio} → {fecha_fin}...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    if "daily" not in data:
        print(f"  ⚠ Sin datos diarios en respuesta")
        return pd.DataFrame()
    
    df = pd.DataFrame(data["daily"])
    df.rename(columns={"time": "fecha"}, inplace=True)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["fuente"] = "historico_era5"
    
    return df


def descargar_forecast(lat, lon):
    """Descarga forecast de Open-Meteo (16 días) + datos recientes."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_VARS),
        "hourly": ",".join(HOURLY_SOIL_VARS),
        "past_days": 30,
        "forecast_days": 16,
        "timezone": "Europe/Madrid",
    }
    
    print(f"  Descargando forecast (30 días pasados + 16 días futuro)...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    # Datos diarios
    df_daily = pd.DataFrame(data["daily"])
    df_daily.rename(columns={"time": "fecha"}, inplace=True)
    df_daily["fecha"] = pd.to_datetime(df_daily["fecha"])
    
    # Marcar qué es forecast y qué es observado
    hoy = pd.Timestamp.now().normalize()
    df_daily["fuente"] = df_daily["fecha"].apply(
        lambda d: "forecast" if d > hoy else "observado_modelo"
    )
    
    # Datos horarios de suelo → agregar a diario
    if "hourly" in data and data["hourly"]:
        df_hourly = pd.DataFrame(data["hourly"])
        df_hourly["time"] = pd.to_datetime(df_hourly["time"])
        df_hourly["fecha"] = df_hourly["time"].dt.date
        
        soil_daily = df_hourly.groupby("fecha").agg({
            "soil_moisture_0_to_7cm": "mean",
            "soil_temperature_0cm": "mean",
        }).reset_index()
        soil_daily["fecha"] = pd.to_datetime(soil_daily["fecha"])
        soil_daily.rename(columns={
            "soil_moisture_0_to_7cm": "humedad_suelo_m3m3",
            "soil_temperature_0cm": "temp_suelo_c",
        }, inplace=True)
        
        df_daily = df_daily.merge(soil_daily, on="fecha", how="left")
    
    return df_daily


def descargar_parcela(parcela_id, config):
    """Descarga todos los datos para una parcela."""
    lat = config["lat"]
    lon = config["lon"]
    
    print(f"\n{'='*60}")
    print(f"Parcela: {parcela_id}")
    print(f"  Ubicación: {config['municipio']}, {config['provincia']}")
    print(f"  Cultivo: {config['cultivo']}")
    print(f"  Coordenadas: {lat}, {lon}")
    print(f"{'='*60}")
    
    frames = []
    
    # 1. Histórico en bloques de 5 años (límite de la API)
    año_inicio = 2005
    año_actual = datetime.now().year
    
    for año in range(año_inicio, año_actual, 5):
        año_fin_bloque = min(año + 4, año_actual - 1)
        fecha_ini = f"{año}-01-01"
        fecha_fin = f"{año_fin_bloque}-12-31"
        
        try:
            df = descargar_historico(lat, lon, fecha_ini, fecha_fin)
            if not df.empty:
                frames.append(df)
                print(f"    ✓ {len(df)} días descargados")
        except Exception as e:
            print(f"    ✗ Error: {e}")
        
        time.sleep(1)  # Ser amable con la API
    
    # 2. Forecast + datos recientes
    try:
        df_forecast = descargar_forecast(lat, lon)
        if not df_forecast.empty:
            frames.append(df_forecast)
            print(f"    ✓ {len(df_forecast)} días (recientes + forecast)")
    except Exception as e:
        print(f"    ✗ Error forecast: {e}")
    
    if not frames:
        print("  ⚠ No se pudieron descargar datos para esta parcela")
        return pd.DataFrame()
    
    # Combinar y limpiar
    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["fecha"], keep="last")
    df_all = df_all.sort_values("fecha").reset_index(drop=True)
    
    # Añadir metadata
    df_all.insert(0, "parcela_id", parcela_id)
    df_all.insert(1, "cultivo", config["cultivo"])
    df_all.insert(2, "lat", lat)
    df_all.insert(3, "lon", lon)
    
    # Renombrar columnas a español
    rename_map = {
        "temperature_2m_max": "temp_max_c",
        "temperature_2m_min": "temp_min_c",
        "temperature_2m_mean": "temp_media_c",
        "precipitation_sum": "precipitacion_mm",
        "rain_sum": "lluvia_mm",
        "relative_humidity_2m_mean": "humedad_rel_pct",
        "wind_speed_10m_max": "viento_max_kmh",
        "wind_speed_10m_mean": "viento_medio_kmh",
        "shortwave_radiation_sum": "radiacion_solar_mjm2",
        "et0_fao_evapotranspiration": "et0_mm",
    }
    df_all.rename(columns=rename_map, inplace=True)
    
    # Calcular ETc (necesidad hídrica del cultivo)
    cultivo = config["cultivo"]
    if cultivo in CULTIVOS:
        kc = CULTIVOS[cultivo]["kc_medio"]
        df_all["kc_aplicado"] = kc
        df_all["etc_mm"] = (df_all["et0_mm"] * kc).round(2)
        df_all["deficit_hidrico_mm"] = (
            df_all["etc_mm"] - df_all["precipitacion_mm"]
        ).clip(lower=0).round(2)
    
    return df_all


def main():
    print("=" * 60)
    print("AgroMétrica — Pipeline de datos meteorológicos")
    print(f"Fecha de ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Parcelas a procesar: {len(PARCELAS)}")
    print("=" * 60)
    
    # 1. Descargar datos de todas las parcelas
    all_data = []
    for parcela_id, config in PARCELAS.items():
        df = descargar_parcela(parcela_id, config)
        if not df.empty:
            all_data.append(df)
    
    if not all_data:
        print("\n✗ No se descargaron datos. Verifica la conexión a internet.")
        return
    
    # 2. Consolidar dataset
    df_final = pd.concat(all_data, ignore_index=True)
    
    # 3. Guardar archivos
    print("\n" + "=" * 60)
    print("Guardando archivos...")
    print("=" * 60)
    
    # CSV principal
    csv_path = "datos_diarios_parcela.csv"
    df_final.to_csv(csv_path, index=False)
    print(f"  ✓ {csv_path} ({len(df_final)} filas, {len(df_final.columns)} columnas)")
    
    # JSON de cultivos
    cultivos_path = "cultivos_referencia.json"
    with open(cultivos_path, "w", encoding="utf-8") as f:
        json.dump(CULTIVOS, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {cultivos_path} ({len(CULTIVOS)} cultivos)")
    
    # JSON de parcelas
    parcelas_path = "parcelas.json"
    with open(parcelas_path, "w", encoding="utf-8") as f:
        json.dump(PARCELAS, f, ensure_ascii=False, indent=2, default=str)
    print(f"  ✓ {parcelas_path} ({len(PARCELAS)} parcelas)")
    
    # 4. Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DEL DATASET")
    print("=" * 60)
    print(f"  Periodo: {df_final['fecha'].min()} → {df_final['fecha'].max()}")
    print(f"  Parcelas: {df_final['parcela_id'].nunique()}")
    print(f"  Total filas: {len(df_final):,}")
    print(f"  Columnas: {list(df_final.columns)}")
    print(f"\n  Estadísticas clave para '{df_final['parcela_id'].iloc[0]}':")
    
    parcela_1 = df_final[df_final["parcela_id"] == df_final["parcela_id"].iloc[0]]
    print(f"    Temp media anual: {parcela_1['temp_media_c'].mean():.1f}°C")
    print(f"    Precipitación media diaria: {parcela_1['precipitacion_mm'].mean():.1f} mm")
    print(f"    ET₀ media diaria: {parcela_1['et0_mm'].mean():.1f} mm")
    if "etc_mm" in parcela_1.columns:
        print(f"    ETc media diaria (×Kc): {parcela_1['etc_mm'].mean():.1f} mm")
        print(f"    Déficit hídrico medio: {parcela_1['deficit_hidrico_mm'].mean():.1f} mm/día")
    
    dias_forecast = len(parcela_1[parcela_1["fuente"] == "forecast"])
    print(f"    Días de forecast disponibles: {dias_forecast}")
    
    print("\n  ✓ Dataset listo para entregar al equipo de IA")
    print("  → Subir al repositorio: /data/datos_diarios_parcela.csv")
    print("  →                       /data/cultivos_referencia.json")
    print("  →                       /data/parcelas.json")


if __name__ == "__main__":
    main()