output "cluster_name" {
  value       = aws_eks_cluster.this.name
  description = "EKS cluster name."
}

output "cluster_endpoint" {
  value       = aws_eks_cluster.this.endpoint
  description = "Cluster API endpoint."
}

output "cluster_certificate_authority_data" {
  value       = aws_eks_cluster.this.certificate_authority[0].data
  description = "Cluster CA cert (base64-encoded)."
}

output "cluster_oidc_issuer_url" {
  value       = aws_eks_cluster.this.identity[0].oidc[0].issuer
  description = "OIDC issuer URL for IRSA."
}

output "oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.this.arn
  description = "ARN of the IAM OIDC provider for IRSA."
}

output "oidc_provider_url" {
  value       = replace(aws_iam_openid_connect_provider.this.url, "https://", "")
  description = "OIDC provider URL (no scheme), used in IRSA trust policies."
}

output "node_role_arn" {
  value       = aws_iam_role.node.arn
  description = "Node group IAM role ARN."
}

output "node_security_group_id" {
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  description = "Cluster security group (covers nodes via EKS-managed SG)."
}
