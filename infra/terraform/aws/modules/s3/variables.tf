variable "name" {
  description = "Name prefix for buckets (e.g. 'sentinelrag-dev')."
  type        = string
}

variable "kms_key_id" {
  description = "KMS key ARN for SSE-KMS (null = AWS-managed S3 key)."
  type        = string
  default     = null
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete the documents bucket even when populated. Audit bucket is never force-destroyed."
  type        = bool
  default     = false
}

variable "audit_lock_mode" {
  description = "Object Lock mode for audit bucket. COMPLIANCE = immutable even for root."
  type        = string
  default     = "COMPLIANCE"
  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.audit_lock_mode)
    error_message = "audit_lock_mode must be GOVERNANCE or COMPLIANCE."
  }
}

variable "audit_retention_years" {
  description = "Years of Object Lock retention applied to every audit object."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
