# Provider versions are pinned exactly, not constrained with a range.
#
# The reason is the same one that made the Python toolchain exact-pinned: a gate whose verdict
# depends on the day it runs cannot tell you whether your change is clean. With `~>` a provider minor
# release can change a resource's behaviour between two applies of an unchanged configuration, and
# the difference surfaces as a plan nobody asked for — on the serve side of this architecture, that
# plan can be "replace the cache volume".
#
# Bump deliberately: change the version here, run `terraform init -upgrade` and `terraform plan`,
# read what moved, and commit both together.
terraform {
  required_version = ">= 1.9.0"

  required_providers {
    netapp-ontap = {
      source  = "NetApp/netapp-ontap"
      version = "2.7.1"
    }
  }
}

# The cache side is ONTAP, not AWS, so there is no AWS provider here at all. That is the point of
# splitting the two directories: the collect side is AWS-shaped and uses CloudFormation, the serve
# side is ONTAP-shaped and runs wherever the consuming site is — on-premises AFF or FAS, ONTAP
# Select, or a second FSx for ONTAP.
#
# Note on reach: this configuration talks to the cache cluster's management endpoint. When the cache
# is a second FSx for ONTAP, that endpoint is VPC-only, so Terraform has to run from inside that VPC
# or through a tunnel. Running it from a laptop against an FSx management LIF does not work, and the
# failure looks like a network timeout rather than a configuration error.
provider "netapp-ontap" {
  connection_profiles = [
    {
      name           = "cache"
      hostname       = var.cache_cluster_hostname
      username       = var.cache_cluster_username
      password       = var.cache_cluster_password
      validate_certs = var.validate_certs
    }
  ]
}
