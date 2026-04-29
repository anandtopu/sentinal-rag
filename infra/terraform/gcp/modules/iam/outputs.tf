output "api_gsa_email" {
  value       = google_service_account.api.email
  description = "GSA email — use as iam.gke.io/gcp-service-account on the api KSA."
}

output "worker_gsa_email" {
  value       = google_service_account.worker.email
  description = "GSA email for the temporal-worker KSA."
}

output "frontend_gsa_email" {
  value       = google_service_account.frontend.email
  description = "GSA email for the frontend KSA."
}

output "eso_gsa_email" {
  value       = google_service_account.eso.email
  description = "GSA email for ESO."
}
