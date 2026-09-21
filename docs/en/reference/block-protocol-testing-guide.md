# Considerations when measuring FSx for ONTAP's block protocols

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/block-protocol-testing-guide.md) | [English](block-protocol-testing-guide.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Collects the pitfalls hit while mounting and measuring FSx for ONTAP over iSCSI / NVMe-TCP in one
place. **File / S3 protocol considerations are in
[Performance testing considerations](performance-testing-guide.md).**
This document holds only what is specific to block protocols.

This document is meant to be read before measuring; it does not contain measurement results.
Results are reached from [verification status](../verification-status.md), sourced from
[per-protocol measurement results](../../ja/verification/perf-matrix-results.md) (Japanese) and
the [block measurement runbook](../../ja/verification/block-measurement-runbook.md) (Japanese).

## Four things before reaching a mount

**Each looks like it succeeded while measuring nothing.**

| Symptom | Cause | How to check |
|---|---|---|
| File system creation fails 25 minutes in | `JunctionPath`'s API reference body says `This parameter is required.` while the `Required:` column says `No`. **The actual behavior is required** | Always specify it for `RW` volumes |
| `cat /etc/nvme/hostnqn` returns `No such file or directory` | AL2023 doesn't create this file (RHEL does) | Generate it with `nvme gen-hostnqn` |
| Counting with `ss` right after login returns 0 | `iscsiadm --login` returns before the connection actually completes. In this environment it took **about 100 seconds** | Don't treat "the command returned" as evidence of "connected." Count to confirm |
| `/dev/mapper/<alias>` never appears | When intentionally measuring a single flow, the path count is 1 by design, but `find_multipaths yes` doesn't create a map for a single-path device | Register explicitly with `multipath -a <wwid>`. Read the wwid from the device with `scsi_id` rather than assembling it |

Details as a table of symptom / cause / how to check are in the
[block measurement runbook](../../ja/verification/block-measurement-runbook.md) (Japanese).

## Before sizing session or queue counts

**Sizing session count by dividing required bandwidth by the "single client 5 Gbps (~625 MBps)"
figure misses in both directions.** 1.82x with one session, 0.20x with sixteen. **Going from one
session to two can move sequential throughput by zero bytes** — the ceiling hit with one session is
not a single flow's capacity.

NVMe/TCP has nothing equivalent to `nr_sessions`; the corresponding quantity is queue count.
**Queue count doesn't honor a request** — one example asked for 36 via `--nr-io-queues` and got 4.

- **Read the effective value with `nvme get-feature --feature-id 7`.** It isn't the value set on
  the subsystem; ONTAP determines it per combination of host, transport, and priority
- **`queue_count` includes the admin queue and matches `NCQA + 1`** (1 -> 2, 4 -> 5)
- Don't use an example's value as your own environment's value. It differs by environment even
  under the same conditions

## Checking whether ANA (multipathing) is available before you're billed

**The check takes one command and can be done before creating a file system.**

```bash
grep -i NVME_MULTIPATH /boot/config-$(uname -r)
```

If it returns `# CONFIG_NVME_MULTIPATH is not set`, then AWS's procedure step
`cat /sys/module/nvme_core/parameters/multipath` doesn't hold (the file doesn't exist). This is a
kernel build setting and can't be changed by adding a package.

**Don't generalize this result.** Write what you observed for the kernel version you checked, not
"ANA doesn't work on AL2023." AL2023's default kernel can change.

### Having two paths and using two paths are different things

**`nvme list-subsys`'s `optimized` / `non-optimized` shows "two paths exist," not "two paths are
being used."** Whether it's actually being used needs to be counted separately.

| Table | Trap |
|---|---|
| `nvmf_lif` | **Can return zero rows.** Indistinguishable from the table not existing at all |
| `lif` | Reports the relevant LIF at 0 bytes. **Doesn't count NVMe-oF** |
| `nvmf_tcp_port` | Has real data. Per-LIF `read_data` / `write_data` / `total_ops` |

**"The table exists but has no rows" and "this version doesn't have that table" look the same —
both return zero.** Proceeding past a zero can land on a correct conclusion for the wrong reason.

It can also be counted independently on the client side. NVMe/TCP controllers use different
destination addresses, so aggregating established sockets by destination separates the paths.

```bash
ss -tin state established | awk '/:4420/{...}'   # sum bytes_sent / bytes_received per destination
```

**Only draw a conclusion once both the ONTAP-side counter and the client-side aggregation agree.**

### The `iopolicy` check procedure itself depends on version

