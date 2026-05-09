variable "project_id" {
  default = "project-7f8b4dee-2b72-40f2-941"
}

variable "region" {
  default = "europe-west1"
}

variable "project_number" {
  default = "874385889107"
}

variable "db_password" {
  sensitive = true
}

variable "secret_key" {
  sensitive = true
}

variable "test_password" {
  sensitive = true
}

variable "fake_sensors_user_id" {
  description = "ID del usuario al que se asocian los sensores fake"
  default     = 1
}

variable "fake_sensors_parcela_ext_1" {
  description = "parcela_usuario_id para FS-EXT-001"
  default     = 1
}

variable "fake_sensors_parcela_ext_2" {
  description = "parcela_usuario_id para FS-EXT-002"
  default     = 2
}

variable "fake_sensors_parcela_gh_1" {
  description = "parcela_usuario_id para FS-GH-001"
  default     = 3
}

variable "fake_sensors_parcela_gh_2" {
  description = "parcela_usuario_id para FS-GH-002"
  default     = 4
}

