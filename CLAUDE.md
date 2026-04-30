# ⚠️ LEE ESTO ANTES DE EDITAR ESTE ARCHIVO.

Este archivo lo lee Claude automáticamente en cada sesión. Lo que escribas aquí afecta a cómo Claude trabaja en todo el proyecto, para todos los miembros del equipo que usen esta IA. 

**Antes de hacer cambios, habla con tus compañeros.**
**Si solo afecta a tu parte (Data o IA), edita solo tu sección.**

---

# Concepto del proyecto
Vamos a desarrollar un proyecto para el master de Data/IA. Se trata de una herramienta agéntica centrada en el seguimiendo y cuidado de plantaciones agrícolas. El usuario podrá logearse, interactuar con un front end desplegado en un cloud run, y la herramienta se conectará a varias APIs públicas para obtener información, y usará contexto a nivel de usuario y memoria. 
La idea es que al entrar al front end y logearse, el usuario verá un mapa (creado idealmente con React) con las parcelas agrícolas que vamos a delimitar usando una capa a partir de la API de SIGPAC, que nos proporciona los polígonos y coordenadas de las parcelas. El usuario puede clickar sobre una parcela y "reclamarla" (asignarla como suya). Al hacer esto aparecerá un pequeño formulario donde el usuario (agricultor) tendrá que indicar tipo y varidead de cosecha (naranjas navelinas, manzanos golden, ...) y el año aproximado de siembra, en caso de ser cultivo de arbol. Eso guardará en una base de datos está relación e información. La herramienta hará el seguimiento de los indicadores de la parcela (lluvia, temperatura, humedad, etc) tanto de los últimos 30 dias como de las previsiones. La fuente principal de datos meteorológicos es **Open-Meteo** (coordenadas, 16 días de previsión, precipitación en mm, ET₀, radiación solar). **AEMET** se usa como fuente secundaria únicamente para obtener el estado del cielo en español y la humedad relativa diaria (días 1-7). Esta la usará el modelo de IA (entrenado con cuidados necesarios de múltiples cultivos) para hacer las sugerencias e indicaciones de cuando haria falta regar un campo, abonarlo, etc. El agricultor también puede marcar estas acciones como hechas a través de la UI para cada campo, para que el modelo sepa que aunque hace x dias que no llueve, el agricultor regó hace 3 dias, por ejemplo, y mostrar en la UI las recomendaciones para cada parcela. 
Adicionalmente, la plataforma integrará sensores IoT opcionales: el agricultor podrá colocar dispositivos físicos en su parcela (sensores de humedad del suelo, temperatura, etc.) y sus lecturas se incorporarán como datos de entrada al modelo, complementando los datos meteorológicos para mejorar las sugerencias.
Todos los recursos que crees deben ser lo más limitados posibles para que la aplicación funcione con pocos usuarios, pero reudciendo el coste de recursos al máximo.

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
Sensor Zigbee
     ↓
Home Assistant (Raspberry Pi, red local)
     ↓  [automation: on state change → HTTP POST]
Cloud Run /ingest  ←──── Cloud SQL (lookup sensor_id → parcel_id + metadatos)
     ↓
Pub/Sub (lecturas crudas)
     ↓
Dataflow (job batch, se ejecuta cada hora)
     ↓
BigQuery (1 registro por sensor por hora)
     ↓
Model serving / API
```

**Decisión clave — push en lugar de pull:** Home Assistant envía los datos mediante una automation que hace HTTP POST al endpoint de Cloud Run cada vez que el sensor registra un cambio. Cloud Run no sondea a Home Assistant. Esto evita exponer la Raspberry Pi a internet de forma permanente (solo necesita salida, no entrada).

## Justificación del uso de Dataflow

El sensor envía lecturas cada pocos minutos. Usar Dataflow en modo batch horario está justificado por tres razones técnicas reales:

1. **Reducción de ruido**: los sensores Zigbee pueden emitir lecturas ruidosas o duplicadas. Agregar en ventanas de 1 hora produce valores estables para el modelo.
2. **Consistencia temporal con Open-Meteo**: los datos meteorológicos de Open-Meteo tienen resolución horaria. Que los datos del sensor también sean horarios permite un join limpio y coherente en el modelo de IA.
3. **Separación de responsabilidades y resiliencia**: Pub/Sub absorbe las lecturas crudas sin pérdida aunque Dataflow no esté procesando en ese momento. El pipeline Apache Beam gestiona natively el windowing, mensajes desordenados (late data) y es testeable unitariamente. El código escala a múltiples sensores sin cambios.

Lo que produce Dataflow por cada ventana de 1 hora y sensor: media, mínimo y máximo de cada métrica, más el enriquecimiento con `parcel_id` y metadatos de cultivo obtenidos de Cloud SQL.

## Bases de datos

| Qué | Dónde | Por qué |
|---|---|---|
| Registro de sensores (sensor_id, coordenadas, parcel_id) | Cloud SQL (PostgreSQL) | Datos relacionales, pocas escrituras, ya usado en el proyecto |
| Lecturas agregadas por hora | BigQuery | Barato para series temporales, consumo directo por el modelo de IA |

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
-Visión Computacional (Satélite): Procesamiento de bandas como tensores bidimensionales. Es obligatorio usar NumPy y vectorización masiva. Prohibido usar bucles (for/while) para iterar píxeles
-Forecasting (Clima): Uso de Pandas y Prophet para predecir series temporales. Salida obligatoria en escenarios probabilísticos (P25 pesimista, P50 neutro, P75 optimista)
-Motor Agronómico: El déficit hídrico se calcula integrando IA y física mediante la ecuación FAO-56 (Penman-Monteith) ajustada por el Coeficiente de Cultivo, no con Redes Neuronales de caja negra.
Despliegue (MLOps): Código modular y seguro (controlando errores como la división por cero). Todo debe empaquetarse en contenedores Docker stateless listos para Cloud Run
