# Memorystore for Redis 7 — VPC-private, AUTH + TLS enabled.

resource "google_redis_instance" "this" {
  name           = "${var.name}-redis"
  project        = var.project_id
  region         = var.region
  tier           = var.tier
  memory_size_gb = var.memory_size_gb

  redis_version       = "REDIS_7_2"
  authorized_network  = var.network_id
  connect_mode        = "PRIVATE_SERVICE_ACCESS"
  reserved_ip_range   = var.reserved_ip_range
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  auth_enabled        = true

  redis_configs = {
    maxmemory-policy = "allkeys-lru"
  }

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 4
        minutes = 0
        seconds = 0
        nanos   = 0
      }
    }
  }

  labels = var.labels
}
