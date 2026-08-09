# Serve-side (cache) environment for S3 Burst on ONTAP Files.
#
# Creates the FlexCache volume that fans the origin out to a consuming site, and exports it read-only
# over NFS. The origin lives on AWS and is built by environments/aws-origin/ with CloudFormation; the
# cache lives wherever the consumers are, which is why this half is Terraform against ONTAP rather
# than CloudFormation against AWS.
#
# There is no separate volume resource here on purpose. Creating a FlexCache creates its cache volume
# — the first draft of this file declared a `netapp-ontap_volume` as well, and `terraform validate`
# rejected it, which is the useful kind of early failure: two resources both claiming to own one
# volume would have fought on every apply.
#
# What this deliberately does NOT do:
#
#   * It does not create cluster or SVM peering. Peering needs IP reachability between the two
#     clusters' intercluster LIFs, which between two VPCs means VPC peering or a transit gateway with
#     routes on both sides. That is network topology owned outside this repository, and creating it
#     here would mean this configuration silently altering routing. It is also the most common reason
#     an otherwise correct apply fails, so check peering first when it does.
#   * It does not attach an S3 Access Point to the cache. The architecture puts the access point on
#     the origin only and serves the cache over a file protocol. ONTAP FlexCache duality and attaching
#     an FSx for ONTAP S3 Access Point are separate mechanisms, and this design uses neither on the
#     cache side.
#   * It sets no security style. That is treated as inherited from the origin at cache creation time
#     rather than as a property of the cache. Decide it on the origin, before the origin volume
#     exists.
#   * It enables no immutability feature. SnapLock and snapshot locking are absent on purpose: they
#     make the volume, its SVM and the whole file system undeletable for the retention period, and a
#     verification environment is the worst possible place for that.

locals {
  # Recorded in the outputs so a reader can tell which origin this cache is bound to without opening
  # the state file.
  origin_reference = "${var.origin_cluster_name}:${var.origin_svm_name}:${var.origin_volume_name}"
}

# The FlexCache relationship, and with it the cache volume.
#
# FlexCache is sparse: it holds the blocks that have actually been read, not a copy of the origin.
# That is the property the architecture depends on — a consuming site gets the part of the data set it
# uses, without the whole set being transferred to it. The size below is a ceiling, not an allocation.
resource "netapp-ontap_flexcache" "cache" {
  cx_profile_name = "cache"
  name            = var.cache_volume_name
  svm_name        = var.cache_svm_name

  origins = [
    {
      svm    = { name = var.origin_svm_name }
      volume = { name = var.origin_volume_name }
    }
  ]

  size      = var.cache_volume_size_gb
  size_unit = "gb"

  junction_path = var.cache_junction_path

  # Relevant on FSx for ONTAP, where a FlexCache volume has been observed to require a tiered
  # aggregate. Harmless where there is no capacity pool.
  use_tiered_aggregate = var.use_tiered_aggregate

  # Every cache sharing an origin has to agree on this, and it is changed on the *origin* cluster's
  # CLI (`volume flexcache origin config modify`), not from here. This architecture serves reads from
  # the cache and takes writes through the origin's S3 Access Point, so cross-cache locking is
  # usually not required.
  global_file_locking_enabled = var.global_file_locking

  # Left to ONTAP when empty. On FSx for ONTAP the aggregate is service-managed and naming one is
  # normally wrong.
  aggregates = [
    for aggregate in var.aggregates : { name = aggregate }
  ]

  # Writeback is left at its default rather than enabled. With writeback on, an S3 Access Point write
  # and a cache-side write to the same file cause the cache's dirty data to be discarded — a
  # data-loss shape nobody should meet for the first time in production. Writes belong on the origin.
}

# Export policy for the consuming site.
#
# Read-only by intent, not by omission. The architecture serves reads from the cache and takes writes
# through the origin, so a read-write export here would invite the topology the design avoids.
resource "netapp-ontap_nfs_export_policy" "cache_readonly" {
  cx_profile_name = "cache"
  name            = "${var.cache_volume_name}_ro"
  svm_name        = var.cache_svm_name
}

resource "netapp-ontap_nfs_export_policy_rule" "cache_readonly" {
  cx_profile_name    = "cache"
  svm_name           = var.cache_svm_name
  export_policy_name = netapp-ontap_nfs_export_policy.cache_readonly.name
  index              = 1

  clients_match = split(",", var.allowed_clients)
  protocols     = ["nfs3", "nfs4"]

  # ro_rule allows AUTH_SYS reads; rw_rule and superuser are "none" so that a client cannot write
  # through the cache or act as root on it, whatever the file permissions say.
  ro_rule   = ["sys"]
  rw_rule   = ["none"]
  superuser = ["none"]

  depends_on = [netapp-ontap_nfs_export_policy.cache_readonly]
}
