# ⚠️ LEE ESTO ANTES DE EDITAR ESTE ARCHIVO.

Este archivo lo lee Claude automáticamente en cada sesión. Lo que escribas aquí afecta a cómo Claude trabaja en todo el proyecto, para todos los miembros del equipo que usen esta IA. 

**Antes de hacer cambios, habla con tus compañeros.**
**Si solo afecta a tu parte (Data o IA), edita solo tu sección.**

---

# Concepto del proyecto
Vamos a desarrollar un proyecto para el master de Data/IA. Se trata de una herramienta agéntica centrada en el seguimiendo y cuidado de plantaciones agrícolas. El usuario podrá logearse, interactuar con un front end desplegado en un cloud run, y la herramienta se conectará a varias APIs públicas para obtener información, y usará contexto a nivel de usuario y memoria. 
La idea es que al entrar al front end y logearse, el usuario verá un mapa (creado idealmente con React) con las parcelas agrícolas que vamos a delimitar usando una capa a partir de la API de SIGPAC, que nos proporciona los polígonos y coordenadas de las parcelas. El usuario puede clickar sobre una parcela y "reclamarla" (asignarla como suya). Al hacer esto aparecerá un pequeño formulario donde el usuario (agricultor) tendrá que indicar tipo y varidead de cosecha (naranjas navelinas, manzanos golden, ...) y el año aproximado de siembra, en caso de ser cultivo de arbol. Eso guardará en una base de datos está relación e información. La herramienta hará el seguimiento de los indicadores de la parcela (lluvia, temperatura, humedad, etc) tanto de los últimos 30 dias como de las previsiones. La fuente de datos meteorológicos es **Open-Meteo** (coordenadas, 15 días de previsión horaria, precipitación en mm, ET₀, radiación solar, estado del cielo vía código WMO traducido al español). Esta la usará el modelo de IA (entrenado con cuidados necesarios de múltiples cultivos) para hacer las sugerencias e indicaciones de cuando haria falta regar un campo, abonarlo, etc. El agricultor también puede marcar estas acciones como hechas a través de la UI para cada campo, para que el modelo sepa que aunque hace x dias que no llueve, el agricultor regó hace 3 dias, por ejemplo, y mostrar en la UI las recomendaciones para cada parcela. 
Adicionalmente, la plataforma integrará sensores IoT opcionales: el agricultor podrá colocar dispositivos físicos en su parcela (sensores de humedad del suelo, temperatura, etc.) y sus lecturas se incorporarán como datos de entrada al modelo, complementando los datos meteorológicos para mejorar las sugerencias.
Todos los recursos que crees deben ser lo más limitados posibles para que la aplicación funcione con pocos usuarios, pero reudciendo el coste de recursos al máximo.

Claude, bajo ninguna circunstancia firmes los commits con un coauthored by claude porque GitHub lo lee como un participante del grupo

# Cultivos objetivos:
## Parcelas (exterior-regadio)
- Maiz (variedad híbrida de ciclo largo/grano)
- Naranjo (Navelate, Navelina, Valencia late)
- Mandarino (Clemenules, Híbrido tardío)
- Melocotonero (Amarillo/Pavía, Nectarina, Paraguayo)
- Limonero (Primofiori)

## Invernadero
- Tomate (Rama/LongLife, Pera, Cherry)
- Pimiento (California, Lamuyo)
- Pepino (Holandés)
- Calabacín (Verde oscuro)

# Integración de dispositivos IoT (a través de Home Assistant)

## Contexto
El tutor del máster nos ha recomendado centrar el proyecto en la integración de sensores IoT. Disponemos de un sensor de humedad del suelo con conectividad Zigbee, conectado a una Raspberry Pi con Home Assistant OS en red local. El sensor devuelve tres métricas: humedad del suelo, humedad ambiental y temperatura.

## Concepto de frontend
Pages:
# Login
    - Proceso de login de usuarios
  
# Crear usuario
     - Permite crear un usuario al preguntar username, password y correo electronico
# Main page
     - Una vez el usuario se logea, puede ver esta interfaz con un mapa donde reclamar o ver sus parcelas
     - Puede clickar en "Conectar con Home Assistant" para crear una conexión con este recurso. Una vez tiene una conexion creada, puede empezar a añadir dispositivos a cada parcela
