terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    bucket = "terraform-state-bucket-dp3"
    prefix = "login"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
