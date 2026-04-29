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
resource "google_bigquery_dataset" "iot_data" {
  dataset_id = "iot_data"
  location   = var.region
}

# --- BigQuery Table ---
resource "google_bigquery_table" "sensor_aggregated" {
  dataset_id          = google_bigquery_dataset.iot_data.dataset_id
  table_id            = "sensor_aggregated"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "window_start"
  }

  schema = jsonencode([
    { name = "sensor_id",          type = "STRING",    mode = "REQUIRED" },
    { name = "sensor_type",        type = "STRING",    mode = "REQUIRED" },
    { name = "parcela_usuario_id", type = "INTEGER",   mode = "REQUIRED" },
    { name = "parcela_id",         type = "STRING",    mode = "NULLABLE" },
    { name = "user_id",            type = "INTEGER",   mode = "REQUIRED" },
    { name = "cultivo",            type = "STRING",    mode = "NULLABLE" },
    { name = "lat",                type = "FLOAT",     mode = "NULLABLE" },
    { name = "lng",                type = "FLOAT",     mode = "NULLABLE" },
    { name = "provincia",          type = "INTEGER",   mode = "NULLABLE" },
    { name = "municipio",          type = "INTEGER",   mode = "NULLABLE" },
    { name = "superficie",         type = "FLOAT",     mode = "NULLABLE" },
    { name = "window_start",       type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "window_end",         type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "value_avg",          type = "FLOAT",     mode = "REQUIRED" },
    { name = "value_min",          type = "FLOAT",     mode = "REQUIRED" },
    { name = "value_max",          type = "FLOAT",     mode = "REQUIRED" },
    { name = "reading_count",      type = "INTEGER",   mode = "REQUIRED" },
    { name = "unit",               type = "STRING",    mode = "NULLABLE" }
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
