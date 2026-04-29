# Secret Manager — one secret per workload, KV materialized as a JSON value
# (matches the AWS Secrets Manager shape for cross-cloud parity).
#
# Each secret has one initial version; rotation is manual via the GCP console
# and `lifecycle.ignore_changes` keeps `terraform apply` from clobbering.

resource "google_secret_manager_secret" "api" {
  secret_id = "${var.release}-api"
  project   = var.project_id
  labels    = merge(var.labels, { component = "api" })

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "api" {
  secret      = google_secret_manager_secret.api.id
  secret_data = jsonencode(var.api_secrets)

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "worker" {
  secret_id = "${var.release}-temporal-worker"
  project   = var.project_id
  labels    = merge(var.labels, { component = "temporal-worker" })

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "worker" {
  secret      = google_secret_manager_secret.worker.id
  secret_data = jsonencode(var.worker_secrets)

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "frontend" {
  secret_id = "${var.release}-frontend"
  project   = var.project_id
  labels    = merge(var.labels, { component = "frontend" })

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "frontend" {
  secret      = google_secret_manager_secret.frontend.id
  secret_data = jsonencode(var.frontend_secrets)

  lifecycle {
    ignore_changes = [secret_data]
  }
}
