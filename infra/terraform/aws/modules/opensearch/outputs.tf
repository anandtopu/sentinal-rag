output "endpoint" {
  value       = aws_opensearch_domain.this.endpoint
  description = "Domain endpoint hostname (no scheme)."
}

output "kibana_endpoint" {
  value       = aws_opensearch_domain.this.dashboard_endpoint
  description = "OpenSearch Dashboards endpoint."
}

output "domain_arn" {
  value       = aws_opensearch_domain.this.arn
  description = "Domain ARN."
}

output "security_group_id" {
  value       = aws_security_group.this.id
  description = "Security group attached to the domain."
}
