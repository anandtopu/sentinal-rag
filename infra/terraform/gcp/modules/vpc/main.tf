# GCP VPC for SentinelRAG (mirror of the AWS VPC module).
#
# One regional VPC with one subnet per region, secondary ranges carved out
# for GKE pods + services (VPC-native cluster requires this). Cloud NAT for
# outbound from private GKE nodes; private services VPC peering range
# carved for Cloud SQL + Memorystore.

resource "google_compute_network" "this" {
  name                            = "${var.name}-vpc"
  project                         = var.project_id
  auto_create_subnetworks         = false
  routing_mode                    = "REGIONAL"
  delete_default_routes_on_create = false
}

resource "google_compute_subnetwork" "primary" {
  name                     = "${var.name}-subnet"
  project                  = var.project_id
  network                  = google_compute_network.this.id
  region                   = var.region
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }

  # Secondary ranges for GKE — VPC-native (alias IP) clusters require these.
  secondary_ip_range {
    range_name    = "${var.name}-pods"
    ip_cidr_range = var.gke_pods_cidr
  }
  secondary_ip_range {
    range_name    = "${var.name}-services"
    ip_cidr_range = var.gke_services_cidr
  }
}

# Cloud Router + NAT so private nodes can reach the internet (registry pulls,
# LiteLLM egress to OpenAI/Anthropic, Ollama-via-DNS).
resource "google_compute_router" "this" {
  name    = "${var.name}-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  name                               = "${var.name}-nat"
  project                            = var.project_id
  router                             = google_compute_router.this.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Reserved range for Private Service Access — Cloud SQL + Memorystore peer
# their VPCs into ours via this allocation.
resource "google_compute_global_address" "private_service_access" {
  name          = "${var.name}-psa"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_access_prefix
  network       = google_compute_network.this.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.this.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_access.name]
}

# Default-deny ingress (defense-in-depth on top of GKE NetworkPolicy).
resource "google_compute_firewall" "deny_all_ingress" {
  name      = "${var.name}-deny-all-ingress"
  project   = var.project_id
  network   = google_compute_network.this.name
  priority  = 65534
  direction = "INGRESS"

  deny {
    protocol = "all"
  }
  source_ranges = ["0.0.0.0/0"]
}

# Allow GCP health checks (load balancers).
resource "google_compute_firewall" "allow_health_checks" {
  name      = "${var.name}-allow-hc"
  project   = var.project_id
  network   = google_compute_network.this.name
  direction = "INGRESS"

  allow {
    protocol = "tcp"
  }
  # GCP LB health-check IP ranges.
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
}
