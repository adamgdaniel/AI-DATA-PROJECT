# --- VPC peering para Cloud SQL con IP privada ---
# Habilita Service Networking para el peering
resource "google_project_service" "servicenetworking" {
  service            = "servicenetworking.googleapis.com"
  disable_on_destroy = false
}

# Reusa la red default del proyecto (no creamos VPC nueva para mantener la infra simple)
data "google_compute_network" "default" {
  name = "default"
}

# Rango interno /16 que Google reserva para los servicios privados (Cloud SQL aquí)
resource "google_compute_global_address" "private_ip_sql" {
  name          = "private-ip-sql"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = data.google_compute_network.default.id
}

# Conexión peering: nuestra VPC <-> red de servicios privados de Google
resource "google_service_networking_connection" "private_sql" {
  network                 = data.google_compute_network.default.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_sql.name]

  depends_on = [google_project_service.servicenetworking]
}
