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
-
-