# GreenHose page 
     - Esta página es una interfaz donde el usuario podrá ver y customizar sus invernaderos
     - La interfaz está inspirada en un juego tipo HayDay o Habbo. El usuario verá un espacio rectangular, y debajo tiene una linea con iconos que representan los cultivos objetivos de invernadero (tomates, pepinos, pimientos y fresas). Al seleccionar cada tipo. El usuario puede arrastrar el icono y colocarlo en la parte que quiera de la cuadrícula que representa el invernadero. La cuadrícula se verá en 3D estilo pixel art, desde un ángulo de 45 grados. Cada usuario puede crear varios invernaderos, y podrá alternar entre ellos desde un selector situado arriba a la izquierda. Cada "tomate" que se coloca tendrá el icono de una plantera de tomates, ocupando un espacio de 2x1 cuadrículas. AL seleccionar la plantera, El usuario puede ver el cultivo, y si tiene configurado una conexión con Home asistant, podrá añadir dispositivos conectados. Si una plantera tiene dispositivos conectados, en la interfaz general del invernadero, se verá una cajita encima indicando las lecturas (temperatura, humedad ambiental, humedad del suelo) de los dispositivos.

## Arquitectura acordada

```
[Open-Meteo API + AEMET API]
      ↑
[AEMET Cloud Run Job — cada hora]
  1) sync municipios: lee parcelas_usuario (logindb) y upserta los municipios
     únicos en municipios_monitorizados (agrodb) con activo=TRUE, marcando
     como activo=FALSE los municipios que ya no tienen parcelas que los usen.
  2) ingesta meteo: para cada municipio activo
     - Open-Meteo: tmax, tmin, precipitacion_mm, et0, radiacion_solar,
       weather_code, humedad_max, humedad_min (FUENTE PRINCIPAL)
     - AEMET: estado_cielo_desc (best-effort; tolera fallos 429/timeout)
  Escribe: prevision_meteorologica (Cloud SQL, 1 fila/municipio/día, 16 días)

[Home Assistant — Raspberry Pi, red local]
      ↑  polling cada 10 min
[IoT Cloud Run Job — cada 10 min]
  Lee:    ha_connections (Cloud SQL) → usuarios con HA configurado
          sensor_entity_ids de parcelas_usuario + invernaderos + plantas_invernadero
  Llama:  GET {ha_url}/api/states/{sensor_entity_id}  por cada sensor linkado
  Publica: Pub/Sub topic "sensor-readings"
              ├── suscripción sus_parcelas      → Dataflow Parcelas
              └── suscripción sus_invernaderos  → Dataflow Invernaderos

[Dataflow Parcelas — cada 10 min]
  Lee:    parcelas_usuario (Cloud SQL) — info de parcelas
          prevision_meteorologica (Cloud SQL) — última fila <= hoy por municipio
          sus_parcelas (Pub/Sub) — lecturas sensor últimos 10 min
  Lógica: meteo es el baseline (siempre presente gracias a Open-Meteo);
          si la parcela tiene sensor, sobreescribe
          temperatura / humedad_ambiental / humedad_suelo según tipo de sensor.
          Merge con CoGroupByKey: meteo_stream + sensor_stream en FixedWindows(10min).
  Escribe: BigQuery lecturas_parcelas
           Firestore usuarios/{uid}/parcelas/{parcela_id}

[Dataflow Invernaderos — cada 10 min]
  Lee:    invernaderos + plantas_invernadero (Cloud SQL) — info estructural
          sus_invernaderos (Pub/Sub) — lecturas sensor últimos 10 min
  Lógica: solo datos de sensor (invernaderos son espacios cerrados, sin meteo)
  Escribe: BigQuery lecturas_plantas
           Firestore usuarios/{uid}/invernaderos/{inv_id} y .../plantas/{plant_id}
```

**Decisión clave — pull en lugar de push:** El IoT Cloud Run sondea Home Assistant cada 10 minutos. HA no necesita exponer ningún endpoint ni tener automation. La Raspberry Pi solo necesita salida a internet, no entrada. El Cloud Run consulta `ha_connections` para saber a qué instancias llamar y qué `sensor_entity_id` pedir en cada una.

