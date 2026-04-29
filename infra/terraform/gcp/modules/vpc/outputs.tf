output "network_id" {
  value       = google_compute_network.this.id
  description = "VPC network resource ID."
}

output "network_name" {
  value       = google_compute_network.this.name
  description = "VPC network name."
}

output "subnet_id" {
  value       = google_compute_subnetwork.primary.id
  description = "Primary subnet ID."
}

output "subnet_name" {
  value       = google_compute_subnetwork.primary.name
  description = "Primary subnet name (used by GKE)."
}

output "pods_range_name" {
  value       = "${var.name}-pods"
  description = "Secondary range name for GKE pods."
}

output "services_range_name" {
  value       = "${var.name}-services"
  description = "Secondary range name for GKE services."
}

output "private_service_access_connection" {
  value       = google_service_networking_connection.private_vpc_connection.id
  description = "PSA connection ID; downstream Cloud SQL / Memorystore depend on it."
}
