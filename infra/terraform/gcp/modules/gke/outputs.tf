output "cluster_name" {
  value       = google_container_cluster.this.name
  description = "GKE cluster name."
}

output "cluster_endpoint" {
  value       = google_container_cluster.this.endpoint
  description = "Cluster master endpoint."
  sensitive   = true
}

output "cluster_ca_certificate" {
  value       = google_container_cluster.this.master_auth[0].cluster_ca_certificate
  description = "Cluster CA cert (base64)."
  sensitive   = true
}

output "workload_identity_pool" {
  value       = "${var.project_id}.svc.id.goog"
  description = "Workload Identity pool string for IAM bindings."
}

output "node_pool_name" {
  value       = google_container_node_pool.primary.name
  description = "Primary node pool name."
}
