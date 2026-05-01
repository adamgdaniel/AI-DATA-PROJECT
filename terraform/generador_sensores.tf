# --- Artifact Registry ---
resource "google_artifact_registry_repository" "fake_sensors" {
  location      = var.region
  repository_id = "fake-sensors-repo"
  format        = "DOCKER"
}

# --- Service Account ---
resource "google_service_account" "fake_sensors" {
  account_id   = "fake-sensors-sa"
  display_name = "Fake Sensors Generator SA"
}

resource "google_project_iam_member" "fake_sensors_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.fake_sensors.email}"
}

resource "google_project_iam_member" "fake_sensors_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.fake_sensors.email}"
}

resource "google_service_account_iam_member" "cloudbuild_act_as_fake_sensors" {
  service_account_id = google_service_account.fake_sensors.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- Cloud Run Job ---
resource "google_cloud_run_v2_job" "fake_sensors" {
  name     = "fake-sensors"
  location = var.region

  template {
    template {
      service_account = google_service_account.fake_sensors.email
      max_retries     = 0

      containers {
        image = "us-docker.pkg.dev/cloudrun/container/hello:latest"

        env {
          name  = "GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "PUBSUB_TOPIC"
          value = google_pubsub_topic.sensor_readings.name
        }
        env {
          name  = "USER_ID"
          value = tostring(var.fake_sensors_user_id)
        }
        env {
          name  = "PARCELA_EXT_1_ID"
          value = tostring(var.fake_sensors_parcela_ext_1)
        }
        env {
          name  = "PARCELA_EXT_2_ID"
          value = tostring(var.fake_sensors_parcela_ext_2)
        }
        env {
          name  = "PARCELA_GH_1_ID"
          value = tostring(var.fake_sensors_parcela_gh_1)
        }
        env {
          name  = "PARCELA_GH_2_ID"
          value = tostring(var.fake_sensors_parcela_gh_2)
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template]
  }

  depends_on = [
    google_project_iam_member.fake_sensors_pubsub,
    google_project_iam_member.fake_sensors_firestore,
  ]
}

# --- Cloud Scheduler: lanzar cada 5 minutos ---
resource "google_service_account" "scheduler_fake_sensors" {
  account_id   = "scheduler-fake-sensors"
  display_name = "Cloud Scheduler Fake Sensors SA"
}

resource "google_project_iam_member" "scheduler_fake_sensors_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler_fake_sensors.email}"
}

resource "google_cloud_scheduler_job" "fake_sensors" {
  name      = "fake-sensors-trigger"
  schedule  = "*/5 * * * *"
  time_zone = "Europe/Madrid"
  region    = var.region

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.fake_sensors.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_fake_sensors.email
    }
  }
}

# --- Cloud Build trigger ---
resource "google_cloudbuild_trigger" "fake_sensors" {
  name        = "fake-sensors-deploy"
  description = "Build y redeploy del generador de sensores fake al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["generador_sensores/**"]
  filename       = "generador_sensores/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}
