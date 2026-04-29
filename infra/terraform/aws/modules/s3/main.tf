# Two S3 buckets:
#   - documents : versioned, server-side encrypted, lifecycle moves old
#                 versions to IA after 30d.
#   - audit     : Object Lock in COMPLIANCE mode (immutable). Backs the
#                 audit dual-write described in ADR-0016.
#
# Object Lock REQUIRES the bucket to be created with object_lock_enabled
# already set — you cannot enable it after the fact. We bake that in here
# instead of relying on a flag.

# --- Documents bucket ---
resource "aws_s3_bucket" "documents" {
  bucket        = "${var.name}-documents"
  force_destroy = var.force_destroy
  tags          = merge(var.tags, { Name = "${var.name}-documents", Purpose = "documents" })
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_id
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }
    noncurrent_version_expiration {
      noncurrent_days = 365
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# --- Audit bucket (Object Lock) ---
resource "aws_s3_bucket" "audit" {
  bucket              = "${var.name}-audit"
  force_destroy       = false # NEVER true — audit is meant to be immutable.
  object_lock_enabled = true
  tags                = merge(var.tags, { Name = "${var.name}-audit", Purpose = "audit" })
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode  = var.audit_lock_mode
      years = var.audit_retention_years
    }
  }
  depends_on = [aws_s3_bucket_versioning.audit]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_id
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Audit bucket policy: block any DeleteObjectVersion outside the retention
# window from non-admin principals. Object Lock already enforces this for
# the data, but the explicit deny prevents accidental privileges escalation
# from making it appear deletable.
resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
      {
        Sid       = "DenyVersionedDelete"
        Effect    = "Deny"
        Principal = "*"
        Action    = ["s3:DeleteObjectVersion", "s3:DeleteBucket"]
        Resource  = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
      },
    ]
  })
}
