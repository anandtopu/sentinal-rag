variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Resource name prefix; matches Helm release."
  type        = string
  default     = "sentinelrag-dev"
}

variable "cloudsql_master_password" {
  description = "Cloud SQL master password seed (rotated post-bootstrap)."
  type        = string
  sensitive   = true
}

variable "k8s_namespace" {
  description = "K8s namespace where SentinelRAG runs."
  type        = string
  default     = "sentinelrag"
}
