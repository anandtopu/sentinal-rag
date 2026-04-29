# ElastiCache Redis 7 replication group.
# Single-node in dev, Multi-AZ replication group in prod.

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name}-redis"
  subnet_ids = var.private_subnet_ids
  tags       = merge(var.tags, { Name = "${var.name}-redis" })
}

resource "aws_security_group" "this" {
  name        = "${var.name}-redis-sg"
  description = "Inbound Redis from EKS workloads."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-redis-sg" })
}

resource "aws_security_group_rule" "ingress" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.this.id
  source_security_group_id = var.client_security_group_id
}

resource "aws_security_group_rule" "egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  security_group_id = aws_security_group.this.id
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_elasticache_parameter_group" "this" {
  name        = "${var.name}-redis-pg"
  family      = "redis7"
  description = "SentinelRAG Redis 7 parameter group."

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  tags = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = "${var.name}-redis"
  description                = "SentinelRAG ${var.name} cache."
  engine                     = "redis"
  engine_version             = var.engine_version
  node_type                  = var.node_type
  port                       = 6379
  parameter_group_name       = aws_elasticache_parameter_group.this.name

  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.this.id]

  automatic_failover_enabled = var.num_node_groups > 1 || var.replicas_per_node_group > 0
  multi_az_enabled           = var.multi_az
  num_node_groups            = var.num_node_groups
  replicas_per_node_group    = var.replicas_per_node_group

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = var.auth_token

  snapshot_retention_limit   = var.snapshot_retention_days
  snapshot_window            = "02:00-03:00"
  maintenance_window         = "sun:03:30-sun:04:30"

  apply_immediately          = var.apply_immediately

  tags = merge(var.tags, { Name = "${var.name}-redis" })

  lifecycle {
    ignore_changes = [auth_token]
  }
}
