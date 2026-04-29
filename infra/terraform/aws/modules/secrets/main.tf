# Secrets Manager parent secret per workload component.
#
# Convention (matches the chart's ExternalSecret remoteRef):
#   {release}/{component}/{KEY}  →  one Secrets Manager secret per release.
#
# Each release+component lives in its own SecretsManager secret carrying a
# JSON map of KEY → value. ExternalSecretsOperator pulls them via
# AWS Secrets Manager → ClusterSecretStore.

resource "aws_secretsmanager_secret" "api" {
  name                    = "${var.release}/api"
  description             = "SentinelRAG API runtime secrets (DSN, JWKS URL, S3 keys, Unleash token)."
  recovery_window_in_days = var.recovery_window_in_days
  kms_key_id              = var.kms_key_id
  tags                    = merge(var.tags, { Component = "api" })
}

resource "aws_secretsmanager_secret_version" "api" {
  secret_id     = aws_secretsmanager_secret.api.id
  secret_string = jsonencode(var.api_secrets)

  lifecycle {
    # Operators rotate values manually via the AWS console / CLI; do not
    # let terraform clobber rotated values on a stale apply.
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "worker" {
  name                    = "${var.release}/temporal-worker"
  description             = "Temporal worker runtime secrets."
  recovery_window_in_days = var.recovery_window_in_days
  kms_key_id              = var.kms_key_id
  tags                    = merge(var.tags, { Component = "temporal-worker" })
}

resource "aws_secretsmanager_secret_version" "worker" {
  secret_id     = aws_secretsmanager_secret.worker.id
  secret_string = jsonencode(var.worker_secrets)

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "frontend" {
  name                    = "${var.release}/frontend"
  description             = "Frontend runtime secrets (NextAuth, Keycloak client)."
  recovery_window_in_days = var.recovery_window_in_days
  kms_key_id              = var.kms_key_id
  tags                    = merge(var.tags, { Component = "frontend" })
}

resource "aws_secretsmanager_secret_version" "frontend" {
  secret_id     = aws_secretsmanager_secret.frontend.id
  secret_string = jsonencode(var.frontend_secrets)

  lifecycle {
    ignore_changes = [secret_string]
  }
}
