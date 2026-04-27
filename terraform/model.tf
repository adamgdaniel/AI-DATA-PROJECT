# --- Artifact Registry: repositorio para la imagen del model-serving ---
resource "google_artifact_registry_repository" "model_serving" {
  location      = var.region
  repository_id = "model-serving-repo"
  format        = "DOCKER"
}

# --- Cloud Run Service: model-serving ---
# Reutiliza el SA cloudrun y el secret aemet-db-url definidos en aemet.tf
resource "google_cloud_run_v2_service" "model_serving" {
  name     = "model-serving"
  location = var.region

  template {
    service_account = google_service_account.cloudrun.email

    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello:latest"

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_url.secret_id
            version = "latest"
          }
        }
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
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  # Cloud Build actualiza la imagen en cada push; Terraform no toca el template
  lifecycle {
    ignore_changes = [template]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.cloudrun_read_db_url,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "model_serving_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.model_serving.location
  name     = google_cloud_run_v2_service.model_serving.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Build trigger ---
resource "google_cloudbuild_trigger" "model_serving" {
  name        = "model-serving-deploy"
  description = "Build y redeploy del model-serving al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["model-serving/**"]
  filename       = "model-serving/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}