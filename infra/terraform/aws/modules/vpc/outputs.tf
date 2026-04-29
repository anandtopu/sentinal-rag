output "vpc_id" {
  value       = aws_vpc.this.id
  description = "VPC ID."
}

output "vpc_cidr_block" {
  value       = aws_vpc.this.cidr_block
  description = "VPC CIDR."
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "Public subnet IDs (one per AZ)."
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Private subnet IDs (one per AZ)."
}

output "azs" {
  value       = local.azs
  description = "Availability zones used by the VPC."
}
