# C4 L4 — AWS Deployment

How the L2 containers map onto a real AWS environment provisioned by `infra/terraform/aws/` and deployed by `infra/helm/sentinelrag/`.

```mermaid
C4Deployment
    title SentinelRAG — AWS Deployment (dev)

    Deployment_Node(aws, "AWS account", "us-east-1") {

      Deployment_Node(vpc, "VPC 10.20.0.0/16", "3 AZ public + 3 AZ private; single NAT for dev") {

        Deployment_Node(eks, "EKS 1.30 cluster", "Managed node group t3.large × 2-6") {

          Deployment_Node(ns_sentinelrag, "Namespace: sentinelrag", "Helm release sentinelrag-dev") {
            Container(api_pod, "api Deployment", "FastAPI", "HPA 2-10, PDB minAvailable=2, IRSA via eks.amazonaws.com/role-arn")
            Container(worker_pod, "temporal-worker Deployment", "Python", "3 task queues; ingestion + evaluation + audit")
            Container(frontend_pod, "frontend Deployment", "Next.js standalone", "HPA 2-6, PDB minAvailable=1")
            Container(migrations_job, "migrations Job", "alembic upgrade head", "Helm pre-upgrade hook")
          }

          Deployment_Node(ns_temporal, "Namespace: temporal", "Helm: temporalio/temporal") {
            Container(temporal_frontend, "temporal-frontend", "gRPC :7233", "")
            Container(temporal_history, "temporal-history", "", "")
            Container(temporal_matching, "temporal-matching", "", "")
          }

          Deployment_Node(ns_keycloak, "Namespace: keycloak", "Helm: bitnami/keycloak") {
            Container(keycloak, "Keycloak", "OIDC / OAuth2", "Realm: sentinelrag")
          }

          Deployment_Node(ns_eso, "Namespace: external-secrets", "Helm: external-secrets") {
            Container(eso, "External Secrets Operator", "Materializes secrets via IRSA", "ClusterSecretStore: sentinelrag-aws-secrets")
          }

          Deployment_Node(ns_obs, "Namespace: observability", "Helm: opentelemetry-operator + Tempo + Prom + Loki") {
            Container(otel_collector, "otel-collector", "OTLP gRPC / HTTP", "")
            ContainerDb(tempo, "Tempo", "Traces", "")
            ContainerDb(prom, "Prometheus", "Metrics", "")
            ContainerDb(loki, "Loki", "Logs", "")
          }

          Deployment_Node(ns_chaos, "Namespace: chaos-mesh + sentinelrag-chaos", "Helm: chaos-mesh + game-day Workflow") {
            Container(chaos_mgr, "Chaos Mesh controllers", "", "Phase 8 Slice 3")
          }
        }

        Deployment_Node(rds_subnet, "Private subnets — data plane") {
          ContainerDb(rds, "RDS Postgres 16.4", "db.t4g.medium, gp3 50→200 GB", "pgvector + tsvector GIN; HNSW indexes; RLS policies")
          ContainerDb(elasticache, "ElastiCache Redis 7.1", "cache.t4g.small", "TLS in-transit + AUTH")
          ContainerDb(opensearch_domain, "OpenSearch 2.13", "t3.small.search × 2 (Phase 8 reintroduction)", "Private VPC; fine-grained access")
        }
      }

      Deployment_Node(s3, "S3 (regional)") {
        ContainerDb(s3_docs, "documents bucket", "Versioned, KMS-encrypted", "")
        ContainerDb(s3_audit, "audit bucket", "Object Lock COMPLIANCE 7y", "ADR-0016")
      }

      Deployment_Node(secrets_mgr, "Secrets Manager") {
        Container(secret_api, "sentinelrag-dev/api", "JSON KV", "")
        Container(secret_worker, "sentinelrag-dev/temporal-worker", "JSON KV", "")
        Container(secret_frontend, "sentinelrag-dev/frontend", "JSON KV", "")
      }

      Deployment_Node(alb, "AWS Load Balancer Controller", "External-facing ALB targets") {
        Container(alb_api, "ALB → api Service", "ACM TLS", "api.dev.sentinelrag.example.com")
        Container(alb_app, "ALB → frontend Service", "ACM TLS", "app.dev.sentinelrag.example.com")
      }
    }

    Deployment_Node(github, "GitHub") {
      Container(ghcr, "GHCR", "Image registry", "ghcr.io/anandtopu/sentinelrag-{api,temporal-worker,frontend}")
      Container(actions, "Actions CI", "tfsec, bandit, trivy, perf-smoke, dr-backup-verify", "Phase 8 Slice 4 + 5")
    }

    Deployment_Node(argocd, "ArgoCD (in-cluster)", "Phase 7 Slice 3 — pending") {
      Container(argocd_app, "Application: sentinelrag-dev", "syncs from infra/helm/sentinelrag", "")
    }

    Rel(api_pod, rds, "asyncpg over private subnet", "TCP 5432")
    Rel(api_pod, elasticache, "TLS+AUTH", "TCP 6379")
    Rel(api_pod, opensearch_domain, "HTTPS", "TCP 443")
    Rel(api_pod, s3_docs, "boto3 (IRSA)", "HTTPS")
    Rel(api_pod, s3_audit, "boto3 (IRSA, write-only)", "HTTPS")
    Rel(api_pod, temporal_frontend, "Temporal SDK", "gRPC 7233")
    Rel(api_pod, keycloak, "JWKS", "HTTPS")
    Rel(api_pod, otel_collector, "OTLP", "gRPC 4317")

    Rel(worker_pod, rds, "asyncpg")
    Rel(worker_pod, s3_docs, "boto3 (IRSA)")
    Rel(worker_pod, s3_audit, "boto3 (IRSA, read for reconciliation)")
    Rel(worker_pod, opensearch_domain, "Bulk-index + delete")
    Rel(worker_pod, temporal_frontend, "Pulls task queues")

    Rel(eso, secret_api, "GetSecretValue (IRSA)")
    Rel(eso, api_pod, "Materializes K8s Secret")
    Rel(actions, ghcr, "Push tagged images")
    Rel(argocd_app, ghcr, "Image Updater watches tags")
```

