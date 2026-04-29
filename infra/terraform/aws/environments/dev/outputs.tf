output "vpc_id" {
  value = module.vpc.vpc_id
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "kubectl_config_command" {
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
  description = "One-liner to wire kubectl to this cluster."
}

output "rds_endpoint" {
  value     = module.rds.endpoint
  sensitive = true
}

output "rds_port" {
  value = module.rds.port
}

output "rds_database_name" {
  value = module.rds.database_name
}

output "rds_username" {
  value = module.rds.username
}

# Surfaces the password input back as an output for the deploy runbook's
# DB_URL / Secrets Manager seed step. Stays sensitive.
output "rds_master_password" {
  value     = var.rds_master_password
  sensitive = true
}

output "redis_endpoint" {
  value     = module.redis.primary_endpoint
  sensitive = true
}

output "redis_port" {
  value = module.redis.port
}

output "redis_auth_token" {
  value     = var.redis_auth_token
  sensitive = true
}

output "documents_bucket" {
  value = module.s3.documents_bucket_name
}

output "audit_bucket" {
  value = module.s3.audit_bucket_name
}

output "irsa_role_arns" {
  value = {
    api            = module.iam.api_role_arn
    worker         = module.iam.worker_role_arn
    frontend       = module.iam.frontend_role_arn
    eso            = module.iam.eso_role_arn
    alb_controller = module.iam.alb_controller_role_arn
  }
  description = "IRSA role ARNs. api/worker/frontend → Helm values-dev.yaml. eso → infra/bootstrap/external-secrets/values.yaml. alb_controller → infra/bootstrap/aws-load-balancer-controller/values.yaml."
}
