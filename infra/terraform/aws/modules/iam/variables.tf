variable "name_prefix" {
  description = "IAM role name prefix (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "oidc_provider_url" {
  description = "OIDC provider URL without scheme (e.g. oidc.eks.us-east-1.amazonaws.com/id/ABC)."
  type        = string
}

variable "oidc_provider_arn" {
  description = "OIDC provider ARN."
  type        = string
}

variable "namespace" {
  description = "Kubernetes namespace where SentinelRAG SAs live."
  type        = string
  default     = "sentinelrag"
}

variable "api_sa_name" {
  description = "API workload ServiceAccount name. Must match Helm-rendered SA."
  type        = string
}

variable "worker_sa_name" {
  description = "Temporal-worker ServiceAccount name."
  type        = string
}

variable "frontend_sa_name" {
  description = "Frontend ServiceAccount name."
  type        = string
}

variable "eso_namespace" {
  description = "Namespace where External Secrets Operator runs."
  type        = string
  default     = "external-secrets"
}

variable "eso_sa_name" {
  description = "ESO ServiceAccount name."
  type        = string
  default     = "external-secrets"
}

variable "alb_namespace" {
  description = "Namespace where the AWS Load Balancer Controller runs."
  type        = string
  default     = "kube-system"
}

variable "alb_sa_name" {
  description = "AWS Load Balancer Controller ServiceAccount name (matches the upstream Helm chart's default)."
  type        = string
  default     = "aws-load-balancer-controller"
}

variable "documents_bucket_arn" {
  description = "ARN of the documents bucket."
  type        = string
}

variable "audit_bucket_arn" {
  description = "ARN of the audit bucket."
  type        = string
}

variable "secret_arns" {
  description = "ARNs of all Secrets Manager secrets ESO can read."
  type        = list(string)
}

variable "tags" {
  description = "Tags applied to every role."
  type        = map(string)
  default     = {}
}
