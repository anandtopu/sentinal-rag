variable "name" {
  description = "Name prefix (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Bucket location."
  type        = string
  default     = "us-central1"
}

variable "kms_key_name" {
  description = "CMEK resource (null = Google-managed)."
  type        = string
  default     = null
}

variable "force_destroy" {
  description = "Allow terraform destroy on the documents bucket. Audit bucket ignores this."
  type        = bool
  default     = false
}

variable "audit_retention_seconds" {
  description = "Retention period for audit objects, in seconds. 7 years = 220752000."
  type        = number
  default     = 220752000
}

variable "audit_lock_retention" {
  description = "When true, the retention policy is irrevocably locked (true immutability)."
  type        = bool
  default     = true
}

variable "labels" {
  description = "Resource labels."
  type        = map(string)
  default     = {}
}
