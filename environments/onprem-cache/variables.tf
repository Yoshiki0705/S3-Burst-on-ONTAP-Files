variable "cache_cluster_hostname" {
  description = "Management hostname or IP of the ONTAP cluster that will hold the cache volume."
  type        = string
}

variable "cache_cluster_username" {
  description = "ONTAP administrative user on the cache cluster."
  type        = string
  default     = "admin"
}

variable "cache_cluster_password" {
  description = <<-EOT
    Password for the cache cluster administrator.

    Marked sensitive so it is redacted from plan and apply output. That is not the same as being
    secret: Terraform writes variable values into the state file in clear text. Keep state in a
    backend with encryption and access control, and prefer supplying this through the environment
    (TF_VAR_cache_cluster_password) or a secrets manager over a tfvars file on disk.
  EOT
  type        = string
  sensitive   = true
}

variable "validate_certs" {
  description = <<-EOT
    Whether to validate the cluster's TLS certificate.

    Defaults to true. A lab cluster commonly ships a self-signed certificate, and the honest way to
    handle that is to set this to false deliberately for that cluster rather than to leave
    verification off by default for everyone.
  EOT
  type        = bool
  default     = true
}

variable "cache_svm_name" {
  description = "SVM on the cache cluster that will own the cache volume."
  type        = string
}

variable "cache_volume_name" {
  description = "Name of the cache volume. ONTAP allows alphanumerics and underscores only."
  type        = string
  default     = "cache_vol"

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9_]{1,46}$", var.cache_volume_name))
    error_message = "ONTAP volume names accept alphanumerics and underscores only, starting with a letter."
  }
}

variable "cache_volume_size_gb" {
  description = <<-EOT
    Size of the cache volume in GB.

    A FlexCache volume is sparse: it holds what has actually been read, not a copy of the origin. The
    size is a ceiling, not an allocation of the origin's contents.

    The default is 50 because 50 GB is reported as the minimum FlexCache volume size on FSx for
    ONTAP. That figure is documented in a sibling repository and has not been verified here, so treat
    it as a starting point — if your cluster accepts less, it costs less.
  EOT
  type        = number
  default     = 50

  validation {
    condition     = var.cache_volume_size_gb >= 1
    error_message = "Size must be at least 1 GB."
  }
}

variable "cache_junction_path" {
  description = "Junction path to mount the cache volume at on the cache cluster."
  type        = string
  default     = "/cache_vol"
}

variable "origin_cluster_name" {
  description = <<-EOT
    Name of the ONTAP cluster holding the origin volume, as the cache cluster knows it.

    This is the cluster peer name, not a hostname. Cluster and SVM peering must already exist before
    a FlexCache relationship can be created, and peering needs IP reachability between the two
    clusters' intercluster LIFs. Between two VPCs that means VPC peering or a transit gateway with
    routes on both sides — it is not created by this configuration, and its absence is the most
    common reason an otherwise correct apply fails.
  EOT
  type        = string
}

variable "origin_svm_name" {
  description = "SVM on the origin cluster that owns the origin volume."
  type        = string
}

variable "origin_volume_name" {
  description = "Origin volume to cache. This is the volume the S3 Access Point is attached to."
  type        = string
}

variable "aggregates" {
  description = <<-EOT
    Aggregates on the cache cluster to place the cache volume on.

    Leave empty to let ONTAP choose. On FSx for ONTAP the aggregate is managed by the service and
    should normally be left empty.
  EOT
  type        = list(string)
  default     = []
}

variable "use_tiered_aggregate" {
  description = <<-EOT
    Whether the cache volume may use a tiered (capacity pool) aggregate.

    Relevant on FSx for ONTAP, where a FlexCache volume has been observed to require this. Leave true
    unless the cache cluster has no capacity pool.
  EOT
  type        = bool
  default     = true
}

variable "global_file_locking" {
  description = <<-EOT
    Whether to enable global file locking on the cache.

    Two things make this worth deciding up front rather than later. Every cache sharing an origin has
    to agree on the setting, and changing it is done on the origin cluster's CLI
    (`volume flexcache origin config modify`) rather than here. This architecture serves reads from
    the cache and writes through the origin's S3 Access Point, so locking across caches is usually
    not required; leaving it off avoids a cross-cache coordination requirement.
  EOT
  type        = bool
  default     = false
}

variable "tags" {
  description = "Free-form labels recorded in the outputs for traceability. ONTAP has no tag API."
  type        = map(string)
  default = {
    project = "s3-burst-on-ontap-files"
    role    = "serve-side-cache"
  }
}

variable "allowed_clients" {
  description = <<-EOT
    Client match string for the cache's NFS export rule, for example "10.20.0.0/16".

    No default. An export rule is an access control decision, and a default here would either be
    permissive enough to be wrong everywhere or narrow enough to be wrong everywhere — in both cases
    somebody would find out by having it not work, or by it working for more clients than intended.
  EOT
  type        = string

  validation {
    condition     = length(trimspace(var.allowed_clients)) > 0
    error_message = "Set allowed_clients to the consuming site's network, not to 0.0.0.0/0."
  }

  validation {
    condition     = trimspace(var.allowed_clients) != "0.0.0.0/0"
    error_message = "0.0.0.0/0 exports the cache to every reachable client. Narrow it to the consuming site."
  }
}
