# Deploy SentinelRAG to a K3s Homelab

> End-to-end runbook for the scripts under `homelabsetup/`. Targets a
> 3-node K3s cluster on a private LAN (default 192.168.0.101–103). Adapt
> the env vars at the top of each script for a different layout.

## What you get

After a successful run you'll have:

- A K3s 3-node cluster (1 control-plane + 2 workers) pinned to `v1.34.6+k3s1`
- A local container registry at `registry.local:30500` (hostPath PV on node1)
- MetalLB serving LoadBalancer IPs from `192.168.0.200–220`
- Traefik (bundled with K3s) routing ingress for:
  - `http://app.sentinelrag.local`  — Next.js frontend
  - `http://api.sentinelrag.local`  — FastAPI API
  - `http://auth.sentinelrag.local` — Keycloak
- The full SentinelRAG application in the `sentinelrag` namespace:
  - `sentinelrag-api`, `sentinelrag-retrieval`, `sentinelrag-temporal-worker`, `sentinelrag-frontend`
  - In-cluster Postgres-16 + pgvector, Redis, MinIO, Keycloak, Unleash
  - Standalone Ollama (Llama 3.1 8B + `nomic-embed-text`)
- Temporal cluster in the `temporal` namespace (api + worker reach it at
  `temporal-frontend.temporal.svc.cluster.local:7233`)
- A seeded demo tenant (`admin@sentinelrag.local` / `Admin@2026!`)

## Prerequisites

**On the 3 nodes:**
- Linux (tested on Ubuntu 22.04 / 24.04)
- SSH access as a user with passwordless `sudo` (default user: `labadmin`)
- Open inbound TCP: `22, 6443, 30500, 80, 443` on node1; `22, 10250` on nodes 2+3
- Static LAN IPs (DHCP reservations are fine)
- ~16 GB RAM and ~50 GB disk on node1 (registry + Ollama models + Postgres),
  ~8 GB on nodes 2+3

**On the build host (your dev machine):**
- `kubectl`, `helm` ≥ 3.14, `docker` (Docker Desktop on Windows), `curl`, `sed`, `openssl`
- `sshpass` (optional — used as fallback when SSH key auth fails)
- `/etc/hosts` (or Windows `hosts` file) entries pointing the three
  `.sentinelrag.local` hostnames at the Traefik LoadBalancer IP. The
  deploy script prints the exact lines after the first install.
- Docker Desktop's `insecure-registries` list contains `registry.local:30500`
  (Settings → Docker Engine).

## Cheat sheet

```bash
# First time — full bootstrap + deploy in one go:
./homelabsetup/bootstrap-homelab.sh --deploy

# After the first time — just push new code:
export KUBECONFIG=$HOME/.kube/config-sentinelrag-homelab
./homelabsetup/deploy-homelab.sh

# Same thing, but reuse the last image build instead of rebuilding:
./homelabsetup/deploy-homelab.sh --skip-build --skip-models

# Rollout-restart all app pods (e.g. after a secret change):
./homelabsetup/restart-homelab.sh

# Scale everything to zero to save power overnight:
./homelabsetup/stop-homelab.sh
# ...and back up:
./homelabsetup/deploy-homelab.sh --skip-build --skip-models

# Helm-uninstall but keep the data:
./homelabsetup/cleanup-homelab.sh

# Nuke namespace + ALL data (asks for "yes" confirmation):
./homelabsetup/cleanup-homelab.sh --all

# Full reset of the application without touching K3s itself:
./homelabsetup/fresh-deploy-homelab.sh

# Re-install K3s on every node (interactive confirm):
./homelabsetup/bootstrap-homelab.sh --teardown
./homelabsetup/bootstrap-homelab.sh --deploy
```

## Step-by-step

### 1. One-time host-side setup

On the **build host**:

```bash
# Add the cluster hostnames to your hosts file. Replace 192.168.0.200
# with whatever Traefik picks (the deploy script will tell you).
sudo sh -c 'cat >> /etc/hosts <<EOF
192.168.0.101 registry.local
192.168.0.200 app.sentinelrag.local api.sentinelrag.local auth.sentinelrag.local
EOF'
```

Windows: edit `C:\Windows\System32\drivers\etc\hosts` as Administrator.

Docker Desktop → Settings → Docker Engine → add `registry.local:30500` to
`"insecure-registries"`. Apply & restart.

### 2. Bootstrap

```bash
./homelabsetup/bootstrap-homelab.sh
```

What happens:
1. SSH to each node (key first, password fallback)
2. `curl https://get.k3s.io | INSTALL_K3S_VERSION=v1.34.6+k3s1 ... sh -` on node1
3. `K3S_URL=https://node1:6443 ... sh -` on nodes 2+3
4. Write `~/.kube/config-sentinelrag-homelab` (127.0.0.1 → node1 IP)
5. Push `/etc/hosts` + `/etc/rancher/k3s/registries.yaml` to every node and
   restart K3s. **This is the step that prevents the "registry-images
   all ImagePullBackOff" failure mode** — without `registries.yaml`,
   containerd treats `registry.local:30500` as unknown and falls back to
   HTTPS, which fails.
6. Install MetalLB + IPAddressPool (`192.168.0.200-220`)
7. Deploy the in-cluster Docker registry as a hostPath PV on node1
8. `helm install temporal` in the `temporal` namespace
9. Apply the Ollama Deployment + PVC in the `sentinelrag` namespace

Pass `--teardown` to uninstall K3s from every node before re-running.

