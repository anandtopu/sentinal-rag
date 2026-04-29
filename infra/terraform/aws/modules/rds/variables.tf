variable "name" {
  description = "Name prefix (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the DB subnet group."
  type        = list(string)
}

variable "client_security_group_id" {
  description = "Security group of the EKS workloads that need to reach Postgres."
  type        = string
}

variable "engine_version" {
  description = "Postgres engine version."
  type        = string
  default     = "16.4"
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage_gb" {
  description = "Initial GP3 storage in GB."
  type        = number
  default     = 50
}

variable "max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling."
  type        = number
  default     = 200
}

variable "kms_key_id" {
  description = "KMS key ARN for storage encryption (null = AWS-managed key)."
  type        = string
  default     = null
}

variable "database_name" {
  description = "Initial database name."
  type        = string
  default     = "sentinelrag"
}

variable "master_username" {
  description = "Master DB user."
  type        = string
  default     = "sentinel"
}

variable "master_password" {
  description = "Master DB password. SHOULD come from Secrets Manager — pass via var, do not commit."
  type        = string
  sensitive   = true
}

variable "multi_az" {
  description = "Enable Multi-AZ. Off in dev (cost), on in prod."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Backup retention in days."
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Block accidental deletion."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip final snapshot on destroy. True only for ephemeral envs."
  type        = bool
  default     = false
}

variable "apply_immediately" {
  description = "Apply parameter changes without waiting for the maintenance window."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
