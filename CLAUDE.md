# ⚠️ LEE ESTO ANTES DE EDITAR ESTE ARCHIVO.

Este archivo lo lee Claude automáticamente en cada sesión. Lo que escribas aquí afecta a cómo Claude trabaja en todo el proyecto, para todos los miembros del equipo que usen esta IA. 

**Antes de hacer cambios, habla con tus compañeros.**
**Si solo afecta a tu parte (Data o IA), edita solo tu sección.**

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
└── api/                      ← 👥 EQUIPO DATA
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

---

# 👥 EQUIPO IA

_Escribe aquí las instrucciones específicas para que Claude trabaje en la parte del modelo de IA._
-
-Rol y Colaboración: Desarrollo exclusivo del motor predictivo en Python puro. La infraestructura (Terraform, bases de datos) la gestiona Data. Toda comunicación entre equipos será mediante APIs y esquemas JSON estrictos
-Visión Computacional (Satélite): Procesamiento de bandas como tensores bidimensionales. Es obligatorio usar NumPy y vectorización masiva. Prohibido usar bucles (for/while) para iterar píxeles
-Forecasting (Clima): Uso de Pandas y Prophet para predecir series temporales. Salida obligatoria en escenarios probabilísticos (P25 pesimista, P50 neutro, P75 optimista)
-Motor Agronómico: El déficit hídrico se calcula integrando IA y física mediante la ecuación FAO-56 (Penman-Monteith) ajustada por el Coeficiente de Cultivo, no con Redes Neuronales de caja negra.
Despliegue (MLOps): Código modular y seguro (controlando errores como la división por cero). Todo debe empaquetarse en contenedores Docker stateless listos para Cloud Run
