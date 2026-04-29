output "instance_name" {
  value       = google_sql_database_instance.this.name
  description = "Cloud SQL instance name."
}

output "private_ip" {
  value       = google_sql_database_instance.this.private_ip_address
  description = "Private IP for the instance."
}

output "connection_name" {
  value       = google_sql_database_instance.this.connection_name
  description = "<project>:<region>:<instance> string used by the Cloud SQL Auth Proxy."
}

output "database_name" {
  value       = google_sql_database.primary.name
  description = "Initial database name."
}

output "username" {
  value       = google_sql_user.master.name
  description = "Master username."
}
