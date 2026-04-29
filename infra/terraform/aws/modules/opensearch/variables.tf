variable "name" {
  description = "Name prefix (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets the domain ENIs will live in."
  type        = list(string)
}

variable "client_security_group_id" {
  description = "Security group of EKS workloads that need to reach OpenSearch."
  type        = string
}

variable "engine_version" {
  description = "OpenSearch engine version."
  type        = string
  default     = "OpenSearch_2.13"
}

variable "instance_type" {
  description = "Data node instance type."
  type        = string
  default     = "t3.small.search"
}

variable "instance_count" {
  description = "Data node count."
  type        = number
  default     = 2
}

variable "zone_awareness_enabled" {
  description = "Multi-AZ data node placement."
  type        = bool
  default     = true
}

variable "dedicated_master_enabled" {
  description = "Run dedicated master nodes (recommended for prod)."
  type        = bool
  default     = false
}

variable "master_instance_type" {
  description = "Dedicated master instance type."
  type        = string
  default     = "t3.small.search"
}

variable "ebs_volume_size_gb" {
  description = "Per-node EBS volume size."
  type        = number
  default     = 20
}

variable "kms_key_id" {
  description = "KMS key ARN for at-rest encryption (null = AWS-managed)."
  type        = string
  default     = null
}

variable "master_user_name" {
  description = "Fine-grained access master user."
  type        = string
  default     = "sentinel-os-admin"
}

variable "master_user_password" {
  description = "Master user password. Pass via Secrets Manager / TF_VAR_."
  type        = string
  sensitive   = true
}

variable "create_service_linked_role" {
  description = "Create the OpenSearch service-linked role. Set false if it already exists in the account."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
