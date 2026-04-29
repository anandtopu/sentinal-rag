output "gke_cluster_name" {
  value = module.gke.cluster_name
}

output "kubectl_config_command" {
  value       = "gcloud container clusters get-credentials ${module.gke.cluster_name} --region ${var.region} --project ${var.project_id}"
  description = "One-liner to wire kubectl to the GKE cluster."
}

output "cloudsql_private_ip" {
  value     = module.cloudsql.private_ip
  sensitive = true
}

output "cloudsql_database_name" {
  value = module.cloudsql.database_name
}

output "cloudsql_username" {
  value = module.cloudsql.username
}

output "cloudsql_master_password" {
  value     = var.cloudsql_master_password
  sensitive = true
}

output "redis_host" {
  value     = module.redis.host
  sensitive = true
}

output "redis_port" {
  value = module.redis.port
}

# Memorystore generates the AUTH string server-side — it's not a tfvar.
# Surface it so the runbook's Secret Manager seed step can read it.
output "redis_auth_string" {
  value     = module.redis.auth_string
  sensitive = true
}

output "documents_bucket" {
  value = module.gcs.documents_bucket_name
}

output "audit_bucket" {
  value = module.gcs.audit_bucket_name
}

output "wi_gsa_emails" {
  value = {
    api      = module.iam.api_gsa_email
    worker   = module.iam.worker_gsa_email
    frontend = module.iam.frontend_gsa_email
    eso      = module.iam.eso_gsa_email
  }
  description = "GSA emails to drop into values-gcp-dev.yaml's serviceAccount.annotations as iam.gke.io/gcp-service-account."
}
