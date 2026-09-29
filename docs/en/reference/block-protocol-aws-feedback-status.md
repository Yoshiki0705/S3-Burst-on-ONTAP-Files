# AWS feedback status for the block protocol articles

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/block-protocol-aws-feedback-status.md) | [English](block-protocol-aws-feedback-status.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Collects, in one place, where the three block protocol measurement articles and S3 Burst Part 2
touch the published documentation. **Each article's own "AWS feedback status" section holds the
state for that article; this document is an index across articles.** The individual background,
verbatim citations, and reproduction steps live in each article and aren't duplicated here.

**Case numbers aren't written here.** They're recorded only in the internal ledger (gitignored).
What's recorded here is content, category, and status.

## Filed (7 items)

| Article | Finding | Category | Status (checked 2026-09-22) |
|---|---|---|---|
| A | `JunctionPath`'s body and `Required:` column disagree ([API reference](https://docs.aws.amazon.com/fsx/latest/APIReference/API_CreateOntapVolumeConfiguration.html), propagates into CloudFormation and the CDK) | Self-contradiction in the documentation | The rationale behind `Required: No` was explained (RW requires it, DP disallows it, so the combined attribute reads as not-always-required). No commitment on adopting `Required: Conditional` |
| B | "Aside from installing packages, valid for other EC2 Linux AMIs" against `cat /etc/nvme/hostnqn` being absent on AL2023 | Counterexample outside the stated scope | Reproduced in the same environment, confirming the file is absent. The two proposed fixes are expected to be shared with the documentation team. No commitment on adoption or timing |
| B | Same statement against `cat /sys/module/nvme_core/parameters/multipath` being absent on AL2023 (`CONFIG_NVME_MULTIPATH` unset) | Counterexample outside the stated scope | The observation was confirmed and filed. A follow-up question (why AL2023 is excluded) also got a technical answer — proceeding with the procedure unmerged risks data corruption, so the exclusion is technically sound |
| B | The procedure's `iopolicy` check value (`round-robin`) versus measured (`queue-depth`). The version boundary is `nvme-cli` 2.11->2.12 | Version difference, not a documentation error | The cause was agreed to be a version difference, with a status update promised after internal review |
| Part 2 | Second-generation sustained writes exceed the published value that should apply to the provisioned value, at both points measured | Gap between published value and measurement | Confirmed that the "up to a third" figure is a sizing indicator, not a hard limit, since writes use bandwidth twice over (active server plus standby sync) and burst capacity can exceed it. For sizing, the original rule of thumb applies: provision three times the required write throughput |
| Part 2 | ap-northeast-1's NVMe read cache capacity is missing from the table, and the management page is written scoped to second-generation only | Missing content (two places) | No documentation change is planned. Enumerating every corner case was judged impractical; `system node external-cache show` was pointed to for individual checks |

## Not filed (3 items)

| Article | Finding | Why not filed |
|---|---|---|
| A | Sizing session count by dividing required bandwidth by 5 Gbps (~625 MBps) doesn't match measurement | AWS never states a formula. The division is a sizing approach the author built, not a documentation finding |
| Part 2 | The observation that raising SSD IOPS made reads 7.14x faster didn't square with "SSD IOPS is used only for reads not served from cache" | Settled by re-measuring. With the working set at 2.15x the cache, it squares with the documentation (ratio came out 4.86x; 7.14x doesn't reproduce). Not a documentation error — it was a measurement gap |
| C | The `nvmf_lif` counter table returns zero rows even after writing 600 GiB | ONTAP-side behavior, not an AWS documentation matter. A vendor (NetApp) question |

**C has no findings beyond this.** What it contains is the author's own measurement errors and
measurements the published spec doesn't explain, neither of which claims the documentation is wrong.

## Breakdown by article

| Article | Filed | Not filed | No findings |
|---|---|---|---|
| A: Session and queue counts | 1 | 1 | — |
| B: Checking whether multipathing is available | 3 | — | — |
| C: What moves the numbers | — | 1 | Yes |
| S3 Burst Part 2 | 2 | 1 | — |

## Discipline for updating this

**Filing is not publication.** Don't write "fixed" in an article until you've confirmed the
documentation actually changed. Once confirmed, add it to the article with a date.
**This index mirrors each article's state; the primary record is the article.** Don't update the
index while leaving the article stale.

## Related documents

| Document | Content |
|---|---|
| [Considerations when measuring FSx for ONTAP's block protocols](block-protocol-testing-guide.md) | Pitfalls to check before measuring |
| [Per-protocol measurement results](../../ja/verification/perf-matrix-results.md) (Japanese) | Measurement records |
| [Verification status](../verification-status.md) | Stage of each claim |

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/block-protocol-aws-feedback-status.md) | [English](block-protocol-aws-feedback-status.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
