variable "project_id" {
  default = "project-7f8b4dee-2b72-40f2-941"
}

variable "region" {
  default = "europe-west1"
}

variable "db_password" {
  sensitive = true
}

variable "secret_key" {
  sensitive = true
}
