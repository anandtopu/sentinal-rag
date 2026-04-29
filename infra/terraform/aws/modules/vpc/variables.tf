variable "name" {
  description = "Name prefix for VPC resources (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "cidr_block" {
  description = "CIDR block for the VPC. Should be /16 for headroom."
  type        = string
  default     = "10.0.0.0/16"
}

variable "cluster_name" {
  description = "EKS cluster name; used to tag subnets for AWS LB Controller discovery."
  type        = string
}

variable "single_nat_gateway" {
  description = "If true, route all private egress through one NAT (cheap, low HA). For dev only."
  type        = bool
  default     = false
}

variable "enable_flow_logs" {
  description = "If true, emit VPC Flow Logs to CloudWatch."
  type        = bool
  default     = true
}

variable "flow_log_retention_days" {
  description = "Retention for VPC flow log group."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
