# Session handoff — 2026-05-17: deploy track started; tooling installed, AWS pre-flight queued

> Purpose: capture the in-flight state at session end so the next session
> opens at the right step. References the
> [remediation plan](../REMEDIATION_PLAN.md), the
> [R4.S6 scaffold handoff](2026-05-17-r4s6-scaffold.md), and the
> [AWS deployment runbook](../../operations/runbooks/deployment-aws.md).

## Where we are

The R-stream is structurally closed (see
[`handoff/2026-05-17-r4s6-scaffold.md`](2026-05-17-r4s6-scaffold.md)).
The user picked **Option 1 — first live deploy on AWS** as the next
backlog item. The session ended after tool installation but before any
`terraform` or `aws` command ran against a real account.

No code changes this session; nothing to commit. This handoff is the
artifact.

## Tooling state on the user's Windows host

| Tool | Status |
|---|---|
| `terraform` | ✅ Installed via Chocolatey, **v1.15.3** (well above the runbook's ≥ 1.7 requirement) |
| `aws` CLI | ✅ Installed via Chocolatey, **v2.34.48**, but PATH not refreshed in the install shell. User was told to `refreshenv` (PowerShell) or close+reopen the terminal, or prepend `C:\Program Files\Amazon\AWSCLIV2` to PATH for the current session. |
| `kubectl` | ✅ Already present (Rancher Desktop) |
| `helm` | ✅ Already present (Rancher Desktop) |
| `jq` | ❓ Not verified this session — runbook step 2 uses it for `terraform output -json`; add to the pre-flight check next session. |

## Outstanding before any `terraform apply`

The user still needs to do (out of my reach):

1. **Verify the AWS CLI is on PATH** in a fresh shell — `aws --version`
   should print `aws-cli/2.34.48 ...`.
2. **`aws configure`** against an IAM user with **admin scope** (the
   runbook downscopes to per-workload IRSA roles for day-2; admin is
   only needed for initial provisioning).
3. **`aws sts get-caller-identity`** — must return the account ID.
4. **A domain** the user controls DNS for (the chart's ingress + ACM
   cert validation hangs on this).
5. **At least one GHCR image tag published** by the
   `.github/workflows/build-images.yml` pipeline — the Helm chart's
   `image.tag` needs a real value, not the `:dev` placeholder.
6. **Cost acceptance** — the runbook documents ~$200–300/mo idle for
   the dev defaults (EKS + RDS + ElastiCache + NAT).

## What I committed to next session

A **review-only walkthrough** before the user fires `terraform apply`.
No cloud spend in this pass — just paper + dry-run:

1. Read `infra/terraform/aws/{environments/dev,modules}` end-to-end;
   verify the resources line up with the runbook's "Architecture this
   provisions" list (VPC + EKS + RDS + ElastiCache + S3 + Secrets
   Manager + IRSA roles).
2. Diff `terraform.tfvars.example` against what the runbook tells the
   user to fill in.
3. **Critical:** Walk the Helm chart values against the runbook's
   `--set` and value-file commands. **R4 added the `retrieval` workload
   plus `RETRIEVAL_TRANSPORT` + `RETRIEVAL_SERVICE_URL` +
   `RETRIEVAL_SERVICE_TIMEOUT_SECONDS` to `api.envFromConfigMap` and
   `RETRIEVAL_SERVICE_TOKEN` to `api.envFromSecret.remoteKeys`.**
   The deployment-aws.md runbook predates this and likely does not
   mention seeding the `RETRIEVAL_SERVICE_TOKEN` in Secrets Manager.
   The R6 startup guard
   (`apps/api/app/lifecycle.py::_build_retrieval_client`) will refuse
   to start the API pod if the chart sees `RETRIEVAL_TRANSPORT=http`
   but the token is empty — so an unpatched runbook will trip on this
   on first deploy. Surface this in the pre-flight report.
4. **Also check:** does the deployment-aws.md runbook account for the
   new `retrieval` SecretsManager path
   (`sentinelrag-dev/retrieval/{DATABASE_URL,SERVICE_TOKEN}`) that the
   chart's `retrieval/externalsecret.yaml` reads? If not, add a
   `sentinelrag-dev/retrieval` secret-creation step.
5. Produce a **pre-flight checklist + drift report** so when the user
   actually runs `terraform apply` + `helm upgrade --install`, every
   command is known-good and the secrets-side surprises are caught in
   advance.

## How to resume

1. Open a fresh PowerShell or Git Bash window so the PATH refresh has
   taken effect.
2. Verify the trio:
   ```bash
   terraform -version            # expect >= 1.7
   aws --version                 # expect 2.34.x
   aws sts get-caller-identity   # expect your account ID returned
   ```
3. Tell the next session: "tools installed, account is <id>, region
   us-east-1, ready for the review-only walkthrough."
4. The walkthrough produces a markdown checklist + drift report. You
   read it, decide on go/no-go, then YOU run `terraform apply` against
   your account. The assistant does not.

## Why no commit this session

The conversation since `27b8e28` was planning + your local CLI install
+ a PATH-refresh diagnosis. No file in the repo changed. The next
session will produce real artifacts (the pre-flight checklist, plus
potentially a chart-vs-runbook drift patch for `deployment-aws.md`),
and those land as their own commit at that point.

## References

- [Deployment runbook (AWS)](../../operations/runbooks/deployment-aws.md)
- [Cluster bootstrap runbook](../../operations/runbooks/cluster-bootstrap.md)
- [ADR-0011](../adr/0011-multi-cloud-strategy.md) — AWS primary, GCP mirror
- [ADR-0023](../adr/0023-helm-chart-shape.md) — chart shape this deploy
  uses
- [ADR-0031](../adr/0031-retrieval-service-extraction.md) — the new
  retrieval workload the runbook needs to be patched for
- Previous handoffs:
  [R4.S6 scaffold](2026-05-17-r4s6-scaffold.md),
  [R6 complete](2026-05-17-r6-complete.md),
  [R5 complete](2026-05-17-r5-complete.md)
