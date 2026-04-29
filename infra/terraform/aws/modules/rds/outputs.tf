output "endpoint" {
  value       = aws_db_instance.this.address
  description = "RDS endpoint hostname."
}

output "port" {
  value       = aws_db_instance.this.port
  description = "RDS port."
}

output "database_name" {
  value       = aws_db_instance.this.db_name
  description = "Initial database name."
}

output "username" {
  value       = aws_db_instance.this.username
  description = "Master username."
}

output "instance_arn" {
  value       = aws_db_instance.this.arn
  description = "RDS instance ARN."
}

output "security_group_id" {
  value       = aws_security_group.this.id
  description = "Security group attached to the RDS instance."
}

output "connection_string" {
  value       = "postgresql+asyncpg://${aws_db_instance.this.username}:REPLACE_PASSWORD@${aws_db_instance.this.address}:${aws_db_instance.this.port}/${aws_db_instance.this.db_name}"
  description = "Async connection string template; password lives in Secrets Manager."
  sensitive   = true
}
