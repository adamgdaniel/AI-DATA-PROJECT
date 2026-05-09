Invernaderos sigue la misma estructura que parcelas, adaptado a su lógica:

  Side input (cada 5 min en test, 10 min en prod):
  1. Reloj — PeriodicImpulse(300s)
  2. VentanaGlobal — GlobalWindows + AfterCount(1) + DISCARDING
  3. CargarSQL — CargarInvernaderosYPlantas lee invernaderos + plantas_invernadero y emite {invernaderos: {...}, plantas: {...}}

  Stream principal:
  1. LeerPubSub
  2. ParsearMensaje
  3. FiltrarInvOPlanta — descarta parcelas

  Rama Firestore (1 doc por mensaje, sin agregación):
  4a. PrepararFirestore — resuelve la ruta (invernadero o planta) usando el side input
  5a. EscribirFirestore — usuarios/{uid}/invernaderos/{inv_id} o .../plantas/{plant_id}, merge

  Rama BigQuery (1 fila por planta y ventana):
  4b. ExpandirAPlantas — fan-out con clave: lectura de invernadero → N pares (plant_id, lectura),
      uno por cada planta del invernadero; lectura de planta → 1 par (plant_id, lectura)
  5b. VentanaFija — FixedWindows(WINDOW_SECONDS) — 5 min en test, 10 min en prod
  6b. AgruparPorPlanta — GroupByKey
  7b. CombinarLecturas — media de las lecturas del mismo sensor (temperatura, humedad_ambiental, humedad_suelo);
      sin lectura → null; sin fallback meteorológico (espacios cerrados)
  8b. EscribirBigQuery → agri_data.lecturas_plantas (append)

  Notas:
  - Si en una ventana no llega ninguna lectura para una planta, no se emite fila a BQ
    (GroupByKey solo dispara para keys con datos), igual que dice CLAUDE.md.
  - Una lectura del invernadero (temp/hum_amb) se replica para todas sus plantas en la ventana,
    así cada planta tiene su propia fila desnormalizada.
