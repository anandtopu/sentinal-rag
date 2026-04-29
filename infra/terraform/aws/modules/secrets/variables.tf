variable "release" {
  description = "Helm release name. Used as the prefix for Secrets Manager keys (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "kms_key_id" {
  description = "KMS key ARN. Null = AWS-managed Secrets Manager key."
  type        = string
  default     = null
}

variable "recovery_window_in_days" {
  description = "Window before deleted secrets are unrecoverable."
  type        = number
  default     = 30
}

variable "api_secrets" {
  description = "Initial KV map for the api secret. Subsequent values come from the AWS console (lifecycle.ignore_changes)."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "worker_secrets" {
  description = "Initial KV map for the worker secret."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "frontend_secrets" {
  description = "Initial KV map for the frontend secret."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "tags" {
  description = "Tags applied to every secret."
  type        = map(string)
  default     = {}
}
