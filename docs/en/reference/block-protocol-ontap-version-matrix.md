# ONTAP version matrix for the block protocol articles

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/block-protocol-ontap-version-matrix.md) | [English](block-protocol-ontap-version-matrix.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Collects, in one place, which ONTAP version each measurement in the three block protocol
measurement articles and S3 Burst Part 2 was taken against. **Some measurements have no
recorded version, and one article's measurements span more than one version — both are stated
explicitly in the source article. This document is an index across articles and doesn't
override what each article says.**

## Mapping by article

| Article | Measurement | ONTAP version | Note |
|---|---|---|---|
| A: Session and queue counts | Divisor table (3 points) | 9.18.1P5 | — |
| A: Session and queue counts | Queue-negotiation section | Not recorded | Separate deployment; not read at measurement time and can't be retaken |
| B: Checking whether ANA is available | Match table's reads and writes | 9.18.1 | — |
| B: Checking whether ANA is available | Sequential writes (12 points) | Not recorded | `FileSystemTypeVersion` returned `null`; the environment was torn down before it could be re-fetched from the cluster API |
| C: What moves the numbers | Initial deployment | 9.18.1P5 | — |
| C: What moves the numbers | Per-path measurement | 9.18.1P6 | — |
| C: What moves the numbers | Later three deployments | 9.18.1 | — |
| S3 Burst Part 2 | Main measurement environment (2026-09-01 and 09-02) | 9.18.1P3D1 | — |
| S3 Burst Part 2 | Second-generation NFS 2-host measurement | 9.18.1P6 | A different version from the main measurement environment |

## The version spread C itself names as a candidate

Article C wasn't measured against one ONTAP version. It spans 9.18.1P5 (initial deployment),
9.18.1P6 (per-path measurement), and 9.18.1 (the later three deployments). **The article itself
names this version spread as one of the unresolved candidates left at its end, alongside the
other candidate (the client used for measurement) — it states this is a list of candidates,
not a settled cause.** No additional measurement was taken to isolate which candidate is
responsible.

## Limits of this table

- **Each article's own measurement-conditions table is the primary source.** This table pulls
  out only the version; other conditions (file system generation, throughput capacity, SSD
  configuration, and so on) are in each article.
- **A measurement with no recorded version isn't rewritten to match a version that was
  recorded elsewhere.** "Not recorded" states a fact about what was captured, not that the
  measurement is invalid.

## Related documents

| Document | Content |
|---|---|
| [Considerations when measuring FSx for ONTAP's block protocols](block-protocol-testing-guide.md) | Pitfalls to check before measuring |
| [Per-protocol measurement results](../../ja/verification/perf-matrix-results.md) (Japanese) | Measurement records |
| [Verification status](../verification-status.md) | Stage of each claim |

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/block-protocol-ontap-version-matrix.md) | [English](block-protocol-ontap-version-matrix.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
