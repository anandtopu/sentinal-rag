# SentinelRAG dev environment on AWS.
# Wires the modules under ../../modules/ together.
#
# Apply order is enforced by Terraform's dep graph; explicit `depends_on`
# is only used where AWS ordering is subtle (audit bucket policy after
# Object Lock).

locals {
  common_tags = {
    Project     = "SentinelRAG"
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}

# --- VPC ---
module "vpc" {
  source = "../../modules/vpc"

  name               = var.name_prefix
  cidr_block         = var.vpc_cidr
  cluster_name       = var.name_prefix
  single_nat_gateway = true       # dev cost saver
  enable_flow_logs   = true
  tags               = local.common_tags
}

# --- EKS ---
module "eks" {
  source = "../../modules/eks"

  name                = var.name_prefix
  kubernetes_version  = var.kubernetes_version
  private_subnet_ids  = module.vpc.private_subnet_ids
  public_subnet_ids   = module.vpc.public_subnet_ids
  node_instance_types = var.node_instance_types
  node_desired_size   = 2
  node_min_size       = 2
  node_max_size       = 6
  tags                = local.common_tags
}

# --- RDS Postgres + pgvector ---
module "rds" {
  source = "../../modules/rds"

  name                     = var.name_prefix
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  client_security_group_id = module.eks.node_security_group_id

  instance_class           = var.rds_instance_class
  multi_az                 = false # dev
  master_password          = var.rds_master_password
  deletion_protection      = false # dev
  skip_final_snapshot      = true  # dev

  tags = local.common_tags
}

# --- ElastiCache Redis ---
module "redis" {
  source = "../../modules/elasticache"

  name                     = var.name_prefix
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  client_security_group_id = module.eks.node_security_group_id

  node_type   = var.redis_node_type
  auth_token  = var.redis_auth_token

  tags = local.common_tags
}

# --- S3 buckets ---
module "s3" {
  source = "../../modules/s3"

  name                  = var.name_prefix
  audit_lock_mode       = "COMPLIANCE"
  audit_retention_years = 7
  force_destroy         = false

  tags = local.common_tags
}

# --- Secrets Manager (placeholder values; rotated post-apply) ---
module "secrets" {
  source = "../../modules/secrets"

  release = var.name_prefix
  api_secrets = {
    DATABASE_URL              = "postgresql+asyncpg://${module.rds.username}:${var.rds_master_password}@${module.rds.endpoint}:${module.rds.port}/${module.rds.database_name}"
    REDIS_URL                 = "rediss://:${var.redis_auth_token}@${module.redis.primary_endpoint}:${module.redis.port}/0"
    KEYCLOAK_ISSUER_URL       = "https://auth.dev.sentinelrag.example.com/realms/sentinelrag"
    KEYCLOAK_AUDIENCE         = "sentinelrag-api"
    KEYCLOAK_JWKS_URL         = "https://auth.dev.sentinelrag.example.com/realms/sentinelrag/protocol/openid-connect/certs"
    OBJECT_STORAGE_ACCESS_KEY = "" # IRSA; left empty so app prefers the role
    OBJECT_STORAGE_SECRET_KEY = ""
    UNLEASH_API_TOKEN         = "PLACEHOLDER_ROTATE_ME"
  }
  worker_secrets = {
    DATABASE_URL              = "postgresql+asyncpg://${module.rds.username}:${var.rds_master_password}@${module.rds.endpoint}:${module.rds.port}/${module.rds.database_name}"
    REDIS_URL                 = "rediss://:${var.redis_auth_token}@${module.redis.primary_endpoint}:${module.redis.port}/0"
    OBJECT_STORAGE_ACCESS_KEY = ""
    OBJECT_STORAGE_SECRET_KEY = ""
  }
  frontend_secrets = {
    NEXTAUTH_SECRET        = "PLACEHOLDER_ROTATE_ME"
    KEYCLOAK_CLIENT_ID     = "sentinelrag-frontend"
    KEYCLOAK_CLIENT_SECRET = "PLACEHOLDER_ROTATE_ME"
  }

  tags = local.common_tags
}

# --- IRSA roles ---
module "iam" {
  source = "../../modules/iam"

  name_prefix       = var.name_prefix
  oidc_provider_url = module.eks.oidc_provider_url
  oidc_provider_arn = module.eks.oidc_provider_arn

  namespace         = var.k8s_namespace
  api_sa_name       = "${var.name_prefix}-sentinelrag-api"
  worker_sa_name    = "${var.name_prefix}-sentinelrag-temporal-worker"
  frontend_sa_name  = "${var.name_prefix}-sentinelrag-frontend"

  documents_bucket_arn = module.s3.documents_bucket_arn
  audit_bucket_arn     = module.s3.audit_bucket_arn
  secret_arns          = module.secrets.all_secret_arns

  tags = local.common_tags
}
