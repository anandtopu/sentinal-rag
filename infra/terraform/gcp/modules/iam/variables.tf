variable "name_prefix" {
  description = "GSA name prefix (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "workload_identity_pool" {
  description = "Workload Identity pool string (e.g. '<project>.svc.id.goog')."
  type        = string
}

variable "namespace" {
  description = "K8s namespace where SentinelRAG SAs live."
  type        = string
  default     = "sentinelrag"
}

variable "api_sa_name" {
  description = "K8s ServiceAccount name for api."
  type        = string
}

variable "worker_sa_name" {
  description = "K8s ServiceAccount name for temporal-worker."
  type        = string
}

variable "frontend_sa_name" {
  description = "K8s ServiceAccount name for frontend."
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

variable "documents_bucket_name" {
  description = "GCS documents bucket name."
  type        = string
}

variable "audit_bucket_name" {
  description = "GCS audit bucket name."
  type        = string
}

variable "secret_names" {
  description = "Fully-qualified Secret Manager secret names (projects/.../secrets/...)."
  type        = list(string)
}
