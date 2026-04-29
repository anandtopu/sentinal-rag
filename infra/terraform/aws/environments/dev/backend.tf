# Remote state in S3, locked via DynamoDB.
#
# The bucket + table must exist before `terraform init`. Bootstrap them
# manually (one-time, per account), e.g. with the AWS CLI:
#
#   aws s3api create-bucket --bucket sentinelrag-tfstate-<account> --region us-east-1
#   aws s3api put-bucket-versioning --bucket sentinelrag-tfstate-<account> \
#     --versioning-configuration Status=Enabled
#   aws s3api put-bucket-encryption --bucket sentinelrag-tfstate-<account> \
#     --server-side-encryption-configuration ...
#   aws dynamodb create-table --table-name sentinelrag-tfstate-locks ...
#
# Or use a `bootstrap/` Terraform stack that runs locally with no backend.

terraform {
  backend "s3" {
    # Override at init time:
    #   terraform init -backend-config="bucket=sentinelrag-tfstate-<account>"
    bucket         = "sentinelrag-tfstate-PLACEHOLDER"
    key            = "aws/dev/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "sentinelrag-tfstate-locks"
  }
}
