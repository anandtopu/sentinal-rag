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
  description = "VPC network ID for private IP."
  type        = string
}

variable "private_service_access_dependency" {
  description = "Dependency handle for the PSA connection (pass module.vpc.private_service_access_connection)."
  type        = string
  default     = ""
}

variable "tier" {
  description = "Cloud SQL instance tier."
  type        = string
  default     = "db-custom-2-4096"
}

variable "availability_type" {
  description = "REGIONAL (HA, prod) or ZONAL (cheap, dev)."
  type        = string
  default     = "ZONAL"
}

variable "disk_size_gb" {
  description = "Initial disk size."
  type        = number
  default     = 50
}

variable "backup_retention_count" {
  description = "Number of automated backups retained."
  type        = number
  default     = 7
}

variable "database_name" {
  description = "Initial database name."
  type        = string
  default     = "sentinelrag"
}

variable "master_username" {
  description = "Master username."
  type        = string
  default     = "sentinel"
}

variable "master_password" {
  description = "Master password (sensitive; rotate post-bootstrap)."
  type        = string
  sensitive   = true
}

variable "deletion_protection" {
  description = "Block accidental deletion."
  type        = bool
  default     = true
}

variable "labels" {
  description = "Resource labels."
  type        = map(string)
  default     = {}
}
