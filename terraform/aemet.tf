# --- Artifact Registry: repositorio para la imagen de ingesta AEMET ---
resource "google_artifact_registry_repository" "aemet" {
  location      = var.region
  repository_id = "aemet-repo"
  format        = "DOCKER"
}

# --- Base de datos para datos agrícolas en el Cloud SQL existente ---
resource "google_sql_database" "agro" {
  name     = "agrodb"
  instance = google_sql_database_instance.main.name
}

# --- Secret Manager: API key de AEMET ---
resource "google_secret_manager_secret" "aemet_api_key" {
  secret_id = "aemet-api-key"
  replication {
    auto {}
  }
}

# --- Permiso para que el SA de Cloud Run lea el secret ---
resource "google_secret_manager_secret_iam_member" "cloudrun_read_aemet_key" {
  secret_id = google_secret_manager_secret.aemet_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloudrun.email}"
}

# --- Cloud Run Job: ingesta de previsión AEMET (2x/día vía Cloud Scheduler) ---
resource "google_cloud_run_v2_job" "aemet_ingest" {
  name     = "aemet-ingest"
  location = var.region

  template {
    template {
      service_account = google_service_account.cloudrun.email

      containers {
        image = "us-docker.pkg.dev/cloudrun/container/hello:latest"

        env {
          name = "AEMET_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.aemet_api_key.secret_id
              version = "latest"
            }
          }
        }

        env {
          name  = "DATABASE_URL"
          value = "postgresql://${google_sql_user.main.name}:${var.db_password}@/agrodb?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.cloudrun_read_aemet_key,
    google_sql_database.agro,
  ]
}

# --- Service Account para Cloud Scheduler ---
resource "google_service_account" "scheduler" {
  account_id   = "cloud-scheduler-aemet"
  display_name = "Cloud Scheduler AEMET SA"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoke_aemet" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.aemet_ingest.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# --- Cloud Scheduler: 2 ejecuciones al día (7:00 y 15:00 hora española) ---
resource "google_cloud_scheduler_job" "aemet_morning" {
  name      = "aemet-ingest-morning"
  schedule  = "0 7 * * *"
  time_zone = "Europe/Madrid"
  region    = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.aemet_ingest.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
}

resource "google_cloud_scheduler_job" "aemet_afternoon" {
  name      = "aemet-ingest-afternoon"
  schedule  = "0 15 * * *"
  time_zone = "Europe/Madrid"
  region    = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.aemet_ingest.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
}

# --- Cloud Build trigger: se dispara en cada push a main que toque apis/AEMET/ ---
resource "google_cloudbuild_trigger" "aemet_ingest" {
  name        = "aemet-ingest-deploy"
  description = "Build y redeploy del job de ingesta AEMET al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["apis/AEMET/**"]

  filename = "apis/AEMET/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}
