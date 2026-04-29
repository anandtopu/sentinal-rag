output "documents_bucket_name" {
  value       = aws_s3_bucket.documents.id
  description = "Documents bucket name."
}

output "documents_bucket_arn" {
  value       = aws_s3_bucket.documents.arn
  description = "Documents bucket ARN."
}

output "audit_bucket_name" {
  value       = aws_s3_bucket.audit.id
  description = "Audit bucket name."
}

output "audit_bucket_arn" {
  value       = aws_s3_bucket.audit.arn
  description = "Audit bucket ARN."
}
