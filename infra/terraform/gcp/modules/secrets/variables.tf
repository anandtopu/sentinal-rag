variable "release" {
  description = "Release prefix (matches Helm release)."
  type        = string
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "api_secrets" {
  description = "Initial KV map for the api secret."
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

variable "labels" {
  description = "Resource labels."
  type        = map(string)
  default     = {}
}