## What Terraform owns vs what Helm owns

| Layer | Tool | Examples |
|---|---|---|
| Account-level | Terraform | VPC, EKS cluster + node group, OIDC provider, RDS, ElastiCache, OpenSearch, S3 buckets, Secrets Manager parents, IRSA roles, ACM certs |
| Cluster-level | Helm (separate releases) | Chaos Mesh, External Secrets Operator, ArgoCD, Temporal, Keycloak, AWS Load Balancer Controller, cert-manager, OTel + Tempo + Prom + Loki |
| Application-level | Helm (sentinelrag chart) | api / worker / frontend Deployments + SAs + ConfigMaps + Services + Ingresses + HPA + PDB + NetworkPolicies + ExternalSecret + migrations Job |

**Boundary rule:** account-level resources are Terraform, anything inside the cluster is Helm. The boundary is explicit so a `terraform destroy` cannot wipe ArgoCD's state, and a `helm uninstall` cannot delete the audit bucket.

## Phase status note

The cluster bootstrap charts (Chaos Mesh, ESO, ArgoCD, Temporal, ALB controller, cert-manager) are listed because they are required for the diagram to be true; their installation is **Phase 7 Slice 3**, currently pending. The SentinelRAG chart and Terraform are both shipped and clean.

## Related ADRs

- [ADR-0011](../adr/0011-multi-cloud-strategy.md) — AWS primary, GCP mirror
- [ADR-0012](../adr/0012-helm-argocd-deployment.md) — Helm + ArgoCD
- [ADR-0023](../adr/0023-helm-chart-shape.md) — Helm chart shape
- [ADR-0024](../adr/0024-terraform-layout.md) — Terraform layout
- [ADR-0028](../adr/0028-disaster-recovery.md) — DR; the failover target diagram is `L4-deployment-gcp.md`
