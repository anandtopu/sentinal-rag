variable "name" {
  description = "Name prefix (e.g. 'sentinelrag-dev')."
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

variable "subnet_cidr" {
  description = "Primary subnet CIDR for GKE nodes."
  type        = string
  default     = "10.30.0.0/20"
}

variable "gke_pods_cidr" {
  description = "Secondary range for GKE pod IPs."
  type        = string
  default     = "10.40.0.0/14"
}

variable "gke_services_cidr" {
  description = "Secondary range for GKE service IPs."
  type        = string
  default     = "10.44.0.0/20"
}

variable "private_service_access_prefix" {
  description = "Prefix length for the Private Service Access allocation."
  type        = number
  default     = 16
}