**Referencia de implementación:** `dataflow/sample_dataflow_from_another_project.py`. Best practices obligatorias extraídas de ese modelo:
- **Side inputs para Cloud SQL:** usar `PeriodicImpulse + GlobalWindows + AsSingleton` para cargar datos de referencia (parcelas, meteo) una sola vez y refrescarlos periódicamente. Nunca consultar la DB dentro de un `process()` que se ejecuta por cada mensaje.
- **`AccumulationMode.DISCARDING`** en los side inputs para no acumular versiones antiguas en memoria.
- **`default_value={}`** en `AsSingleton` para evitar errores si el side input aún no ha disparado al arrancar.
- **Ciclo de vida de DoFns:** abrir conexiones (Cloud SQL, Firestore) en `setup()`, lógica en `process()`, cerrar en `teardown()`. Nunca en `__init__()`.
- **Firestore:** usar `set(element, merge=True)` para no sobreescribir campos que escribe otro servicio (p.ej. `ultimo_riego` lo escribe el frontend, no Dataflow).
- **`FixedWindows`** para el stream de Pub/Sub; usar `beam.DoFn.WindowParam` para obtener el timestamp de inicio de ventana y usarlo como `timestamp` en la fila de BQ.

**Por qué dos Dataflow separados:** Las parcelas dependen de datos meteorológicos (Open-Meteo vía Cloud SQL) además de los sensores; los invernaderos dependen solo de sensores. Aunque ambos corren a 10 min, las dependencias y los joins son distintos, así que mantenerlos separados simplifica el pipeline y evita que un fallo de meteo afecte a invernaderos.

**Por qué Dataflow y no Cloud Run directo para el join:** Dataflow (Apache Beam) gestiona nativamente el windowing de Pub/Sub, mensajes desordenados y la escritura atómica a BQ + Firestore. Para el equipo de IA es crítico recibir en BigQuery filas limpias con toda la info ya cruzada (parcela + meteo + sensor). Cloud Run no está diseñado para este tipo de join con estado.

## Tablas Cloud SQL relevantes para el pipeline

| Tabla | Contenido clave |
|---|---|
| `users` | `id`, `username`, `password_hash`, `email` — cuentas de usuario |
| `parcelas_usuario` | `id`, `usuario_id`, `parcela_id`, `provincia`, `municipio`, `poligono`, `parcela`, `recinto`, `cultivo`, `variedad`, `edad_cultivo`, `superficie`, `lat`, `lng`, `geometria`, `zonas`, `grid` |
| `invernaderos` | `id`, `usuario_id`, `nombre`, `temperatura_entity_id`, `hum_amb_entity_id` — entity IDs de HA para temperatura y humedad ambiental del invernadero |
| `plantas_invernadero` | `id`, `invernadero_id`, `tipo`, `variedad`, `grid_col`, `grid_row`, `soil_entity_id` — entity ID de HA para humedad de suelo de la planta |
| `ha_connections` | `id`, `user_id`, `ha_url`, `ha_token` (cifrados con Fernet), `display_name`, `last_seen_at` |
| `sensors` | `sensor_id` (entity ID de HA), `connection_id`, `user_id`, `location_id`, `location_type` (`'parcela'`/`'invernadero'`/`'planta'`), `sensor_type` (`'temperature'`/`'ambient_humidity'`/`'soil_moisture'`), `active` — **registro central de todos los sensores vinculados** |

**Cómo se puebla `sensors`:**
- Sensores de parcela: el usuario los registra desde la página de detalle de parcela → IoT API `POST /ha/sensores`
- Sensores de invernadero/planta: el usuario los asigna desde la página de invernaderos → data-api `PUT /invernaderos/<id>/sensor` y `PUT /plantas/<id>/sensor`, que escriben en `sensors` con `ON CONFLICT DO NOTHING`

**Cómo lee el IoT puller:** consulta `sensors JOIN ha_connections` filtrando `location_type = 'parcela'`. Para invernaderos/plantas el Dataflow lee las columnas `temperatura_entity_id`, `hum_amb_entity_id`, `soil_entity_id` directamente de sus tablas.

