output "api_secret_arn" {
  value       = aws_secretsmanager_secret.api.arn
  description = "ARN of the api Secrets Manager secret."
}

output "worker_secret_arn" {
  value       = aws_secretsmanager_secret.worker.arn
  description = "ARN of the worker Secrets Manager secret."
}

output "frontend_secret_arn" {
  value       = aws_secretsmanager_secret.frontend.arn
  description = "ARN of the frontend Secrets Manager secret."
}

output "all_secret_arns" {
  value = [
    aws_secretsmanager_secret.api.arn,
    aws_secretsmanager_secret.worker.arn,
    aws_secretsmanager_secret.frontend.arn,
  ]
  description = "All secret ARNs for IAM policy fan-out."
}
