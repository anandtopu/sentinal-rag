variable "name" {
  description = "Cluster name (e.g. 'sentinelrag-dev')."
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
  description = "VPC network resource ID."
  type        = string
}

variable "subnet_id" {
  description = "Primary subnet ID."
  type        = string
}

variable "pods_range_name" {
  description = "Secondary range name for pod IPs."
  type        = string
}

variable "services_range_name" {
  description = "Secondary range name for service IPs."
  type        = string
}

variable "master_ipv4_cidr" {
  description = "CIDR for the GKE control plane (must not overlap with VPC)."
  type        = string
  default     = "172.16.0.0/28"
}

variable "master_authorized_cidrs" {
  description = "CIDRs allowed onto the GKE master endpoint."
  type = list(object({
    cidr         = string
    display_name = string
  }))
  default = [
    { cidr = "0.0.0.0/0", display_name = "any" }
  ]
}

variable "release_channel" {
  description = "GKE release channel."
  type        = string
  default     = "REGULAR"
}

variable "node_machine_type" {
  description = "Machine type for the primary node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "node_disk_size_gb" {
  description = "Per-node disk size."
  type        = number
  default     = 50
}

variable "node_initial_count" {
  description = "Initial nodes per zone."
  type        = number
  default     = 1
}

variable "node_min_count" {
  description = "Min nodes per zone."
  type        = number
  default     = 1
}

variable "node_max_count" {
  description = "Max nodes per zone."
  type        = number
  default     = 3
}

variable "node_service_account" {
  description = "Service account email for nodes (registry pull only)."
  type        = string
}

variable "database_encryption_key" {
  description = "CMEK resource ID for etcd encryption (null = Google-managed)."
  type        = string
  default     = null
}

variable "deletion_protection" {
  description = "Block accidental cluster deletion."
  type        = bool
  default     = true
}

variable "labels" {
  description = "Labels applied to the cluster + node pool."
  type        = map(string)
  default     = {}
}
