output "documents_bucket_name" {
  value       = google_storage_bucket.documents.name
  description = "Documents bucket name."
}

output "documents_bucket_url" {
  value       = google_storage_bucket.documents.url
  description = "Documents bucket gs:// URL."
}

output "audit_bucket_name" {
  value       = google_storage_bucket.audit.name
  description = "Audit bucket name."
}

output "audit_bucket_url" {
  value       = google_storage_bucket.audit.url
  description = "Audit bucket gs:// URL."
}
