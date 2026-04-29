# Workload Identity bindings — the GCP equivalent of IRSA.
#
# For each workload, we create:
#   1. A Google service account (GSA).
#   2. An IAM binding letting the K8s service account (KSA) impersonate the
#      GSA via the cluster's Workload Identity pool.
#   3. The GSA's project-level / resource-level grants (GCS, Secret Manager).
#
# Helm values-gcp-dev.yaml then annotates the KSA with:
#   iam.gke.io/gcp-service-account: <gsa-email>

locals {
  ksa_member = {
    api      = "serviceAccount:${var.workload_identity_pool}[${var.namespace}/${var.api_sa_name}]"
    worker   = "serviceAccount:${var.workload_identity_pool}[${var.namespace}/${var.worker_sa_name}]"
    frontend = "serviceAccount:${var.workload_identity_pool}[${var.namespace}/${var.frontend_sa_name}]"
    eso      = "serviceAccount:${var.workload_identity_pool}[${var.eso_namespace}/${var.eso_sa_name}]"
  }
}

# --- Google Service Accounts ---
resource "google_service_account" "api" {
  account_id   = "${var.name_prefix}-api"
  project      = var.project_id
  display_name = "SentinelRAG api workload"
}

resource "google_service_account" "worker" {
  account_id   = "${var.name_prefix}-worker"
  project      = var.project_id
  display_name = "SentinelRAG temporal-worker workload"
}

resource "google_service_account" "frontend" {
  account_id   = "${var.name_prefix}-frontend"
  project      = var.project_id
  display_name = "SentinelRAG frontend workload"
}

resource "google_service_account" "eso" {
  account_id   = "${var.name_prefix}-eso"
  project      = var.project_id
  display_name = "External Secrets Operator"
}

# --- KSA → GSA impersonation bindings ---
resource "google_service_account_iam_member" "api_wi" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.ksa_member.api
}

resource "google_service_account_iam_member" "worker_wi" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.ksa_member.worker
}

resource "google_service_account_iam_member" "frontend_wi" {
  service_account_id = google_service_account.frontend.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.ksa_member.frontend
}

resource "google_service_account_iam_member" "eso_wi" {
  service_account_id = google_service_account.eso.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.ksa_member.eso
}

# --- GCS access for api + worker ---
resource "google_storage_bucket_iam_member" "api_documents" {
  bucket = var.documents_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_storage_bucket_iam_member" "api_audit_writer" {
  bucket = var.audit_bucket_name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_storage_bucket_iam_member" "worker_documents" {
  bucket = var.documents_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_storage_bucket_iam_member" "worker_audit_reader" {
  bucket = var.audit_bucket_name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.worker.email}"
}

# --- ESO access to all SentinelRAG Secret Manager secrets ---
resource "google_secret_manager_secret_iam_member" "eso_secret_accessor" {
  for_each  = toset(var.secret_names)
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.eso.email}"
}
