# ⚠️ LEE ESTO ANTES DE EDITAR ESTE ARCHIVO.

Este archivo lo lee Claude automáticamente en cada sesión. Lo que escribas aquí afecta a cómo Claude trabaja en todo el proyecto, para todos los miembros del equipo que usen esta IA. 

**Antes de hacer cambios, habla con tus compañeros.**
**Si solo afecta a tu parte (Data o IA), edita solo tu sección.**

---

# Concepto del proyecto
Vamos a desarrollar un proyecto para el master de Data/IA. Se trata de una herramienta agéntica centrada en el seguimiendo y cuidado de plantaciones agrícolas. El usuario podrá logearse, interactuar con un front end desplegado en un cloud run, y la herramienta se conectará a varias APIs públicas para obtener información, y usará contexto a nivel de usuario y memoria. 
La idea es que al entrar al front end y logearse, el usuario verá un mapa (creado idealmente con React) con las parcelas agrícolas que vamos a delimitar usando una capa a partir de la API de SIGPAC, que nos proporciona los polígonos y coordenadas de las parcelas. El usuario puede clickar sobre una parcela y "reclamarla" (asignarla como suya). Al hacer esto aparecerá un pequeño formulario donde el usuario (agricultor) tendrá que indicar tipo y varidead de cosecha (naranjas navelinas, manzanos golden, ...) y el año aproximado de siembra, en caso de ser cultivo de arbol. Eso guardará en una base de datos está relación e información. La herramienta hará el seguimiento de los indicadores de la parcela (lluvia, temperatura, humedad, etc) tanto de los últimos 30 dias como de las previsiones, información obtenida a través de la API de AEMET (o servicio similar). Esta la usará el modelo de IA (entrenado con cuidados necesarios de múltiples cultivos) para hacer las sugerencias e indicaciones de cuando haria falta regar un campo, abonarlo, etc. El agricultor también puede marcar estas acciones como hechas a través de la UI para cada campo, para que el modelo sepa que aunque hace x dias que no llueve, el agricultor regó hace 3 dias, por ejemplo, y mostrar en la UI las recomendaciones para cada parcela. 
Todos los recursos que crees deben ser lo más limitados posibles para que la aplicación funcione con pocos usuarios, pero reudciendo el coste de recursos al máximo.

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
