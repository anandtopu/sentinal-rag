output "api_role_arn" {
  value       = aws_iam_role.api.arn
  description = "IRSA role ARN for the api SA."
}

output "worker_role_arn" {
  value       = aws_iam_role.worker.arn
  description = "IRSA role ARN for the temporal-worker SA."
}

output "frontend_role_arn" {
  value       = aws_iam_role.frontend.arn
  description = "IRSA role ARN for the frontend SA."
}

output "eso_role_arn" {
  value       = aws_iam_role.eso.arn
  description = "IRSA role ARN for ESO."
}
