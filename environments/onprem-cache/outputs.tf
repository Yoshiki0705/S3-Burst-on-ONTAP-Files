output "cache_volume_name" {
  description = "Name of the cache volume created by the FlexCache relationship."
  value       = netapp-ontap_flexcache.cache.name
}

output "cache_junction_path" {
  description = "Path to mount on the consuming site's clients."
  value       = var.cache_junction_path
}

output "origin_reference" {
  description = "The origin this cache is bound to, as cluster:svm:volume."
  value       = local.origin_reference
}

output "export_policy_name" {
  description = "Read-only export policy applied to the cache."
  value       = netapp-ontap_nfs_export_policy.cache_readonly.name
}

output "mount_command" {
  description = <<-EOT
    How to mount the cache on a client at the consuming site.

    Two forms, because the NFS client's attribute cache decides what a reader sees and the difference
    is not small. Linux defaults are acdirmin=30 and acdirmax=60, so a file that appears in a
    directory the client has already listed can stay invisible for up to a minute for reasons that
    have nothing to do with the storage. Measured on the origin side of this architecture: a delete
    took 7 ms to be reflected with actimeo=0 and over two seconds with the defaults.

    Use actimeo=0 when you are measuring or when freshness matters. Use the default when you are
    reading the same files repeatedly and want the cache to do its job.
  EOT
  value = {
    fresh     = "sudo mount -t nfs -o nfsvers=3,actimeo=0 <cache-svm-nfs-ip>:${var.cache_junction_path} /mnt/cache"
    cached    = "sudo mount -t nfs -o nfsvers=3 <cache-svm-nfs-ip>:${var.cache_junction_path} /mnt/cache"
    read_only = "The export policy allows reads only. Writes belong on the origin's S3 Access Point."
  }
}

output "teardown_order" {
  description = <<-EOT
    Order matters on the serve side, and getting it wrong leaves resources that cannot be removed
    until something else is.

    `terraform destroy` removes the cache volume and the export policy. The peering it depends on was
    not created here and is not removed here.
  EOT
  value = join(" -> ", [
    "terraform destroy (cache volume, export policy)",
    "release the SVM peer",
    "release the cluster peer",
    "remove VPC peering or the transit gateway attachment",
    "delete the origin stack (environments/aws-origin)",
  ])
}

output "what_is_not_verified" {
  description = <<-EOT
    Stated in the output so it is read at apply time rather than looked for in a document.

    Whether an object written through the origin's S3 Access Point becomes visible on this cache
    volume, and how long that takes, is UNVERIFIED in this repository. The measured figures published
    so far are for the origin volume itself, over both protocols, which is a different question. See
    docs/ja/verification-status.md, and docs/ja/poc-checklist.md for the order to check things in.
  EOT
  value       = "S3 Access Point write to FlexCache cache visibility: unverified. See docs/ja/verification-status.md"
}
