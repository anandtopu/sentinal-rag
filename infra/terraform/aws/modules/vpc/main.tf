# VPC for SentinelRAG on AWS.
#
# 3 AZs, public + private subnets per AZ.
#   - Public  : NAT egress + ALB
#   - Private : EKS nodes, RDS, ElastiCache (no public IPs)
# One NAT gateway per AZ for HA in prod; toggle to single-NAT for dev cost.
#
# EKS subnet discovery requires the magic tags
# (kubernetes.io/role/elb on public, /role/internal-elb on private, plus the
# kubernetes.io/cluster/<name> tag) — we set them here so the AWS Load
# Balancer Controller can find subnets without explicit annotations.

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 3)

  # /16 → /20 subnets gives 4096 IPs per subnet, plenty of headroom for
  # EKS pods (cluster CIDR doesn't draw from VPC IPs but ENIs do).
  public_subnet_cidrs  = [for i, _ in local.azs : cidrsubnet(var.cidr_block, 4, i)]
  private_subnet_cidrs = [for i, _ in local.azs : cidrsubnet(var.cidr_block, 4, i + 8)]

  cluster_subnet_tag = { "kubernetes.io/cluster/${var.cluster_name}" = "shared" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.tags, local.cluster_subnet_tag, {
    Name = "${var.name}-vpc"
  })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags = merge(var.tags, {
    Name = "${var.name}-igw"
  })
}

resource "aws_subnet" "public" {
  count                   = length(local.azs)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, local.cluster_subnet_tag, {
    Name                       = "${var.name}-public-${local.azs[count.index]}"
    Tier                       = "public"
    "kubernetes.io/role/elb"   = "1"
  })
}

resource "aws_subnet" "private" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = merge(var.tags, local.cluster_subnet_tag, {
    Name                              = "${var.name}-private-${local.azs[count.index]}"
    Tier                              = "private"
    "kubernetes.io/role/internal-elb" = "1"
  })
}

# NAT — single in dev, one-per-AZ in prod (controlled by single_nat_gateway).
resource "aws_eip" "nat" {
  count  = var.single_nat_gateway ? 1 : length(local.azs)
  domain = "vpc"
  tags = merge(var.tags, {
    Name = "${var.name}-nat-eip-${count.index}"
  })
}

resource "aws_nat_gateway" "this" {
  count         = var.single_nat_gateway ? 1 : length(local.azs)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags = merge(var.tags, {
    Name = "${var.name}-nat-${count.index}"
  })
  depends_on = [aws_internet_gateway.this]
}

# Route tables.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = merge(var.tags, {
    Name = "${var.name}-rt-public"
  })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = length(local.azs)
  vpc_id = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[var.single_nat_gateway ? 0 : count.index].id
  }
  tags = merge(var.tags, {
    Name = "${var.name}-rt-private-${local.azs[count.index]}"
  })
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# VPC Flow Logs to CloudWatch — production hygiene; tiny cost.
resource "aws_cloudwatch_log_group" "flow" {
  count             = var.enable_flow_logs ? 1 : 0
  name              = "/aws/vpc/${var.name}-flow"
  retention_in_days = var.flow_log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "flow" {
  count = var.enable_flow_logs ? 1 : 0
  name  = "${var.name}-vpc-flow-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy" "flow" {
  count = var.enable_flow_logs ? 1 : 0
  role  = aws_iam_role.flow[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
        "logs:DescribeLogGroups",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_flow_log" "this" {
  count                = var.enable_flow_logs ? 1 : 0
  iam_role_arn         = aws_iam_role.flow[0].arn
  log_destination      = aws_cloudwatch_log_group.flow[0].arn
  traffic_type         = "ALL"
  vpc_id               = aws_vpc.this.id
  max_aggregation_interval = 60
  tags                 = var.tags
}
