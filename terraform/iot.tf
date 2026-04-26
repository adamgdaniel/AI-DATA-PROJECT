# --- Artifact Registry ---
resource "google_artifact_registry_repository" "iot" {
  location      = var.region
  repository_id = "iot-repo"
  format        = "DOCKER"
}

# --- Service Account para servicios IoT ---
resource "google_service_account" "iot" {
  account_id   = "cloudrun-iot"
  display_name = "Cloud Run IoT SA"
}

resource "google_project_iam_member" "iot_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.iot.email}"
}

resource "google_project_iam_member" "iot_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.iot.email}"
}

resource "google_service_account_iam_member" "cloudbuild_act_as_iot" {
  service_account_id = google_service_account.iot.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- Pub/Sub ---
resource "google_pubsub_topic" "sensor_readings" {
  name = "sensor-readings-raw"
}

# --- Secret Manager: clave de cifrado para tokens HA ---
resource "google_secret_manager_secret" "iot_encryption_key" {
  secret_id = "iot-encryption-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "iot_read_encryption_key" {
  secret_id = google_secret_manager_secret.iot_encryption_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.iot.email}"
}

# --- Cloud Run Service: IoT API ---
resource "google_cloud_run_v2_service" "iot_api" {
  name     = "iot-api"
  location = var.region

  template {
    service_account = google_service_account.iot.email

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
        name = "ENCRYPTION_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.iot_encryption_key.secret_id
            version = "latest"
          }
        }
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

  lifecycle {
    ignore_changes = [template]
  }

  depends_on = [
    google_project_iam_member.iot_cloudsql,
    google_secret_manager_secret_iam_member.iot_read_encryption_key
  ]
}

resource "google_cloud_run_v2_service_iam_member" "iot_api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.iot_api.location
  name     = google_cloud_run_v2_service.iot_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run Job: IoT Puller ---
resource "google_cloud_run_v2_job" "iot_puller" {
  name     = "iot-puller"
  location = var.region

  template {
    template {
      service_account = google_service_account.iot.email

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
          name  = "GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "PUBSUB_TOPIC"
          value = google_pubsub_topic.sensor_readings.name
        }
        env {
          name = "ENCRYPTION_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.iot_encryption_key.secret_id
              version = "latest"
            }
          }
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
  }

  lifecycle {
    ignore_changes = [template]
  }

  depends_on = [
    google_project_iam_member.iot_cloudsql,
    google_secret_manager_secret_iam_member.iot_read_encryption_key
  ]
}

# --- Cloud Scheduler: lanzar el puller cada 15 minutos ---
resource "google_service_account" "scheduler_iot" {
  account_id   = "scheduler-iot"
  display_name = "Cloud Scheduler IoT SA"
}

resource "google_project_iam_member" "scheduler_iot_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler_iot.email}"
}

resource "google_cloud_scheduler_job" "iot_puller" {
  name      = "iot-puller-trigger"
  schedule  = "*/15 * * * *"
  time_zone = "Europe/Madrid"
  region    = var.region

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.iot_puller.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_iot.email
    }
  }
}

# --- Cloud Build triggers ---
resource "google_cloudbuild_trigger" "iot_api" {
  name        = "iot-api-deploy"
  description = "Build y redeploy de la IoT API al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["IoT/api/**"]
  filename       = "IoT/api/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_cloudbuild_trigger" "iot_puller" {
  name        = "iot-puller-deploy"
  description = "Build y redeploy del IoT puller al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["IoT/puller/**"]
  filename       = "IoT/puller/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}
