variable "name" {
  description = "Name prefix."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the cache subnet group."
  type        = list(string)
}

variable "client_security_group_id" {
  description = "Security group of the EKS workloads that connect to Redis."
  type        = string
}

variable "engine_version" {
  description = "Redis engine version."
  type        = string
  default     = "7.1"
}

variable "node_type" {
  description = "Cache node instance type."
  type        = string
  default     = "cache.t4g.small"
}

variable "num_node_groups" {
  description = "Number of shards. 1 = single primary; >1 = cluster mode."
  type        = number
  default     = 1
}

variable "replicas_per_node_group" {
  description = "Replicas per shard."
  type        = number
  default     = 0
}

variable "multi_az" {
  description = "Enable Multi-AZ. Off in dev."
  type        = bool
  default     = false
}

variable "auth_token" {
  description = "Redis AUTH token. Pass via secret; rotate manually."
  type        = string
  sensitive   = true
  default     = null
}

variable "snapshot_retention_days" {
  description = "How long to keep automatic snapshots."
  type        = number
  default     = 1
}

variable "apply_immediately" {
  description = "Apply changes outside the maintenance window."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
