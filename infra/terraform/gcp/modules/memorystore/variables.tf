variable "name" {
  description = "Name prefix."
  type        = string
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "us-central1"
}

variable "network_id" {
  description = "VPC network ID."
  type        = string
}

variable "tier" {
  description = "BASIC (single node) or STANDARD_HA (replicated)."
  type        = string
  default     = "BASIC"
}

variable "memory_size_gb" {
  description = "Memory size in GB."
  type        = number
  default     = 1
}

variable "reserved_ip_range" {
  description = "Reserved IP range for the instance (null = auto)."
  type        = string
  default     = null
}

variable "labels" {
  description = "Resource labels."
  type        = map(string)
  default     = {}
}