**Nota sobre `estado_cielo`:** Por defecto viene de AEMET (`estado_cielo_desc`). Si AEMET falla (rate limit, timeout, etc.), el Dataflow hace fallback al `weather_code` (código WMO estándar de Open-Meteo) traducido a español con una tabla de mapeo estática. Así el campo nunca queda vacío.

# ARQUITECTURA

## Cloud Run
Donde viven todos los servicios del proyecto. Cada servicio es un contenedor independiente que arranca bajo demanda.

## Cloud SQL (PostgreSQL)
Guarda los datos de usuario y configuración: cuentas, parcelas reclamadas, invernaderos, sensores registrados. **Entra:** escrituras de los servicios web cuando el usuario hace acciones. **Sale:** los servicios lo consultan para saber qué parcelas/sensores pertenecen a quién.

## BigQuery
Histórico completo de lecturas métricas. **Sale:** el modelo de IA lo consulta para generar recomendaciones agronómicas. Tres tablas:

### `lecturas_parcelas` — 1 fila por parcela por hora
Particionada por `DATE(timestamp)`, clusterizada por `parcel_id`.
- `user_id`, `parcel_id` — STRING
- `timestamp` — DATETIME (hora UTC)
- `temperatura`, `humedad_ambiental` — FLOAT (sensor si existe, sino Open-Meteo)
- `humedad_suelo` — FLOAT, nullable (solo si hay sensor IoT)
- `precipitacion_mm` — FLOAT (Open-Meteo, horaria; el modelo agrega)
- `et0`, `radiacion_solar` — FLOAT (Open-Meteo)
- `fuente_temperatura` — STRING (`'sensor'` / `'openmeteo'`)
- `tipo_cultivo`, `variedad` — STRING
- `fecha_plantacion_aprox` — DATE (para árboles: midpoint del rango de edad indicado por el agricultor en intervalos de 5 años, convertido a fecha restando años a la fecha de registro; para maíz: fecha exacta de siembra)

### `lecturas_plantas` — 1 fila por planta por hora
Particionada por `DATE(timestamp)`, clusterizada por `plant_id`.
- `user_id`, `greenhouse_id`, `plant_id` — STRING
- `timestamp` — DATETIME (hora UTC)
- `temperatura`, `humedad_ambiental` — FLOAT (del invernadero, desnormalizado)
- `humedad_suelo` — FLOAT, nullable (solo si hay sensor IoT en esa planta)
- `tipo_cultivo`, `variedad` — STRING
- `fecha_plantacion` — DATE (fecha exacta de siembra; el agricultor indica la semana)

### `eventos_agricolas` — 1 fila por evento registrado
Escrita por el frontend/API cuando el agricultor registra una acción. No es horaria.
- `user_id`, `entity_type` (`'parcela'`/`'planta'`), `entity_id` — STRING
- `timestamp` — DATETIME
- `tipo_evento` — STRING (`'riego'`/`'poda'`/`'abonado'`)
- `valor` — STRING, nullable (tipo de abono si aplica)

El modelo obtiene la última acción por entidad con `MAX(timestamp)` agrupado.

## Pub/Sub
Buffer de lecturas de sensores IoT. Un único topic `sensor-readings` con dos suscripciones independientes:
- `sus_parcelas` → consumida por Dataflow Parcelas
- `sus_invernaderos` → consumida por Dataflow Invernaderos

Cada mensaje publicado por el IoT Cloud Run tiene esta estructura:

```json
// Atributos del mensaje (para filtrado en Dataflow)
{
  "entity_type": "parcela" | "planta",
  "entity_id":   "12-345-1-2-3",
  "usuario_id":  "42",
  "sensor_tipo": "temperatura" | "humedad_ambiental" | "humedad_suelo"
}

// Body (JSON serializado)
{
  "valor": 23.5,
  "unidad": "°C",
  "sensor_entity_id": "sensor.zigbee_temp_01",
  "timestamp_lectura": "2025-05-08T15:22:00Z"
}
```

Cada Dataflow filtra los mensajes por `entity_type` en los atributos para procesar solo los que le corresponden.

## Dataflow (Apache Beam)

