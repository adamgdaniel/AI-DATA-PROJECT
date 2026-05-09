  Side input (cada 5 min en test, 20 min en prod):
  1. Reloj — PeriodicImpulse(300s)
  2. VentanaGlobal — GlobalWindows + Repeatedly(AfterCount(1)) + DISCARDING
  3. CargarSQL — CargarParcelasYMeteo lee parcelas_usuario (logindb) y prevision_meteorologica (agrodb), construye el codigo_ine desde
  provincia+municipio, cruza por municipio y emite {parcela_id: {user_id, cultivo, variedad, temperatura, humedad_ambiental, precipitacion_mm,
  et0, radiacion_solar, estado_cielo}}

  Stream principal:
  1. LeerPubSub — con atributos
  2. ParsearMensaje — atributos + body → dict plano
  3. FiltrarParcelas — descarta invernaderos/plantas

  Rama Firestore (1 update por mensaje, sin agregación):
  4a. EnriquecerFirestore — baseline = meteo, sensor sobreescribe el campo correspondiente, marca fuente_temperatura
  5a. EscribirFirestore → usuarios/{uid}/parcelas/{pid} (merge)

  Rama BigQuery (1 fila por parcela y ventana):
  4b. ClavePorParcela — (parcel_id, lectura)
  5b. VentanaFija — FixedWindows(WINDOW_SECONDS) — 5 min en test, 20 min en prod
  6b. AgruparPorParcela — GroupByKey
  7b. CombinarLecturas — media de las lecturas del mismo sensor; si no hay lectura cae al valor de meteo;
      humedad_suelo queda null si no hay sensor; fuente_temperatura='sensor' solo si llegó alguna lectura de temperatura
  8b. EscribirBigQuery → agri_data.lecturas_parcelas (append)

  Notas:
  - humedad_suelo solo si llega del sensor (Open-Meteo no la da).
  - fecha_plantacion_aprox queda en None por ahora — la lógica del midpoint del rango de edad la añadimos cuando esté la columna lista.
  - estado_cielo viene de estado_cielo_desc (AEMET) si existe; si no, del mapping WMO.
  - Si en una ventana no llega ninguna lectura para una parcela, no se emite fila a BQ
    (GroupByKey solo dispara para keys con datos).
  - Solo abre conexiones SQL cuando dispara el reloj, así que no debería volver a tocarse el límite.