AWS's procedure has you confirm `iopolicy` is `round-robin`, but the value the udev rule sets
depends on the `nvme-cli` version (in upstream's `71-nvmf-netapp.rules.in`, v2.11 is `round-robin`
and v2.12 onward is `queue-depth`). **Following the procedure as written can return a value other
than expected, depending on version.** The performance impact is negligible (measured at 0.5%) —
this isn't a performance issue, it's a version difference in what the check procedure returns.

## Pitfalls with the measurement tool (VDBENCH) and block devices

**auto_vdbench is built to create test files at a mount path and can't drive a raw device / NVMe
namespace.** Use VDBENCH directly when measuring block.

| Symptom | Cause | Fix |
|---|---|---|
| Fill "completes successfully without writing anything" | vdbench resolves `include=` against the current directory, not against the path given to `-f` | Check the current directory at execution time. Verify beforehand whether the measurement is reading unwritten (zero) blocks |
| Passing `xfersize=1024k` fails with `Unused parameter substitution` | A `key=value` on the command line isn't an override of the workload definition — it's an assignment to a placeholder inside the parameter file | Put the placeholder in the parameter file |
| A 600 GiB write is judged a failure because it doesn't fit the wait limit | Misjudged SSM's `status: InProgress` as a failure | A wait limit isn't a failure. Keep polling until completion |
| A detection step gets skipped even though the module is present | Implementation prints `MISSING` when the module is absent, checked with `grep -q 'MISSING'`, but it hit an explanatory line in the same output (`A MISSING line means…`) | Don't use a sentinel string that your own explanatory text can satisfy |
| A `DELETE_FAILED` stack remains after teardown | Under `set -euo pipefail`, calling `describe-stacks` after deletion always fails once the stack is gone, and that failure kills the trap itself | Put the delete call first in the trap, then `set +e` right after |
| A nonexistent path appears in socket aggregation | A field ending in `:4420` was treated as the destination, but `bytes_acked:4420` — a **value** — happened to match 4420, creating a fake path named `bytes_acked` | Select the aggregated field by an explicit key name, not by matching on value content |
| Only CI turns red | A check that scans tracked files doesn't include a new file while it's untracked | Check after the last `git add`, not just after the last edit |

## Lowering provisioned IOPS starts a six-hour cooldown

**A provisioned IOPS change is treated as a storage capacity update, and lowering it blocks the
next update for six hours from the last one.** Try to raise it back right away and the request is
refused with "cannot start until at least 6 hours have passed since the last storage capacity
update". Billing continues while you wait.

**The increasing direction has no such constraint.** It takes one update and doesn't hit the
cooldown. When a plan calls for measuring several provisioned values, building one series that
only increases is cheaper than a file system that goes down and back up.

**The update itself isn't instant either.** It stays in `UPDATED_OPTIMIZING` for about 18 minutes
(about 17 minutes when lowering). Don't start measuring at the new value during that window.

| What you want | Cheaper way to build it |
|---|---|
| Measure several provisioned values in sequence | One series, low to high, increasing only |
| Also measure a lower value | Specify it at file system creation time; don't raise and lower it later |
| Need a round trip — lower then restore | Rebuilding the environment is often cheaper than waiting six hours |

## Items to always record (block-specific)

In addition to the
[file/S3 protocol list](performance-testing-guide.md#what-to-always-record-alongside-a-measurement),
record the following for block:

- iSCSI: the counted number of TCP connections (the actual count from `ss`, not the requested value)
- NVMe/TCP: requested queue count and effective queue count (`nvme get-feature --feature-id 7`),
  controller count
- ANA: kernel's `CONFIG_NVME_MULTIPATH` presence, the kernel version checked
- `iopolicy` setting value and `nvme-cli` version
- Per-path byte counts (both the ONTAP-side counter and the client-side aggregation)
- ONTAP version. **`FileSystemTypeVersion` is a Lustre-only field and cannot be retrieved for
  FSx for ONTAP**, so recording it depends on the cluster-side API or manual notes

## Related documents

| Document | Content |
|---|---|
| [File/S3 protocol considerations](performance-testing-guide.md) | Common pitfalls and recording items across protocols |
| [Block measurement runbook](../../ja/verification/block-measurement-runbook.md) (Japanese) | Symptom / cause / how-to-check table |
| [Per-protocol measurement results](../../ja/verification/perf-matrix-results.md) (Japanese) | Block protocol measurement records |
| [Verification status](../verification-status.md) | Stage of each claim |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/block-protocol-testing-guide.md) | [English](block-protocol-testing-guide.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
