# 差分論点台帳 — TR 記載と FSx for ONTAP 実装の差分

この台帳は、NetApp ONTAP の Technical Report（TR）に書かれた指針・性質と、
Amazon FSx for NetApp ONTAP（以降 FSx for ONTAP）の実装・公開ドキュメントとの間に差分の可能性がある点を、1 件 1 論点で
記録したものである。要件 7「TR と FSx for ONTAP 実装との差分整理」に対応する。

目的は、改善要望（フィードバック）と利用促進の論点を、未検証の断定を避けながら提示することである。
TR 側の参照と FSx for ONTAP 側の出典の両方がそろう論点のみを「確定済み」とし、片方しかない論点は
「未完了」、差分の有無を実測も公式記載も確認できない論点は「未確認」とする。未確認の論点では、
確定形（「〜である」「〜できない」「〜に限る」等）を使わない（要件 7.3）。

## 列構成

| フィールド | 内容 |
|---|---|
| `tr_reference` | TR 側の該当箇所（文書名と節または行の参照）。節番号を特定できていない場合はその旨を記す |
| `fsxn_source` | FSx for ONTAP 側の出典（公式ドキュメント URL または実測結果の識別子） |
| `status` | 確定済み / 未完了 / 未確認 のいずれか一つ |
| `perspective` | 改善要望 / 利用促進 / 両方 のいずれか（未分類を残さない） |

## 差分論点

| 論点 | tr_reference | fsxn_source | status | perspective |
|---|---|---|---|---|
| 高ファイル数ワークロードの TR はオンプレミス ONTAP を主な前提に書かれており、FSx for ONTAP 固有のサイジング手順（第一世代/第二世代のスループット構成との関係）が TR 側に明示されていない可能性がある | High File Count NAS Workloads TR（節番号は特定できていない） | FSx for ONTAP の[スループット構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/)側に該当記述があるか未確認 | 未確認 | 利用促進 |
| FlexCache の対応構成について、AWS は FSx for ONTAP を Origin とする構成を 3 通りに明記しているが、TR 側（FlexCache and FlexGroup volumes）はより広いプラットフォーム組み合わせを前提に記述している可能性があり、FSx for ONTAP で検証されていない組み合わせを区別する必要がある | FlexCache and FlexGroup volumes TR（節番号は特定できていない） | [FSx for ONTAP の FlexCache 対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)（3 通りを明記） | 確定済み | 利用促進 |
| S3 Access Points 経由の操作では FPolicy 通知が発火せず、`mandatory` 同期ポリシーでも遮断されない。TR（S3）および Security TR が FPolicy をデータ保護・監視の手段として記述している場合、この収集経路には適用できない点を区別する必要がある | S3 TR / Security TR（節番号は特定できていない） | [FPolicy の S3 Access Point 経路に関する実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/errata-fpolicy-s3ap-coverage.md)（この repo の[検証状況](../../verification-status.md)で検証済み） | 確定済み | 改善要望 |
| S3 Access Points の対応表は `Presign` を非対応としているが、実測では `PutObject` / `HeadObject` / `GetObject` の presigned URL が成功した。対応表と実測が逆向きである | — | [presigned URL の実測記録](../../verification/s3ap-operations.md)（2026-08-19）。TR 側に対応する記述を特定できていない | 未完了 | 改善要望 |
| S3 Access Points のアップロード上限は 50 GiB だがダウンロードは上限なしという非対称性があり、NFS/SMB で書いた 50 GiB 超のファイルを S3 で読める。TR 側（S3）にこの非対称性に対応する記述があるか未確認 | S3 TR（節番号は特定できていない） | [オブジェクトサイズ上限の実測](../limits/s3-access-point.md#上限がアップロード側にしかないこと)（検証済み、2026-09-11） | 未確認 | 利用促進 |
| FlexCache の Cache 側は Snapshot・SnapRestore・FlexClone・SnapMirror がいずれも不可で、データ保護を Origin 側にしか置けない。TR（FlexCache and FlexGroup volumes / Data protection）がこの制約を Origin/Cache で区別して記述しているか確認が必要 | FlexCache and FlexGroup volumes TR / Data protection TR（節番号は特定できていない） | [Origin/Cache の対応可否一覧](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html)（この repo の[サポート状況](../../support-matrix.md)に転記済み） | 確定済み | 利用促進 |

## ステータスの内訳と扱い

- 確定済み: 3 件 / 未完了: 1 件 / 未確認: 2 件（合計 6 件）
- 観点が未分類の論点は残していない（要件 7.4）。
- 未完了の 1 件（presigned URL）は、FSx for ONTAP 側の実測は存在するが、対応する TR 側の該当箇所を
  特定できていない。TR 側参照が欠落しているため確定済みに分類しない（要件 7.2）。TR 本文で該当節を
  特定できた時点で status を更新する。
- 未確認の 2 件は、差分の有無を実測も公式記載も確認できていない。断定形を使わず「可能性がある」
  「未確認」の表現に留めている（要件 7.3）。公式記載または実測が得られた時点で status を更新する。

## 識別子の扱い

本台帳には、ベンダー内部チケットID・サポートケース番号・ベンダー内部製品ID を記載しない。
これらが論点の経緯に関わる場合は「内部の製品要望（追跡中）」等の中立表現に置換し、数値を含む元の
識別子を残さない（要件 7.5、要件 6.3）。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [スコープ台帳](scope-ledger.md) | TR のスコープ内外の判定 |
| [委任台帳](delegation-ledger.md) | TR 由来知見の作業主体判定 |
| [検証状況](../../verification-status.md) | 評価段階の定義と現在の状態 |
| [サポート状況](../../support-matrix.md) | 収集層・配布層の対応状況と制約 |
