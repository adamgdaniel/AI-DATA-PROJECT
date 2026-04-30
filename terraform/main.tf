# --- Artifact Registry ---
resource "google_artifact_registry_repository" "login" {
  location      = var.region
  repository_id = "login-repo"
  format        = "DOCKER"
}

# --- Service Account para Cloud Run ---
resource "google_service_account" "cloudrun" {
  account_id   = "cloudrun-login"
  display_name = "Cloud Run Login SA"
}

resource "google_project_iam_member" "cloudrun_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}

resource "google_service_account_iam_member" "cloudbuild_act_as_cloudrun" {
  service_account_id = google_service_account.cloudrun.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_service_account_iam_member" "cloudbuild_act_as_compute" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- Cloud SQL ---
resource "google_sql_database_instance" "main" {
  name             = "login-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = "db-f1-micro"
  }

  deletion_protection = false
}

resource "google_sql_database" "main" {
  name     = "logindb"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "main" {
  name     = "loginuser"
  instance = google_sql_database_instance.main.name
  password = var.db_password
}

# --- Cloud Run: API ---
resource "google_cloud_run_v2_service" "api" {
  name     = "login-api"
  location = var.region

  template {
    service_account = google_service_account.cloudrun.email

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

  # Cloud Build actualizará la imagen; ignoramos cambios en template tras el primer apply
  lifecycle {
    ignore_changes = [template]
  }

  depends_on = [google_project_iam_member.cloudrun_cloudsql]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run: Data API ---
resource "google_cloud_run_v2_service" "data_api" {
  name     = "data-api"
  location = var.region

  template {
    service_account = google_service_account.cloudrun.email

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

  depends_on = [google_project_iam_member.cloudrun_cloudsql]
}

resource "google_cloud_run_v2_service_iam_member" "data_api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.data_api.location
  name     = google_cloud_run_v2_service.data_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run: Frontend ---
resource "google_cloud_run_v2_service" "frontend" {
  name     = "login-frontend"
  location = var.region

  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello:latest"

      env {
        name  = "API_URL"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "DATA_API_URL"
        value = google_cloud_run_v2_service.data_api.uri
      }
      env {
        name  = "IOT_API_URL"
        value = google_cloud_run_v2_service.iot_api.uri
      }
      env {
        name  = "SECRET_KEY"
        value = var.secret_key
      }
    }
  }

  lifecycle {
    ignore_changes = [template]
  }
}

# --- Secret Manager: SECRET_KEY del frontend ---
resource "google_secret_manager_secret" "frontend_secret_key" {
  secret_id = "frontend-secret-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "frontend_read_secret_key" {
  secret_id = google_secret_manager_secret.frontend_secret_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_secret_manager_secret_iam_member" "frontend_read_aemet_key" {
  secret_id = "aemet-api-key"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- Cloud Build trigger: login-frontend ---
resource "google_cloudbuild_trigger" "login_frontend" {
  name        = "login-frontend-deploy"
  description = "Build y redeploy del frontend al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["frontend/**"]

  filename = "frontend/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

# --- Cloud Build trigger: login-api ---
resource "google_cloudbuild_trigger" "login_api" {
  name        = "login-api-deploy"
  description = "Build y redeploy de la API de login al hacer push a main"
  location    = var.region

  github {
    owner = "adamgdaniel"
    name  = "AI-DATA-PROJECT"
    push {
      branch = "^main$"
    }
  }

  included_files = ["logging/api/**"]

  filename = "logging/api/cloudbuild.yaml"

  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.frontend.location
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
