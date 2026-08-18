# Decisions that come first — before the origin volume exists

<!-- lang-switcher:start -->
🌐 [日本語](../ja/design-first-decisions.md) | [English](design-first-decisions.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

The judgement that could be most expensive to reverse in this architecture is **whether the fan-out
side uses NFS or SMB**. The origin volume's security style bears on it.

The conclusion first. **Read the confirmed part and the unconfirmed part separately.**

> **Deciding whether the consuming site uses NFS or SMB before the origin volume exists is the safe
> order.** The security style (UNIX or NTFS) pairs with the type of identity the S3 Access Point uses,
> and that part is confirmed. **Whether the security style is inherited from the origin at cache
> creation time is unconfirmed.** If it is, changing it on the origin afterwards means deleting and
> recreating the cache. **The reason to decide early is the asymmetry, not a confirmed constraint.**

## The source, and how far it is confirmed

The basis for this section is **Azure NetApp Files' cache volume requirements**
([cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes) /
[requirements](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-requirements)).
It is not corroborated in AWS documentation as a property of FlexCache in general.

Two things therefore have to be read apart.

| Item | State |
|---|---|
| The mapping between security style and protocol (table below) | Stated in Azure NetApp Files' cache volume requirements. **Whether the same rule holds on this architecture's main path (FSx for ONTAP origin to on-premises ONTAP cache) is unconfirmed** |
| The property that "the security style is inherited from the origin" | Stated in the same requirements text. The behaviour on the main path is unconfirmed for the same reason |
| That changing the protocol later means rebuilding the serve layer | A consequence of the two above holding. The premise is unconfirmed, so this is not asserted |

The position taken here is not to defer the decision on the grounds that it is unconfirmed. The rework
if the rule holds is large, and there is nothing to lose if it does not. The procedure for confirming
it on hardware is in the [PoC checklist](poc-checklist.md).

## The mapping between security style and protocol

Azure NetApp Files' cache volume requirements state the following mapping.

| Origin security style | Cache protocol | S3 AP support |
|---|---|---|
| UNIX | NFS (SMB is also possible, name-mapping required) | ✅ supported |
| NTFS | SMB (the SVM needs a CIFS server) | ✅ supported (Windows identity) |
| MIXED | NFS or SMB | ⚠️ not recommended (see below) |

### On the MIXED security style

`mixed` can be specified through the API, but **AWS's own guidance does not recommend it, describing
it as for advanced users only**
([Enabling multiprotocol workloads with Amazon FSx for NetApp ONTAP](https://aws.amazon.com/blogs/storage/enabling-multiprotocol-workloads-with-amazon-fsx-for-netapp-ontap/)).
The FSx for ONTAP volume creation guide also presents the choice as UNIX or NTFS.

The problems with mixed:

- the permission type is decided by the kind of client that wrote last, which makes the permission
  state hard to predict
- troubleshooting has to cover both the NFS and the SMB permission model, which compounds it
- NetApp itself lists "Complex Permission Management" and "Troubleshooting Challenges" as
  disadvantages
  [in a KB article](https://kb.netapp.com/on-prem/ontap/da/NAS/NAS-KBs/What_are_the_disadvantages_of_the_Mixed_security_style)

**This architecture does not use mixed.** Choose either UNIX or NTFS.

Which identity the S3 Access Point uses on the FSx for ONTAP side, Windows or UNIX, ties directly to
the protocol choice on the fan-out side.

The identity only has to be a user the SVM can resolve. **Neither type requires an external directory
service.** A UNIX identity served reads and writes as an SVM-local user with no LDAP or NIS, and a
Windows identity did the same as a local user on a workgroup-mode CIFS server ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md)).
Workgroup mode is documented as the alternative when an Active Directory domain is not available
([SMB server in a workgroup](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html)). It supports NTLM authentication only, not Kerberos, and leaves
out GPO, VSS and SMB3 CA shares among others.

> **Security note**: if you do join the SVM to Active Directory, **every data operation** through the
> S3 Access Point then needs reachability to an AD domain controller. `HeadBucket` succeeds even when
> AD is unreachable, so it cannot be used as a connectivity check. Always confirm reachability with a
> data operation. This behaviour is treated as verified in the sibling repository
> ([verification status](verification-status.md)). **Not joining AD does not incur this dependency.**

## Other preconditions the same requirements text lists

All of these are stated in Azure NetApp Files' cache volume requirements, and whether the same
conditions apply on this architecture's main path is unconfirmed. They are listed as a starting point
for investigation.

- The cache is created through the REST API only (by way of the cache endpoint)
- The origin-side cluster runs ONTAP 9.15.1 or later
- The protocol type matches between cache and origin
- `globalFileLocking` is consistent across the caches sharing one origin. It is changed from the
  origin-side cluster's CLI (`volume flexcache origin config modify`)

## The order to decide in

1. **Decide the consuming site's protocol** — NFS or SMB. If equipment or an application already
   decides it, that is the answer
2. **Decide the origin's security style** — pick the one matching step 1. UNIX (mainly NFS) or NTFS
   (mainly SMB). mixed is not used
3. **Decide the S3 Access Point's identity** — make it consistent with step 2: a Windows identity for
   NTFS, a UNIX identity for UNIX, and in both cases create a user the SVM can resolve first.
   **Only joining Active Directory makes AD reachability a standing dependency.** The identity cannot
   be changed after creation, so separate write and read use onto separate access points
4. **Create the origin volume**
5. **Create the cache** — at this point the security style is no longer selectable

Proceeding to step 4 with any of steps 1 to 3 still open removes the choice at step 5.

## Operations that are irreversible or mean rebuilding

| Operation | Impact |
|---|---|
| Changing the origin's security style | The cache has to be deleted and recreated (if the premise above holds) |
| The S3 Access Point's `NetworkOrigin` | Cannot be changed after creation. Changing it means deleting and recreating the access point, which changes the alias. The reachability conditions are in [support matrix](support-matrix.md) |
| The FlexCache deletion order | Do not delete the origin side while a cache still exists. Releasing the cache and the SVM peer comes before removing the peering |
| Enabling SnapLock or tamperproof snapshots | Cannot be undone. **Do not enable it without an instruction that names the retention period.** See the irreversible operations section of [AGENTS.md](../../AGENTS.md) |

## Related documents

| Document | Contents |
|---|---|
| [Architecture](architecture.md) | The collect and serve layers as a whole |
| [Support matrix](support-matrix.md) | Minimum versions and supported configurations |
| [Verification status](verification-status.md) | What is verified and what is not |
| [PoC checklist](poc-checklist.md) | The procedure for confirming this section's unconfirmed items on hardware |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/design-first-decisions.md) | [English](design-first-decisions.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
