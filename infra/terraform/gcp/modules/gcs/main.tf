# GCS buckets — documents (versioned) + audit (retention policy LOCKED).
#
# GCS retention policies are the GCP equivalent of S3 Object Lock COMPLIANCE
# mode: once locked, objects cannot be deleted before retention expires —
# not even by project owners. This implements ADR-0016's audit immutability
# guarantee on GCP.

# --- Documents bucket ---
resource "google_storage_bucket" "documents" {
  name          = "${var.name}-documents"
  project       = var.project_id
  location      = var.region
  force_destroy = var.force_destroy

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = var.kms_key_name
  }

  lifecycle_rule {
    condition {
      age                = 30
      with_state         = "ARCHIVED" # noncurrent versions
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age        = 365
      with_state = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = merge(var.labels, { purpose = "documents" })
}

# --- Audit bucket ---
resource "google_storage_bucket" "audit" {
  name          = "${var.name}-audit"
  project       = var.project_id
  location      = var.region
  force_destroy = false # never true for audit

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  retention_policy {
    is_locked        = var.audit_lock_retention
    retention_period = var.audit_retention_seconds
  }

  encryption {
    default_kms_key_name = var.kms_key_name
  }

  labels = merge(var.labels, { purpose = "audit" })
}