### Dataflow Parcelas — cadencia 10 min
**Fuentes:**
1. `parcelas_usuario` (Cloud SQL `logindb`) — metadatos de parcela (cultivo, variedad, provincia/municipio, usuario_id)
2. `prevision_meteorologica` (Cloud SQL `agrodb`) — última fila <= hoy por municipio:
   `SELECT DISTINCT ON (codigo_ine) ... WHERE fecha_prevision <= CURRENT_DATE ORDER BY codigo_ine, fecha_prevision DESC`
3. `sus_parcelas` (Pub/Sub) — lecturas de sensores de los últimos 10 min

**Arquitectura del merge (CoGroupByKey):**
- `meteo_stream`: `PeriodicImpulse(600s)` → carga SQL → explota a `(parcel_id, info)` → `FixedWindows(10min)`
- `sensor_stream`: Pub/Sub → parse → filter `entity_type=parcela` → `(entity_id, msg)` → `FixedWindows(10min)`
- `CoGroupByKey` empareja ambos streams en la misma ventana, por parcel_id
- Una sola escritura por parcela por ventana, tanto a BQ como a Firestore

**Lógica de merge campo a campo:**
- Baseline = datos meteo del municipio (Open-Meteo, vía SQL)
- Si hay lecturas de sensor en la ventana, sobreescribe `temperatura`/`humedad_ambiental`/`humedad_suelo` según `sensor_tipo`
- `humedad_suelo` solo existe si llega del sensor (Open-Meteo no la proporciona)
- `fuente_temperatura` = `'sensor'` si hay lectura de sensor de temperatura, `'openmeteo'` en caso contrario
- `timestamp` de BQ = inicio de ventana (`window.start.to_utc_datetime()`)

**Salida:** BigQuery `lecturas_parcelas` + Firestore `usuarios/{uid}/parcelas/{parcela_id}` (con `merge=True`, omitiendo campos `None`)

### Dataflow Invernaderos — cadencia 10 min
**Fuentes:**
1. `invernaderos` + `plantas_invernadero` (Cloud SQL) — estructura y metadatos
2. `sus_invernaderos` (Pub/Sub) — lecturas de sensores de los últimos 10 min

**Lógica:** Solo datos de sensor. Sin fallback meteorológico (espacios cerrados). Si no hay lectura de sensor en la ventana, no escribe fila en BQ para esa planta.

**Salida:** BigQuery `lecturas_plantas` + Firestore `usuarios/{uid}/invernaderos/{inv_id}` y `.../plantas/{plant_id}`

## Firestore
Estado actual para el frontend. No es un histórico — cada escritura sobreescribe. El histórico vive en BigQuery.

**Árbol de colecciones:**
```
usuarios/{uid}/
  parcelas/{parcela_id}                ← escribe: Dataflow Parcelas + Frontend/API
    temperatura, humedad_ambiental     (Open-Meteo o sensor)
    humedad_suelo                      (solo si hay sensor)
    precipitacion_mm, et0, radiacion_solar, estado_cielo
    forecast: [{fecha, temp_max, temp_min, precipitacion_mm, et0, estado_cielo}×15]
    ultimo_riego, ultima_poda, ultimo_abonado, tipo_abono   (escribe: Frontend/API)
    fuente_temperatura
    updated_at

  invernaderos/{inv_id}                ← escribe: Dataflow Invernaderos
    temperatura, humedad_ambiental
    updated_at

    plantas/{plant_id}                 ← escribe: Dataflow Invernaderos + Frontend/API
      humedad_suelo                    (solo si hay sensor)
      ultimo_riego, ultima_poda, ultimo_abonado, tipo_abono
      updated_at
```

**Nota:** Anteriormente existía una colección `municipios/{municipio_id}` escrita por un servicio de meteo. Ese servicio ya no existe — el AEMET job escribe solo a Cloud SQL y el Dataflow lee de ahí.

**Reglas:**
- Campos sin valor se omiten (no se guardan como `null`)
- El frontend se suscribe vía SDK Firestore (WebSocket) — recibe cambios en tiempo real sin polling
- `ultimo_riego` etc. los escribe exclusivamente el Frontend/API cuando el agricultor registra una acción manual

