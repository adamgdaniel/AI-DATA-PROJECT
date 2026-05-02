# --- Dataflow API ---
resource "google_project_service" "dataflow" {
  service            = "dataflow.googleapis.com"
  disable_on_destroy = false
}

# --- GCS Bucket para Dataflow (temp y staging) ---
resource "google_storage_bucket" "dataflow_temp" {
  name                        = "${var.project_id}-dataflow"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_iam_member" "dataflow_temp_admin" {
  bucket = google_storage_bucket.dataflow_temp.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_dataflow_developer" {
  project = var.project_id
  role    = "roles/dataflow.developer"
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_dataflow_worker" {
  project = var.project_id
  role    = "roles/dataflow.worker"
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_pubsub_subscriber" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_bigquery_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- BigQuery Dataset ---
resource "google_bigquery_dataset" "agri_data" {
  dataset_id = "agri_data"
  location   = var.region
}

# --- lecturas_parcelas: 1 fila por parcela por hora ---
resource "google_bigquery_table" "lecturas_parcelas" {
  dataset_id          = google_bigquery_dataset.agri_data.dataset_id
  table_id            = "lecturas_parcelas"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  clustering = ["parcel_id"]

  schema = jsonencode([
    { name = "user_id",                type = "STRING",   mode = "REQUIRED" },
    { name = "parcel_id",              type = "STRING",   mode = "REQUIRED" },
    { name = "timestamp",              type = "DATETIME", mode = "REQUIRED" },
    { name = "temperatura",            type = "FLOAT",    mode = "NULLABLE" },
    { name = "humedad_ambiental",      type = "FLOAT",    mode = "NULLABLE" },
    { name = "humedad_suelo",          type = "FLOAT",    mode = "NULLABLE" },
    { name = "precipitacion_mm",       type = "FLOAT",    mode = "NULLABLE" },
    { name = "et0",                    type = "FLOAT",    mode = "NULLABLE" },
    { name = "radiacion_solar",        type = "FLOAT",    mode = "NULLABLE" },
    { name = "fuente_temperatura",     type = "STRING",   mode = "NULLABLE" },
    { name = "tipo_cultivo",           type = "STRING",   mode = "NULLABLE" },
    { name = "variedad",               type = "STRING",   mode = "NULLABLE" },
    { name = "fecha_plantacion_aprox", type = "DATE",     mode = "NULLABLE" }
  ])
}

# --- lecturas_plantas: 1 fila por planta por hora ---
resource "google_bigquery_table" "lecturas_plantas" {
  dataset_id          = google_bigquery_dataset.agri_data.dataset_id
  table_id            = "lecturas_plantas"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  clustering = ["plant_id"]

  schema = jsonencode([
    { name = "user_id",           type = "STRING",   mode = "REQUIRED" },
    { name = "greenhouse_id",     type = "STRING",   mode = "REQUIRED" },
    { name = "plant_id",          type = "STRING",   mode = "REQUIRED" },
    { name = "timestamp",         type = "DATETIME", mode = "REQUIRED" },
    { name = "temperatura",       type = "FLOAT",    mode = "NULLABLE" },
    { name = "humedad_ambiental", type = "FLOAT",    mode = "NULLABLE" },
    { name = "humedad_suelo",     type = "FLOAT",    mode = "NULLABLE" },
    { name = "tipo_cultivo",      type = "STRING",   mode = "NULLABLE" },
    { name = "variedad",          type = "STRING",   mode = "NULLABLE" },
    { name = "fecha_plantacion",  type = "DATE",     mode = "NULLABLE" }
  ])
}

# --- eventos_agricolas: 1 fila por acción manual del agricultor ---
resource "google_bigquery_table" "eventos_agricolas" {
  dataset_id          = google_bigquery_dataset.agri_data.dataset_id
  table_id            = "eventos_agricolas"
  deletion_protection = false

  schema = jsonencode([
    { name = "user_id",     type = "STRING",   mode = "REQUIRED" },
    { name = "entity_type", type = "STRING",   mode = "REQUIRED" },
    { name = "entity_id",   type = "STRING",   mode = "REQUIRED" },
    { name = "timestamp",   type = "DATETIME", mode = "REQUIRED" },
    { name = "tipo_evento", type = "STRING",   mode = "REQUIRED" },
    { name = "valor",       type = "STRING",   mode = "NULLABLE" }
  ])
}

# --- Cloud Build trigger: Dataflow ---
resource "google_cloudbuild_trigger" "dataflow" {
  name        = "dataflow-deploy"
  description = "Lanza el job de Dataflow al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["dataflow/**"]
  filename       = "dataflow/cloudbuild.yaml"

  substitutions = {
    _DB_PASSWORD = var.db_password
  }

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}
