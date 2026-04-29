# GKE Standard cluster with Workload Identity, private nodes, public endpoint.
#
# We pick GKE Standard over Autopilot because Autopilot blocks several add-ons
# we want control over (DaemonSets for OTel collector, Temporal worker
# placement, custom resource requests for the bge-reranker pod). Autopilot is
# tempting for the "no node management" pitch but the lock-in trade-off is a
# net negative for this project.

resource "google_container_cluster" "this" {
  name     = var.name
  project  = var.project_id
  location = var.region

  # Remove the default node pool — we manage our own.
  remove_default_node_pool = true
  initial_node_count       = 1

  # VPC-native (alias IP) — required for shared services. Names match the
  # secondary ranges created in the vpc module.
  networking_mode = "VPC_NATIVE"
  network         = var.network_id
  subnetwork      = var.subnet_id
  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_range_name
    services_secondary_range_name = var.services_range_name
  }

  # Workload Identity — the GCP equivalent of IRSA. Pods authenticate to GCP
  # via the cluster's identity namespace `<project>.svc.id.goog`.
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Private cluster — nodes have no public IPs; egress goes through Cloud NAT.
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = var.master_ipv4_cidr
  }

  # Allow only specific CIDRs onto the public master endpoint.
  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.master_authorized_cidrs
      content {
        cidr_block   = cidr_blocks.value.cidr
        display_name = cidr_blocks.value.display_name
      }
    }
  }

  release_channel {
    channel = var.release_channel
  }

  # Surface logs + metrics via Cloud Operations.
  logging_service    = "logging.googleapis.com/kubernetes"
  monitoring_service = "monitoring.googleapis.com/kubernetes"

  addons_config {
    network_policy_config {
      disabled = false
    }
    http_load_balancing {
      disabled = false
    }
  }

  network_policy {
    enabled  = true
    provider = "CALICO"
  }

  # Database encryption with a CMEK if provided.
  dynamic "database_encryption" {
    for_each = var.database_encryption_key == null ? [] : [1]
    content {
      state    = "ENCRYPTED"
      key_name = var.database_encryption_key
    }
  }

  resource_labels = var.labels

  # Maintenance window during off-peak.
  maintenance_policy {
    daily_maintenance_window {
      start_time = "08:00"
    }
  }

  deletion_protection = var.deletion_protection

  lifecycle {
    # GKE upgrades change node_version + master_version out-of-band; ignore
    # so terraform apply doesn't fight the release channel.
    ignore_changes = [node_version, min_master_version]
  }
}

# Node pool — separate so it can be replaced without re-creating the cluster.
resource "google_container_node_pool" "primary" {
  name     = "${var.name}-pool"
  project  = var.project_id
  location = var.region
  cluster  = google_container_cluster.this.name

  initial_node_count = var.node_initial_count
  autoscaling {
    min_node_count = var.node_min_count
    max_node_count = var.node_max_count
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  upgrade_settings {
    max_surge       = 1
    max_unavailable = 0
  }

  node_config {
    machine_type = var.node_machine_type
    disk_size_gb = var.node_disk_size_gb
    disk_type    = "pd-balanced"

    # Service account for the node — nodes need pull access to GCR/Artifact
    # Registry; everything else is on the Workload Identity SAs.
    service_account = var.node_service_account
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    labels = merge(var.labels, {
      pool = "general"
    })

    tags = ["sentinelrag-node", "gke-${var.name}"]
  }

  lifecycle {
    ignore_changes = [initial_node_count]
  }
}
