# Remote state in GCS — bucket + uniform-bucket-level-access bootstrapped
# manually before `terraform init`. Object Versioning ON for safety.

terraform {
  backend "gcs" {
    # Override at init: terraform init -backend-config="bucket=sentinelrag-tfstate-<project>"
    bucket = "sentinelrag-tfstate-PLACEHOLDER"
    prefix = "gcp/dev"
  }
}
