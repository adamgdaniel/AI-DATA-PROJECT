# --- Artifact Registry para Dataflow Parcelas ---
resource "google_artifact_registry_repository" "dataflow_parcelas" {
  location      = var.region
  repository_id = "dataflow-parcelas-repo"
  format        = "DOCKER"
}

# --- Artifact Registry para Dataflow Invernaderos ---
resource "google_artifact_registry_repository" "dataflow_invernaderos" {
  location      = var.region
  repository_id = "dataflow-invernaderos-repo"
  format        = "DOCKER"
}

# --- Pub/Sub Dead Letter Topic para sensores ---
resource "google_pubsub_topic" "sensor_readings_dead_letter" {
  name = "sensor_readings_dead_letter"
}

resource "google_pubsub_subscription" "sensor_readings_dead_letter_sub" {
  name  = "sensor-readings-dead-letter-sub"
  topic = google_pubsub_topic.sensor_readings_dead_letter.id

  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
}

# --- Cloud Build trigger: Dataflow Parcelas ---
resource "google_cloudbuild_trigger" "dataflow_parcelas" {
  name        = "dataflow-parcelas-deploy"
  description = "Build y redeploy del Dataflow Parcelas al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["dataflow-v2/parcelas/**"]
  filename       = "dataflow-v2/parcelas/cloudbuild.yaml"

  substitutions = {
    _DB_PASSWORD              = var.db_password
    _INSTANCE_CONNECTION_NAME = google_sql_database_instance.main.connection_name
    _DB_USER                  = google_sql_user.main.name
    _DB_NAME                  = google_sql_database.main.name
    _DB_NAME_METEO            = google_sql_database.agro.name
  }

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- Cloud Build trigger: Dataflow Invernaderos ---
resource "google_cloudbuild_trigger" "dataflow_invernaderos" {
  name        = "dataflow-invernaderos-deploy"
  description = "Build y redeploy del Dataflow Invernaderos al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["dataflow-v2/invernaderos/**"]
  filename       = "dataflow-v2/invernaderos/cloudbuild.yaml"

  substitutions = {
    _DB_PASSWORD              = var.db_password
    _INSTANCE_CONNECTION_NAME = google_sql_database_instance.main.connection_name
    _DB_USER                  = google_sql_user.main.name
    _DB_NAME                  = google_sql_database.main.name
  }

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}
