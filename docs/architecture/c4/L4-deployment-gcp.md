# C4 L4 — GCP Deployment (mirror)

How the L2 containers map onto GCP. Module names and topology mirror the AWS L4 diagram per ADR-0025.

```mermaid
C4Deployment
    title SentinelRAG — GCP Deployment (dev mirror)

    Deployment_Node(gcp, "GCP project", "us-central1") {

      Deployment_Node(vpc_gcp, "VPC 10.30.0.0/20 + secondary ranges", "Cloud NAT for egress; PSA peered for SQL+Memorystore") {

        Deployment_Node(gke, "GKE Standard 1.30", "e2-standard-4 × 1-3, private nodes, public master") {

          Deployment_Node(ns_sentinelrag, "Namespace: sentinelrag", "Helm release sentinelrag-dev (values-gcp-dev.yaml)") {
            Container(api_pod, "api Deployment", "FastAPI", "Workload Identity via iam.gke.io/gcp-service-account")
            Container(worker_pod, "temporal-worker Deployment", "Python", "Same chart; same workloads as AWS")
            Container(frontend_pod, "frontend Deployment", "Next.js standalone", "")
            Container(migrations_job, "migrations Job", "alembic upgrade head", "Helm pre-upgrade hook")
          }

          Deployment_Node(ns_temporal, "Namespace: temporal", "Helm: temporalio/temporal") {
            Container(temporal, "Temporal frontend / history / matching", "", "")
          }

          Deployment_Node(ns_keycloak, "Namespace: keycloak") { Container(kc, "Keycloak", "OIDC", "") }
          Deployment_Node(ns_eso, "Namespace: external-secrets") { Container(eso, "ESO", "Reads Secret Manager via WI", "ClusterSecretStore: sentinelrag-gcp-secrets") }
          Deployment_Node(ns_obs, "Namespace: observability") { Container(otel, "OTel + Tempo + Prom + Loki", "", "") }
        }

        Deployment_Node(psa, "Private Service Access peering", "Cloud SQL + Memorystore reach the cluster privately") {
          ContainerDb(cloudsql, "Cloud SQL Postgres 16", "db-custom-2-4096, ZONAL (dev) / REGIONAL (prod)", "pgvector + tsvector GIN")
          ContainerDb(memorystore, "Memorystore Redis 7.2", "BASIC tier 1 GB", "TLS in-transit + AUTH")
        }
      }

      Deployment_Node(gcs, "GCS (regional)") {
        ContainerDb(gcs_docs, "documents bucket", "Versioned, KMS-encrypted", "")
        ContainerDb(gcs_audit, "audit bucket", "Locked retention 7y", "ADR-0016")
      }

      Deployment_Node(sm, "Secret Manager") {
        Container(sec_api, "sentinelrag-dev-api", "JSON KV", "")
        Container(sec_worker, "sentinelrag-dev-temporal-worker", "JSON KV", "")
        Container(sec_frontend, "sentinelrag-dev-frontend", "JSON KV", "")
      }

      Deployment_Node(gce_lb, "GCE External HTTPS LB", "ManagedCertificate + global static IP") {
        Container(lb_api, "LB → api Service", "TLS via networking.gke.io/managed-certificates", "api.dev.sentinelrag.example.com")
        Container(lb_app, "LB → frontend Service", "TLS", "app.dev.sentinelrag.example.com")
      }
    }

    Rel(api_pod, cloudsql, "asyncpg via PSA private IP", "TCP 5432")
    Rel(api_pod, memorystore, "TLS+AUTH", "TCP 6379")
    Rel(api_pod, gcs_docs, "google-cloud-storage (WI)", "HTTPS")
    Rel(api_pod, gcs_audit, "google-cloud-storage (WI, write-only)", "HTTPS")
    Rel(api_pod, temporal, "Temporal SDK", "gRPC 7233")
    Rel(api_pod, kc, "JWKS", "HTTPS")
    Rel(api_pod, otel, "OTLP", "gRPC 4317")

    Rel(worker_pod, cloudsql, "asyncpg")
    Rel(worker_pod, gcs_docs, "google-cloud-storage (WI)")
    Rel(worker_pod, gcs_audit, "google-cloud-storage (WI, read for reconciliation)")
    Rel(worker_pod, temporal, "Pulls task queues")

    Rel(eso, sec_api, "Read (WI)")
    Rel(eso, api_pod, "Materializes K8s Secret")
```

## AWS↔GCP equivalence (the source of "same chart, two clouds")

| Function | AWS | GCP | Module |
|---|---|---|---|
| Identity (workload) | IRSA | Workload Identity | `iam` |
| K8s | EKS | GKE Standard | `eks` / `gke` |
| RDBMS | RDS Postgres 16 + pgvector | Cloud SQL Postgres 16 + pgvector | `rds` / `cloudsql` |
| Cache | ElastiCache Redis 7 | Memorystore Redis 7 | `elasticache` / `memorystore` |
| Object storage | S3 + Object Lock | GCS + locked retention | `s3` / `gcs` |
| Secrets | Secrets Manager | Secret Manager | `secrets` |
| Ingress | ALB Controller | GCE Ingress + ManagedCertificate | (Helm values diff only) |

Cross-cloud DR stance: **active-passive, manual DNS cut-over** (ADR-0028). Cross-cloud data replication is explicitly Phase 9-or-later work; the unreplicated lag window during a regional failover is disclosed up-front in the runbook.

## Related ADRs

- [ADR-0025](../adr/0025-gcp-parity.md) — GCP parity rules
- [ADR-0028](../adr/0028-disaster-recovery.md) — DR including AWS↔GCP failover procedure
