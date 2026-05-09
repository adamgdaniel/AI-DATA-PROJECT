Invernaderos sigue la misma estructura que parcelas, adaptado a su lógica:

  Side input (cada 5 min):
  1. Reloj — PeriodicImpulse(300s)
  2. VentanaGlobal — GlobalWindows + AfterCount(1) + DISCARDING
  3. CargarSQL — CargarInvernaderosYPlantas lee invernaderos + plantas_invernadero y emite {invernaderos: {...}, plantas: {...}}

  Stream:
  1. LeerPubSub
  2. ParsearMensaje
  3. FiltrarInvOPlanta — descarta parcelas

  Sink Firestore (1 doc por mensaje):
  - PrepararFirestore — resuelve la ruta (invernadero o planta) usando el side input
  - EscribirFirestore — usuarios/{uid}/invernaderos/{inv_id} o .../plantas/{plant_id}, merge

  Sink BigQuery (fan-out):
  - PrepararBQ — si llega lectura de invernadero (temperatura/humedad_ambiental) emite N filas (una por cada planta en ese invernadero); si llega
   lectura de planta (humedad_suelo) emite 1 fila para esa planta
  - EscribirBigQuery — append a agri_data.lecturas_plantas