# IRSA roles bound to Kubernetes ServiceAccounts.
#
# Each role's trust policy says: "the OIDC provider can assume me for SA
# <namespace>/<sa-name>". The chart's values-{env}.yaml ServiceAccount
# annotations hand the ARN back to the workload via:
#   eks.amazonaws.com/role-arn: <these_role_arns>

locals {
  account_id = data.aws_caller_identity.current.account_id
  oidc_url   = var.oidc_provider_url           # e.g. oidc.eks.us-east-1.amazonaws.com/id/ABCDEF
  oidc_arn   = var.oidc_provider_arn

  api_sa_full        = "system:serviceaccount:${var.namespace}:${var.api_sa_name}"
  worker_sa_full     = "system:serviceaccount:${var.namespace}:${var.worker_sa_name}"
  frontend_sa_full   = "system:serviceaccount:${var.namespace}:${var.frontend_sa_name}"
  eso_sa_full        = "system:serviceaccount:${var.eso_namespace}:${var.eso_sa_name}"
}

data "aws_caller_identity" "current" {}

# --- Trust policy doc factory ---
data "aws_iam_policy_document" "trust_api" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = [local.api_sa_full]
    }
  }
}

data "aws_iam_policy_document" "trust_worker" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = [local.worker_sa_full]
    }
  }
}

data "aws_iam_policy_document" "trust_frontend" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = [local.frontend_sa_full]
    }
  }
}

data "aws_iam_policy_document" "trust_eso" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = [local.eso_sa_full]
    }
  }
}

# --- API role: read documents bucket, write audit, no Secrets Manager
#     (ESO holds those for it). ---
resource "aws_iam_role" "api" {
  name               = "${var.name_prefix}-api"
  assume_role_policy = data.aws_iam_policy_document.trust_api.json
  tags               = merge(var.tags, { Component = "api" })
}

data "aws_iam_policy_document" "api" {
  statement {
    sid    = "DocumentsReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetObjectVersion",
    ]
    resources = [
      var.documents_bucket_arn,
      "${var.documents_bucket_arn}/*",
    ]
  }
  statement {
    sid    = "AuditPutOnly"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:PutObjectRetention",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      var.audit_bucket_arn,
      "${var.audit_bucket_arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  name   = "${var.name_prefix}-api"
  policy = data.aws_iam_policy_document.api.json
}

# --- Worker role: same buckets as api + reconciliation list. ---
resource "aws_iam_role" "worker" {
  name               = "${var.name_prefix}-worker"
  assume_role_policy = data.aws_iam_policy_document.trust_worker.json
  tags               = merge(var.tags, { Component = "temporal-worker" })
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid    = "DocumentsReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetObjectVersion",
    ]
    resources = [
      var.documents_bucket_arn,
      "${var.documents_bucket_arn}/*",
    ]
  }
  statement {
    sid    = "AuditReadList"
    effect = "Allow"
    # Reconciliation activity needs to LIST + GET the audit bucket to
    # diff against Postgres rows. It does NOT delete (Object Lock would
    # block it anyway).
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
      "s3:GetObjectRetention",
    ]
    resources = [
      var.audit_bucket_arn,
      "${var.audit_bucket_arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "worker" {
  role   = aws_iam_role.worker.id
  name   = "${var.name_prefix}-worker"
  policy = data.aws_iam_policy_document.worker.json
}

# --- Frontend role: empty for now (NextAuth talks Keycloak only).
#     Created so the chart's IRSA annotation has somewhere to point. ---
resource "aws_iam_role" "frontend" {
  name               = "${var.name_prefix}-frontend"
  assume_role_policy = data.aws_iam_policy_document.trust_frontend.json
  tags               = merge(var.tags, { Component = "frontend" })
}

# --- ESO role: read all SentinelRAG Secrets Manager secrets. ---
resource "aws_iam_role" "eso" {
  name               = "${var.name_prefix}-eso"
  assume_role_policy = data.aws_iam_policy_document.trust_eso.json
  tags               = merge(var.tags, { Component = "external-secrets-operator" })
}

data "aws_iam_policy_document" "eso" {
  statement {
    sid    = "ReadSentinelragSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
      "secretsmanager:ListSecrets",
    ]
    resources = var.secret_arns
  }
}

resource "aws_iam_role_policy" "eso" {
  role   = aws_iam_role.eso.id
  name   = "${var.name_prefix}-eso"
  policy = data.aws_iam_policy_document.eso.json
}
