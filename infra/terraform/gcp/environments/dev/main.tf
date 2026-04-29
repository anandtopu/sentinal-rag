# SentinelRAG dev environment on GCP — mirror of the AWS dev environment.
# Helm chart and values overlays are unchanged across clouds; only the
# Terraform inputs differ.

locals {
  common_labels = {
    project     = "sentinelrag"
    environment = "dev"
    managed_by  = "terraform"
  }
}

# Per-cluster service account for nodes (registry pull only).
resource "google_service_account" "node" {
  account_id   = "${var.name_prefix}-node"
  project      = var.project_id
  display_name = "SentinelRAG node SA"
}

resource "google_project_iam_member" "node_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.node.email}"
}

resource "google_project_iam_member" "node_logwriter" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.node.email}"
}

resource "google_project_iam_member" "node_metricwriter" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.node.email}"
}

# --- VPC ---
module "vpc" {
  source = "../../modules/vpc"

  name       = var.name_prefix
  project_id = var.project_id
  region     = var.region
}

# --- GKE ---
module "gke" {
  source = "../../modules/gke"

  name       = var.name_prefix
  project_id = var.project_id
  region     = var.region

  network_id          = module.vpc.network_id
  subnet_id           = module.vpc.subnet_id
  pods_range_name     = module.vpc.pods_range_name
  services_range_name = module.vpc.services_range_name

  node_service_account = google_service_account.node.email
  deletion_protection  = false  # dev

  labels = local.common_labels
}

# --- Cloud SQL Postgres + pgvector ---
module "cloudsql" {
  source = "../../modules/cloudsql"

  name       = var.name_prefix
  project_id = var.project_id
  region     = var.region

  network_id                        = module.vpc.network_id
  private_service_access_dependency = module.vpc.private_service_access_connection

  availability_type   = "ZONAL"  # dev
  master_password     = var.cloudsql_master_password
  deletion_protection = false    # dev

  labels = local.common_labels
}

# --- Memorystore Redis ---
module "redis" {
  source = "../../modules/memorystore"

  name       = var.name_prefix
  project_id = var.project_id
  region     = var.region

  network_id     = module.vpc.network_id
  tier           = "BASIC"
  memory_size_gb = 1

  labels = local.common_labels
}

# --- GCS buckets ---
module "gcs" {
  source = "../../modules/gcs"

  name       = var.name_prefix
  project_id = var.project_id
  region     = var.region

  audit_lock_retention = false  # dev — lock retention ON in prod overlay
  force_destroy        = false

  labels = local.common_labels
}

# --- Secret Manager ---
module "secrets" {
  source = "../../modules/secrets"

  release    = var.name_prefix
  project_id = var.project_id

  api_secrets = {
    # Cloud SQL connections from K8s use the private IP directly when both
    # are peered through PSA (no auth proxy needed for the dev path).
    DATABASE_URL              = "postgresql+asyncpg://${module.cloudsql.username}:${var.cloudsql_master_password}@${module.cloudsql.private_ip}:5432/${module.cloudsql.database_name}"
    REDIS_URL                 = "rediss://:CHANGE_ME@${module.redis.host}:${module.redis.port}/0"
    KEYCLOAK_ISSUER_URL       = "https://auth.dev.sentinelrag.example.com/realms/sentinelrag"
    KEYCLOAK_AUDIENCE         = "sentinelrag-api"
    KEYCLOAK_JWKS_URL         = "https://auth.dev.sentinelrag.example.com/realms/sentinelrag/protocol/openid-connect/certs"
    OBJECT_STORAGE_ACCESS_KEY = ""  # WI-bound; SDK uses metadata server
    OBJECT_STORAGE_SECRET_KEY = ""
    UNLEASH_API_TOKEN         = "PLACEHOLDER_ROTATE_ME"
  }
  worker_secrets = {
    DATABASE_URL              = "postgresql+asyncpg://${module.cloudsql.username}:${var.cloudsql_master_password}@${module.cloudsql.private_ip}:5432/${module.cloudsql.database_name}"
    REDIS_URL                 = "rediss://:CHANGE_ME@${module.redis.host}:${module.redis.port}/0"
    OBJECT_STORAGE_ACCESS_KEY = ""
    OBJECT_STORAGE_SECRET_KEY = ""
  }
  frontend_secrets = {
    NEXTAUTH_SECRET        = "PLACEHOLDER_ROTATE_ME"
    KEYCLOAK_CLIENT_ID     = "sentinelrag-frontend"
    KEYCLOAK_CLIENT_SECRET = "PLACEHOLDER_ROTATE_ME"
  }

  labels = local.common_labels
}

# --- Workload Identity bindings ---
module "iam" {
  source = "../../modules/iam"

  name_prefix            = var.name_prefix
  project_id             = var.project_id
  workload_identity_pool = module.gke.workload_identity_pool
  namespace              = var.k8s_namespace

  api_sa_name      = "${var.name_prefix}-sentinelrag-api"
  worker_sa_name   = "${var.name_prefix}-sentinelrag-temporal-worker"
  frontend_sa_name = "${var.name_prefix}-sentinelrag-frontend"

  documents_bucket_name = module.gcs.documents_bucket_name
  audit_bucket_name     = module.gcs.audit_bucket_name
  secret_names          = module.secrets.all_secret_names
}
