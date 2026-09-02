# Changelog

Notable additions and corrections. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**Record every stage change here, in both directions.** This repository restates facts it does not
own — support status, limits, Region coverage — and a reader who designed against an earlier version
needs to know which claim moved and why. A claim that was lowered matters as much as one that was
raised: the first tells a reader to stop relying on something.

Entries begin at the point this file was added. Anything earlier is in `git log`, which is where it
was recorded at the time; back-filling it now would be writing history from the diffs rather than
from what was known.

## [Unreleased]

### Added

- **The Region pairs are now checked against AWS's page instead of being maintained by hand.**
  `tools/check_interconnect_regions.py` retrieves
  [Regional Availability](https://docs.aws.amazon.com/interconnect/latest/userguide/region-availability.html)
  and compares it against the table in both languages, reporting an added pair, a withdrawn pair and
  a moved lifecycle as three separate findings. Run by `make interconnect-regions` and weekly by
  `.github/workflows/interconnect-regions.yml`, which files one issue and does not block a pull
  request — the change that trips it is someone else's, and a gate that can turn red on an unrelated
  pull request teaches contributors to ignore red. It is deliberately outside `make all`, recorded in
  `NOT_IN_ALL` with that reason.
  **Every way of coming back empty exits non-zero**: the request failing, the page parsing to zero
  pairs, and a document whose table cannot be found. Each was confirmed to fail before the check was
  trusted. A retrieval failure reported as "no divergence" is how this class of check goes quiet and
  stays quiet, which is the failure the Azure correction below was caused by.
- **`AWS Interconnect – last mile` is named, and separated from the three ways of building a
  cloud-to-cloud connection.** It brings a carrier circuit to AWS rather than joining two CSPs, so it
  is not in the classification tables. Documented, not measured here.
- **`docs/agent/policy-in-code.md` now states that an empty result and an unreadable source are
  different answers**, with the rule for any check added later: decide what the absence of findings
  means before writing the success message.
- **This file.**

### Changed

- **Azure moved from "planned" to Preview across every statement that asserted otherwise.** AWS added
  Azure to AWS Interconnect – multicloud in 2026-08 with four pairs (us-east-1, us-west-1,
  eu-central-1, ap-southeast-2), and the product page now reads "Microsoft Azure (Preview)".
  Four places said it was neither GA nor Preview: the overview table, the "planned" table, the
  selection steps, and the state of the Japanese Regions. The pairs table gained a lifecycle column
  so the distinction sits per row, the "planned" section now says none at present rather than being
  deleted, and the cross-cloud diagram draws Azure reaching the managed frame with the edge labelled
  Preview — while keeping its partner-route edge, because dropping that would say a Preview is a
  substitute for a GA path.
  **A pair being listed is not the same as that pair being GA**, and the selection steps now say so.
  No Japanese pair was added.
- **Azure's connectivity options are two managed services, not one.** Microsoft's facing service,
  Azure Multicloud Interconnect, is recorded with **how weak its sources are**: two Microsoft blogs,
  and no mention on Microsoft Learn's cross-cloud design guide. Its published figures — up to
  100 Gbps, a path extending to Azure Private Link — describe GA, not the Preview, and are marked as
  blog-only.

- **The overview figure now draws the connectivity layer the FlexCache link runs over.** The edge
  crossed from the AWS boundary to the cache site with nothing on it, and a reader asked where AWS
  Interconnect was. It is drawn as a frame naming the three cases — same Region: VPC peering;
  cross-Region: VPC peering / Transit Gateway / Cloud WAN; on-premises: Direct Connect /
  Site-to-Site VPN — rather than as one product icon, which would read as a requirement, and a
  Direct Connect icon in particular would imply a circuit the same-Region case does not need.
  A note states that **AWS Interconnect – multicloud is not this link**: it joins AWS to another CSP,
  and no other cloud appears in that figure. `AWS Interconnect – last mile` is named there as one way
  to obtain the on-premises circuit. Both published posts embed the figure from `main`, so the picture
  changed with the merge.

### Fixed

- **The physical-link encryption of AWS Interconnect – multicloud was stated more definitely than the
  sources support.** The product page names no standard. MACsec is named only by an AWS executive
  quoted on a Microsoft blog, which is a public statement but not service documentation, so the two
  now appear as separate rows with that difference stated. Added to
  `docs/ja/verification-status.md` as unconfirmed.
- **`llms.txt` kept telling crawlers that Azure support was "coming later in 2026" and neither GA nor
  Preview**, after the documents had been corrected. It was missed because the search that found the
  other occurrences was restricted to `*.md`, which excludes `llms.txt` — the scan range is part of
  the result.
- **Two blog drafts were sitting in the published-copy naming scheme without ever having been
  published.** `make blog-sync` asks for a `published-body-sha256:` marker on every
  `.private/blog-draft-*.md`, and the drafts of the ONTAP interoperability measurements had none. The
  marker is the digest of the body *as published*, so adding one would have asserted a publication
  that has not happened and silenced the check while the two bodies stayed apart. Renamed to the
  `blog-unpublished-` prefix the repository already uses for exactly this, which is outside the glob.
