# Cloud SQL Postgres 16 with pgvector enabled.
#
# pgvector ships in Cloud SQL Postgres 16 as a supported extension (we still
# CREATE EXTENSION at boot via migration 0002). The instance peers into the
# VPC via Private Service Access, so workloads connect on the private IP
# without going through the Cloud SQL Auth Proxy.

resource "google_sql_database_instance" "this" {
  name             = "${var.name}-db"
  project          = var.project_id
  region           = var.region
  database_version = "POSTGRES_16"

  settings {
    tier              = var.tier
    availability_type = var.availability_type
    disk_type         = "PD_SSD"
    disk_size         = var.disk_size_gb
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = var.backup_retention_count
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled                                  = false # private only
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
    }

    insights_config {
      query_insights_enabled = true
      query_string_length    = 1024
      record_application_tags = true
      record_client_address   = false
    }

    maintenance_window {
      day          = 7   # Sunday
      hour         = 4
      update_track = "stable"
    }

    user_labels = var.labels
  }

  deletion_protection = var.deletion_protection

  depends_on = [var.private_service_access_dependency]

  lifecycle {
    ignore_changes = [settings[0].disk_size]
  }
}

resource "google_sql_database" "primary" {
  name     = var.database_name
  project  = var.project_id
  instance = google_sql_database_instance.this.name
}

resource "google_sql_user" "master" {
  name     = var.master_username
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = var.master_password
}
