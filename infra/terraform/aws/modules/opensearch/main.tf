# AWS OpenSearch domain — phase 8 reintroduction (ADR-0026).
#
# Deployed in private subnets, accessed by EKS workloads via the cluster
# security group. Fine-grained access control with the master user backed
# by a Secrets Manager secret; downstream apps use IAM-signed requests
# (boto3 + opensearch-py URLLib3 connection) so no long-lived credentials
# live in pods.

resource "aws_security_group" "this" {
  name        = "${var.name}-os-sg"
  description = "Inbound HTTPS from EKS workloads to the OpenSearch domain."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-os-sg" })
}

resource "aws_security_group_rule" "ingress_https" {
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.this.id
  source_security_group_id = var.client_security_group_id
}

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.this.id
  cidr_blocks       = ["0.0.0.0/0"]
}

# Service-linked role required by OpenSearch in a VPC. Idempotent —
# checked-then-created across multiple stacks in the same account is fine.
resource "aws_iam_service_linked_role" "this" {
  count            = var.create_service_linked_role ? 1 : 0
  aws_service_name = "opensearchservice.amazonaws.com"
}

resource "aws_opensearch_domain" "this" {
  domain_name    = "${var.name}-os"
  engine_version = var.engine_version

  cluster_config {
    instance_type            = var.instance_type
    instance_count           = var.instance_count
    zone_awareness_enabled   = var.zone_awareness_enabled
    dynamic "zone_awareness_config" {
      for_each = var.zone_awareness_enabled ? [1] : []
      content {
        availability_zone_count = min(var.instance_count, length(var.private_subnet_ids))
      }
    }
    dedicated_master_enabled = var.dedicated_master_enabled
    dynamic "dedicated_master_config" {
      for_each = var.dedicated_master_enabled ? [1] : []
      content {
        instance_type  = var.master_instance_type
        instance_count = 3
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.ebs_volume_size_gb
  }

  vpc_options {
    subnet_ids         = slice(var.private_subnet_ids, 0, var.zone_awareness_enabled ? min(var.instance_count, length(var.private_subnet_ids)) : 1)
    security_group_ids = [aws_security_group.this.id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_id
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https           = true
    tls_security_policy     = "Policy-Min-TLS-1-2-PFS-2023-10"
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = var.master_user_name
      master_user_password = var.master_user_password
    }
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.es_logs.arn
    log_type                 = "ES_APPLICATION_LOGS"
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.es_logs.arn
    log_type                 = "INDEX_SLOW_LOGS"
  }

  tags = merge(var.tags, { Name = "${var.name}-os" })

  depends_on = [aws_iam_service_linked_role.this]

  lifecycle {
    # Engine upgrades happen out-of-band; ignore the diff.
    ignore_changes = [advanced_security_options[0].master_user_options]
  }
}

resource "aws_cloudwatch_log_group" "es_logs" {
  name              = "/aws/opensearch/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_resource_policy" "es_logs" {
  policy_name = "${var.name}-os-log-policy"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "es.amazonaws.com" }
      Action    = ["logs:PutLogEvents", "logs:CreateLogStream"]
      Resource  = "${aws_cloudwatch_log_group.es_logs.arn}:*"
    }]
  })
}