## Artifact Registry
Repositorios Docker, uno por servicio: `login-repo` (auth API), `frontend-repo` (frontend, data-api), `iot-repo` (IoT Cloud Run Job), `meteo-repo` (Meteo Cloud Run Job), `dataflow-parcelas-repo`, `dataflow-invernaderos-repo`, `model-serving-repo` (modelo IA).

## Secret Manager
Guarda credenciales y claves sensibles (DB password, API keys, secret key de sesión). **Entra:** se crean manualmente o via Terraform. **Sale:** Cloud Run los inyecta como variables de entorno al arrancar los contenedores.

## Cloud Build
CI/CD del proyecto. **Entra:** un push a `main` en GitHub. **Sale:** construye la imagen Docker, la sube a Artifact Registry y redespliegua el servicio en Cloud Run. Cada carpeta de servicio tiene su propio `cloudbuild.yaml`.

---

# Contexto del Proyecto

## Stack
- **Infra**: GCP + Terraform
- **Servicios**: Cloud Run + Docker + Python
- **CI/CD**: Cloud Build — cada push a `main` que toque una carpeta de servicio lanza automáticamente el build y redeploy de ese servicio en Cloud Run
- **Git**: rama principal `main`. Cada uno trabaja en su propia rama y hace PR a `main`. No hay rama staging ni develop.

## Estructura del proyecto
```
DP3/
├── arquitectura/             ← diagramas, no hay código aquí
├── terraform/                ← 👥 EQUIPO DATA
├── data-ingestion/           ← 👥 EQUIPO DATA
├── data-processing/          ← 👥 EQUIPO DATA
├── model-training/           ← 👥 EQUIPO IA 
├── model-serving/            ← 👥 EQUIPO IA
├── api/                      ← 👥 EQUIPO DATA
└── frontend/                 ← 👥 EQUIPO DATA/IA
```

## Regla básica
- Si eres del **Equipo Data**: trabaja solo en `terraform/`, `data-ingestion/`, `data-processing/`, `api/`
- Si eres del **Equipo IA**: trabaja solo en `model-training/`, `model-serving/`, 
- Si necesitas tocar algo fuera de tu zona, consúltalo primero con el otro equipo

## Cómo funciona el CI/CD
Cada carpeta de servicio tiene su propio `Dockerfile` y `cloudbuild.yaml`. Cuando se hace push a `main` tocando esa carpeta, Cloud Build automáticamente:
1. Construye la imagen Docker
2. La sube a Google Container Registry
3. Redespliegua el servicio en Cloud Run


---

# 👥 EQUIPO DATA

_Escribe aquí las instrucciones específicas para que Claude trabaje en la parte de Data e infraestructura._

- El despliegue completo debe ir con Terraform
- El proyecto se guarda en un repo público de Git, todas las claves e información sensible debe ir con variables de entorno y/o secretos de GCP.
- Todo debe ejecutarse con CI/CD
- Todas las conexiones externas deben ir con APIs. 
- El equipo está formado por perfiles junior, limita la complejidad de los scripts y herramientas usadas.
- Si en algún prompt las instrucciones no estan lo suficientemente claras, pregunta al usuario antes de hacer freestyle.
- El proyecto debe funcionar cuando cambiemos a otra cuenta/proyecto de GCP, por lo que la infraestructira completa debe definirse con terraform, inclusive los permisos de Service accounts.

---

# 👥 EQUIPO IA

_Escribe aquí las instrucciones específicas para que Claude trabaje en la parte del modelo de IA._
-
-Rol y Colaboración: Desarrollo exclusivo del motor predictivo en Python puro. La infraestructura (Terraform, bases de datos) la gestiona Data. Toda comunicación entre equipos será mediante APIs y esquemas JSON estrictos
-Forecasting (Clima): Uso de Pandas y Prophet para predecir series temporales. Salida obligatoria en escenarios probabilísticos (P25 pesimista, P50 neutro, P75 optimista)
-Motor Agronómico: El déficit hídrico se calcula integrando IA y física mediante la ecuación FAO-56 (Penman-Monteith) ajustada por el Coeficiente de Cultivo, no con Redes Neuronales de caja negra.
Despliegue (MLOps): Código modular y seguro (controlando errores como la división por cero). Todo debe empaquetarse en contenedores Docker stateless listos para Cloud Run 
