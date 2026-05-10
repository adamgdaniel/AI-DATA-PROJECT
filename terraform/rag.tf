# --- Artifact Registry (compartido por rag-api, sensor-api y agent) ---
resource "google_artifact_registry_repository" "rag" {
  location      = var.region
  repository_id = "rag-repo"
  format        = "DOCKER"
}

# --- IAM: Vertex AI para los servicios que llaman a embeddings y Gemini ---
resource "google_project_iam_member" "cloudrun_vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}

# --- Cloud Storage: bucket para los PDFs originales ---
resource "google_storage_bucket" "agro_docs" {
  name                        = "${var.project_id}-agro-docs"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_iam_member" "cloudrun_gcs_rw" {
  bucket = google_storage_bucket.agro_docs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloudrun.email}"
}
resource "google_project_iam_member" "cloudrun_bigquery_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_project_iam_member" "cloudrun_bigquery_jobuser" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}

# --- BigQuery: dataset y tabla para los chunks del RAG ---
resource "google_bigquery_dataset" "rag_data" {
  dataset_id = "rag_data"
  location   = var.region
}

resource "google_bigquery_table" "document_chunks" {
  dataset_id          = google_bigquery_dataset.rag_data.dataset_id
  table_id            = "document_chunks"
  deletion_protection = false

  schema = jsonencode([
    { name = "chunk_id",   type = "STRING",    mode = "REQUIRED" },
    { name = "doc_path",   type = "STRING",    mode = "REQUIRED" },
    { name = "cultivo",    type = "STRING",    mode = "NULLABLE" },
    { name = "tipo_doc",   type = "STRING",    mode = "NULLABLE" },
    { name = "titulo",     type = "STRING",    mode = "NULLABLE" },
    { name = "texto",      type = "STRING",    mode = "REQUIRED" },
    { name = "embedding",  type = "FLOAT64",   mode = "REPEATED" },
    { name = "created_at", type = "TIMESTAMP", mode = "NULLABLE" }
  ])
}

# --- Cloud Run: RAG API ---
resource "google_cloud_run_v2_service" "rag_api" {
  name     = "rag-api"
  location = var.region

  template {
    service_account = google_service_account.cloudrun.email
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello:latest"
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.agro_docs.name
      }
    }
  }

  lifecycle { ignore_changes = [template] }
  depends_on = [
    google_project_iam_member.cloudrun_vertex_user,
    google_storage_bucket_iam_member.cloudrun_gcs_rw,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "rag_api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.rag_api.location
  name     = google_cloud_run_v2_service.rag_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run: Sensor API ---
resource "google_cloud_run_v2_service" "sensor_api" {
  name     = "sensor-api"
  location = var.region

  template {
    service_account = google_service_account.cloudrun.email

    vpc_access {
      network_interfaces {
        network    = "default"
        subnetwork = "default"
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello:latest"
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = google_sql_database_instance.main.connection_name
      }
      env {
        name  = "DB_NAME"
        value = google_sql_database.main.name
      }
      env {
        name  = "DB_USER"
        value = google_sql_user.main.name
      }
      env {
        name  = "DB_PASSWORD"
        value = var.db_password
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.main.connection_name] }
    }
  }

  lifecycle { ignore_changes = [template] }
  depends_on = [google_project_iam_member.cloudrun_cloudsql]
}

resource "google_cloud_run_v2_service_iam_member" "sensor_api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.sensor_api.location
  name     = google_cloud_run_v2_service.sensor_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run: Agent ---
resource "google_cloud_run_v2_service" "agent" {
  name     = "agent"
  location = var.region

  template {
    service_account = google_service_account.cloudrun.email
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello:latest"
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "SENSOR_API_URL"
        value = google_cloud_run_v2_service.sensor_api.uri
      }
      env {
        name  = "RAG_API_URL"
        value = google_cloud_run_v2_service.rag_api.uri
      }
      env {
        name  = "MODEL_SERVING_URL"
        value = google_cloud_run_v2_service.model_serving.uri
      }
    }
  }

  lifecycle { ignore_changes = [template] }
  depends_on = [
    google_project_iam_member.cloudrun_vertex_user,
    google_cloud_run_v2_service.sensor_api,
    google_cloud_run_v2_service.rag_api,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "agent_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.agent.location
  name     = google_cloud_run_v2_service.agent.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Build triggers ---
resource "google_cloudbuild_trigger" "rag_api" {
  name     = "rag-api-deploy"
  location = var.region
  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push  { branch = "^main$" }
  }
  included_files = ["RAG_api/**"]
  filename       = "RAG_api/cloudbuild.yaml"
  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_cloudbuild_trigger" "sensor_api" {
  name     = "sensor-api-deploy"
  location = var.region
  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push  { branch = "^main$" }
  }
  included_files = ["sensor-api/**"]
  filename       = "sensor-api/cloudbuild.yaml"
  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_cloudbuild_trigger" "agent" {
  name     = "agent-deploy"
  location = var.region
  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push  { branch = "^main$" }
  }
  included_files = ["agent/**"]
  filename       = "agent/cloudbuild.yaml"
  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}
