# RDS Postgres 16 with pgvector enabled.
#
# pgvector ships in RDS Postgres 16's catalog of trusted extensions —
# CREATE EXTENSION vector works with no parameter group flag (unlike e.g.
# pgaudit). We still set a custom parameter group so we can tune it later
# (work_mem, hnsw.ef_search, log_min_duration_statement) without forking
# the resource.

locals {
  family   = "postgres${split(".", var.engine_version)[0]}"
  port     = 5432
  password = var.master_password
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-rds"
  subnet_ids = var.private_subnet_ids
  tags       = merge(var.tags, { Name = "${var.name}-rds" })
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name}-pg"
  family      = local.family
  description = "SentinelRAG parameter group with pgvector + sane logging defaults."

  # Log slow queries (tunable). Keep autovacuum honest.
  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # ms — surface slow queries
  }
  # Loaded at session level for HNSW; default is fine, but we leave the
  # parameter group ready for ALTER SYSTEM if we need it.

  tags = var.tags
}

resource "aws_security_group" "this" {
  name        = "${var.name}-rds-sg"
  description = "Inbound Postgres from EKS cluster."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name}-rds-sg" })
}

resource "aws_security_group_rule" "ingress" {
  type                     = "ingress"
  from_port                = local.port
  to_port                  = local.port
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

resource "aws_db_instance" "this" {
  identifier              = "${var.name}-db"
  engine                  = "postgres"
  engine_version          = var.engine_version
  instance_class          = var.instance_class
  allocated_storage       = var.allocated_storage_gb
  max_allocated_storage   = var.max_allocated_storage_gb
  storage_type            = "gp3"
  storage_encrypted       = true
  kms_key_id              = var.kms_key_id

  db_name                 = var.database_name
  username                = var.master_username
  password                = local.password
  port                    = local.port

  multi_az                = var.multi_az
  publicly_accessible     = false
  db_subnet_group_name    = aws_db_subnet_group.this.name
  vpc_security_group_ids  = [aws_security_group.this.id]
  parameter_group_name    = aws_db_parameter_group.this.name

  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:30-sun:05:30"
  copy_tags_to_snapshot   = true
  deletion_protection     = var.deletion_protection
  skip_final_snapshot     = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name}-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"

  performance_insights_enabled = true
  performance_insights_retention_period = 7

  enabled_cloudwatch_logs_exports = ["postgresql"]
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.monitoring.arn

  apply_immediately = var.apply_immediately

  tags = merge(var.tags, { Name = "${var.name}-db" })

  lifecycle {
    # final_snapshot_identifier embeds timestamp() which rolls every plan;
    # skip the diff churn.
    ignore_changes = [final_snapshot_identifier, password]
  }
}

# Enhanced Monitoring needs an IAM role.
resource "aws_iam_role" "monitoring" {
  name = "${var.name}-rds-monitoring"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "monitoring" {
  role       = aws_iam_role.monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
