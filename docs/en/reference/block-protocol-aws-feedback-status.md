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

| Article | Finding | Category | Status (checked 2026-09-21) |
|---|---|---|---|
| A | `JunctionPath`'s body and `Required:` column disagree ([API reference](https://docs.aws.amazon.com/fsx/latest/APIReference/API_CreateOntapVolumeConfiguration.html), propagates into CloudFormation and the CDK) | Self-contradiction in the documentation | Under investigation. AWS's first reply only |
| B | "Aside from installing packages, valid for other EC2 Linux AMIs" against `cat /etc/nvme/hostnqn` being absent on AL2023 | Counterexample outside the stated scope | AWS confirmed the observation and filed it as documentation feedback. Fix timing undecided |
| B | Same statement against `cat /sys/module/nvme_core/parameters/multipath` being absent on AL2023 (`CONFIG_NVME_MULTIPATH` unset) | Counterexample outside the stated scope | AWS confirmed the observation and filed it. An accompanying clarifying question (which distributions were in scope) has been resolved |
| B | The procedure's `iopolicy` check value (`round-robin`) versus measured (`queue-depth`). The version boundary is `nvme-cli` 2.11->2.12 | Version difference, not a documentation error | AWS agreed the cause is a version difference. Checking with the internal team, promised a status update |
| Part 2 | Second-generation sustained writes exceed the published value that should apply to the provisioned value, at both points measured | Gap between published value and measurement | No reply |
| Part 2 | ap-northeast-1's NVMe read cache capacity is missing from the table, and the management page is written scoped to second-generation only | Missing content (two places) | No reply |

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
| B: Checking whether ANA is available | 3 | — | — |
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
