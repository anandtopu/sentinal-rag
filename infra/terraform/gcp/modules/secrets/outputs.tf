output "api_secret_id" {
  value       = google_secret_manager_secret.api.secret_id
  description = "API secret ID."
}

output "worker_secret_id" {
  value       = google_secret_manager_secret.worker.secret_id
  description = "Worker secret ID."
}

output "frontend_secret_id" {
  value       = google_secret_manager_secret.frontend.secret_id
  description = "Frontend secret ID."
}

output "all_secret_names" {
  value = [
    google_secret_manager_secret.api.name,
    google_secret_manager_secret.worker.name,
    google_secret_manager_secret.frontend.name,
  ]
  description = "Fully qualified secret names for IAM bindings."
}
