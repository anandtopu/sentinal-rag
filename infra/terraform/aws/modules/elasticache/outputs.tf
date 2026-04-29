output "primary_endpoint" {
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
  description = "Primary endpoint hostname."
}

output "configuration_endpoint" {
  value       = aws_elasticache_replication_group.this.configuration_endpoint_address
  description = "Cluster-mode configuration endpoint (null when single shard)."
}

output "port" {
  value       = aws_elasticache_replication_group.this.port
  description = "Redis port."
}

output "security_group_id" {
  value       = aws_security_group.this.id
  description = "Security group attached to the cluster."
}
