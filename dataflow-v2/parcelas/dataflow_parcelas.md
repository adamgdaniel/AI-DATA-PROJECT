  Side input (cada 20 min):
  1. Reloj — PeriodicImpulse(1200s)
  2. VentanaGlobal — GlobalWindows + Repeatedly(AfterCount(1)) + DISCARDING
  3. CargarSQL — CargarParcelasYMeteo lee parcelas_usuario (logindb) y prevision_meteorologica (agrodb), construye el codigo_ine desde
  provincia+municipio, cruza por municipio y emite {parcela_id: {user_id, cultivo, variedad, temperatura, humedad_ambiental, precipitacion_mm,
  et0, radiacion_solar, estado_cielo}}

  Stream (por mensaje Pub/Sub):
  1. LeerPubSub — con atributos
  2. ParsearMensaje — atributos + body → dict plano
  3. FiltrarParcelas — descarta invernaderos/plantas
  4. Enriquecer — baseline = meteo, sensor sobreescribe el campo correspondiente, marca fuente_temperatura

  Sinks (en paralelo):
  - EscribirFirestore → usuarios/{uid}/parcelas/{pid} (merge)
  - EscribirBigQuery → agri_data.lecturas_parcelas (append)

  Notas:
  - humedad_suelo solo si llega del sensor (Open-Meteo no la da).
  - fecha_plantacion_aprox queda en None por ahora — la lógica del midpoint del rango de edad la añadimos cuando esté la columna lista.
  - estado_cielo viene de estado_cielo_desc (AEMET) si existe; si no, del mapping WMO.
  - Solo abre conexiones SQL una vez cada 20 min (cuando dispara el reloj), así que no debería volver a tocarse el límite.