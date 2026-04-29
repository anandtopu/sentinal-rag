variable "name" {
  description = "EKS cluster name (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.30"
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for nodes + cluster ENIs."
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for the cluster ENIs (so the API can be public)."
  type        = list(string)
}

variable "public_access_cidrs" {
  description = "CIDRs allowed to hit the public EKS API endpoint."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_capacity_type" {
  description = "ON_DEMAND or SPOT."
  type        = string
  default     = "ON_DEMAND"
}

variable "node_desired_size" {
  description = "Initial desired node count."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum node count."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum node count."
  type        = number
  default     = 6
}

variable "node_disk_size_gb" {
  description = "Per-node EBS disk size."
  type        = number
  default     = 50
}

variable "addon_versions" {
  description = "Pinned EKS add-on versions. `aws eks describe-addon-versions` for current."
  type = object({
    coredns    = string
    kube_proxy = string
    vpc_cni    = string
  })
  default = {
    coredns    = "v1.11.3-eksbuild.1"
    kube_proxy = "v1.30.3-eksbuild.5"
    vpc_cni    = "v1.18.3-eksbuild.2"
  }
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
