variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Resource name prefix; matches helm release name."
  type        = string
  default     = "sentinelrag-dev"
}

variable "vpc_cidr" {
  description = "VPC CIDR."
  type        = string
  default     = "10.20.0.0/16"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.30"
}

variable "node_instance_types" {
  description = "EC2 instance types for the EKS managed node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "rds_master_password" {
  description = "Master password seed for RDS. Pass via TF_VAR_rds_master_password (CI) or terraform.tfvars (local). Rotated out-of-band post-bootstrap."
  type        = string
  sensitive   = true
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "redis_auth_token" {
  description = "Initial Redis AUTH token. Rotated post-bootstrap."
  type        = string
  sensitive   = true
}

variable "k8s_namespace" {
  description = "Kubernetes namespace where SentinelRAG runs."
  type        = string
  default     = "sentinelrag"
}
