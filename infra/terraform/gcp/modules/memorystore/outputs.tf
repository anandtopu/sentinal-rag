output "host" {
  value       = google_redis_instance.this.host
  description = "Redis host."
}

output "port" {
  value       = google_redis_instance.this.port
  description = "Redis port."
}

output "auth_string" {
  value       = google_redis_instance.this.auth_string
  description = "AUTH token (sensitive)."
  sensitive   = true
}

output "current_location_id" {
  value       = google_redis_instance.this.current_location_id
  description = "Current location ID."
}
