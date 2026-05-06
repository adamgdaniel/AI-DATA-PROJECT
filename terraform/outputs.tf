output "frontend_url" {
  value = google_cloud_run_v2_service.frontend.uri
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "db_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "agent_url" {
  value = google_cloud_run_v2_service.agent.uri
}

output "rag_api_url" {
  value = google_cloud_run_v2_service.rag_api.uri
}

output "sensor_api_url" {
  value = google_cloud_run_v2_service.sensor_api.uri
}

output "model_serving_url" {
  value = google_cloud_run_v2_service.model_serving.uri
}