### 3. Deploy the application

```bash
export KUBECONFIG=$HOME/.kube/config-sentinelrag-homelab
./homelabsetup/deploy-homelab.sh
```

What happens:
1. Verifies `registry.local:30500` is reachable from the build host
2. Verifies `registries.yaml` is present on every K3s node (precheck — see
   pitfall below)
3. Builds the 4 service images (`sentinelrag-api`, `-retrieval-service`,
   `-temporal-worker`, `-frontend`) with an immutable tag
   `build-YYYYMMDD-HHMMSS`
4. Pushes them to the local registry
5. Creates the per-workload Kubernetes Secrets + the Keycloak realm
   ConfigMap
6. `helm dependency update` pulls Bitnami subcharts (Postgres, Redis, MinIO,
   Keycloak, Unleash)
7. `helm upgrade --install sentinelrag …` against `values-homelab.yaml`
   with the build tag substituted in
8. Runs an idempotent `CREATE EXTENSION vector` Job (defence in depth — the
   pgvector image initdb script handles first-boot, this Job covers
   already-initialized clusters)
9. `kubectl rollout restart` each app deployment to force a fresh image pull
10. Pulls `llama3.1:8b` + `nomic-embed-text` into the Ollama PVC
11. Prints the DNS hint with the current Traefik LoadBalancer IP
12. Runs `scripts/seed/seed_demo.py` inside the API pod to create the demo
    tenant + admin user

Saves credentials to `homelabsetup/.homelab-credentials` (gitignored — do
NOT commit).

## Footguns / Pitfalls

### "Every pod is in ImagePullBackOff"

The most common failure on first install. K3s ships containerd, not Docker,
and containerd has its own registry-mirror config at
`/etc/rancher/k3s/registries.yaml`. Without that file, `registry.local:30500`
is treated as an unknown registry and containerd tries HTTPS → fails →
backoff.

The bootstrap script writes this file on every node automatically. If you
ever see `ImagePullBackOff`, run `./homelabsetup/bootstrap-homelab.sh
--skip-prereqs` to re-apply it.

The deploy script has a pre-apply guard that uses `kubectl debug node/`
to verify the file exists. Pass `--skip-mirror-check` to bypass (not
recommended).

### "The frontend talks to api.sentinelrag.local but auth.sentinelrag.local fails"

You added two of the three hostnames to `/etc/hosts` and forgot the third.
The deploy script's DNS hint prints all three; copy all of them.

### "I rotated my AWS key and now homelab login is broken"

Wrong project — this homelab path has no AWS dependency. Run
`./homelabsetup/restart-homelab.sh` if Keycloak gets confused, or
`./homelabsetup/fresh-deploy-homelab.sh` if you need a clean slate.

### "Ollama keeps crashing — out of memory"

`llama3.1:8b` needs ~5 GB RAM in addition to whatever the Ollama runtime
consumes. The Ollama Deployment in `bootstrap-homelab.sh` requests 1 GB
and limits to 8 GB. If your node is tight, switch to a smaller model:
`kubectl -n sentinelrag exec deploy/ollama -- ollama pull llama3.2:3b`,
then update `DEFAULT_GENERATION_MODEL` in `values-homelab.yaml`.

### "After cleanup --all, registry shows ImagePullBackOff on next deploy"

`cleanup-homelab.sh --all` deletes the `sentinelrag` namespace but leaves
the registry running. The PVC the registry uses is in its own `registry`
namespace and survives. Images you built before the cleanup are still
there. To wipe the registry too, use `cleanup-homelab.sh --everything`.

### "Helm refuses to upgrade — schema validation error"

Most often this means you changed a field type in `values-homelab.yaml`
(e.g. string → list). Run `helm template sentinelrag ./infra/helm/sentinelrag
-f values-homelab.yaml` locally to see the diff. If you've added a new
Bitnami subchart, you need a `helm dependency update` first (deploy script
does this automatically).

## What's not covered (yet)

These deliberate deferrals from the v1 homelab scope:

- **Observability stack.** No Tempo, Loki, Grafana — `kubectl logs` is
  the demo. SDK `OTEL_EXPORTER_OTLP_ENDPOINT` points at a nonexistent
  service; the SDK noops silently. Bolt on later as a separate
  `observability` namespace.
- **HTTPS.** Ingress is HTTP-only. cert-manager is not installed. Add
  for production use; the homelab demo doesn't need it.
- **OpenSearch.** Disabled per ADR-0026 — Postgres FTS is the always-on
  default keyword backend.
- **ArgoCD GitOps.** The chart was designed for ArgoCD (cloud path) but
  the homelab installs via plain `helm upgrade --install`. Adding ArgoCD
  to the homelab is a future exercise.
- **Multi-cloud parity tests.** The cloud cells (AWS / GCP) are still
  the canonical "production" path; the homelab is portfolio-grade
  proof that the chart works on bare metal.

## Where to read deeper

- Chart source: `infra/helm/sentinelrag/`
- ADR-0012 (Helm + ArgoCD GitOps): `docs/architecture/adr/0012-helm-argocd-gitops.md`
- ADR-0023 (Helm chart shape): `docs/architecture/adr/0023-helm-chart-shape.md`
- ADR-0030 (bootstrap charts split): `docs/architecture/adr/0030-bootstrap-charts-split.md`
- Cluster bootstrap runbook (cloud-side, related): `docs/operations/runbooks/cluster-bootstrap.md`
