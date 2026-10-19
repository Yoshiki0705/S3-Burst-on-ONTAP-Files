# 検証記録 — Amazon S3 Files の請求数量と CloudWatch 指標の突き合わせ

<!-- ontap-version-exempt-file: this record reconciles Amazon S3 Files billing quantities
     against CloudWatch metrics; ONTAP is not involved in the quantity measured here. -->

**この記録は、別々の日に測った 2 件の測定について、CloudWatch の `AWS/S3/Files` 指標の合計と、
Cost Explorer の請求側の使用量を突き合わせた結果である。** 突き合わせたのは数量であって、
請求書ではない。Cost Explorer の値はすべて `Estimated: true` で、各行に同額の `Credit` 行
（マイナス）があり、正味の請求額は 0 だった。つまり使用量と単価は計上されているが、金額は
クレジットで相殺されている。したがって「CloudWatch のバイトの合計が、請求の読み取り数量に
一致した」までが言え、「請求額が確認できた」とは言えない。

2 件の測定は、どちらも既に記録済みの測定である。10-16 はメタデータ課金の測定（4 MiB の
オブジェクトの読み取りに `MetadataReadBytes` が立つか）、10-17 はアクティブ割合の測定
（[`StorageBytes` 増分と作業セット比](s3files-active-ratio-measured.md)、以下 M-A）。

## 検証環境

| 項目 | 値 |
|---|---|
| 突き合わせの実行日 | 2026-10-19（読み取りのみ。AWS の状態は変更していない） |
| 対象の測定 | 2026-10-16 のメタデータ課金測定、2026-10-17 の M-A（別々の日、別々の測定） |
| リージョン | ap-northeast-1 |
| メタデータ課金測定の実行環境 | m5.large |
| 請求側の取得元 | Cost Explorer（us-east-1 エンドポイント） |
| CloudWatch 側の取得元 | `AWS/S3/Files` の `MetadataReadBytes`、`DataReadBytes`、`MetadataWriteBytes`、`DataWriteBytes`、`StorageBytes` |
| アカウント ID / ファイルシステム ID | この記録では伏せる（公開物のため。プレースホルダも置かない） |

この期間にこのアカウントで S3 Files を使ったのは、上の 2 件の測定だけである。

## 請求側の取得クエリ

| 項目 | 値 |
|---|---|
| エンドポイント | Cost Explorer の us-east-1 |
| 操作 | `get-cost-and-usage` |
| 期間 | 2026-10-14 〜 2026-10-20（End は排他） |
| 粒度 | 日次 |
| メトリクス | `UsageQuantity`、`UnblendedCost` |
| グループ化（1 回目） | `USAGE_TYPE` |
| グループ化（2 回目） | `USAGE_TYPE` に `RECORD_TYPE` を足し、`Usage` と `Credit` を分けた |
| タグ条件 | 付けていない。タグが配分タグとして有効かは未確認のため、使用量種別だけで見た |

`Files` を含む使用量種別は、2026-10-16 と 2026-10-17 の 2 日だけに出た。他の日には出ていない。
すべて `Estimated: true`。

## 請求側の値

`RECORD_TYPE=Usage` の行。数量の単位は Cost Explorer の表記が GB（読み取りと書き込み）と GB-Month（保管）
で、下の突き合わせでは 2^30 B として換算した。10^9 B として換算すると比は変わる（10-16 は 1.068）。

| 日 | 使用量種別 | UsageQuantity | UnblendedCost（USD） | 数量あたり単価 |
|---|---|---|---|---|
| 10-16 | `APN1-Files-Read` | 0.1165046692 GB | 0.0046601868 | 0.04 USD/GB |
| 10-16 | `APN1-Files-Write` | 0.07633209 GB | 0.0053432463 | 0.07 USD/GB |
| 10-16 | `APN1-Files-TimedStorage-ByteHrs` | 0.0001284358 GB-Month | 0.0000462369 | 0.36 USD/GB-Month |
| 10-17 | `APN1-Files-Read` | 3.24599361 GB | 0.1298397444 | 0.04 USD/GB |
| 10-17 | `APN1-Files-Write` | 5.2583160401 GB | 0.3680821228 | 0.07 USD/GB |
| 10-17 | `APN1-Files-TimedStorage-ByteHrs` | 0.02176555 GB-Month | 0.007835598 | 0.36 USD/GB-Month |

各行に同額の `Credit` 行（マイナス）があり、正味は 0 である。単価 0.04 / 0.07 / 0.36 は、
[FinOps の費用構造](../reference/comparison/finops-s3-vs-s3ap.md)のモデル（`S3FILES` の read / write / storage）
が使う単価と同じ値である。

## 2026-10-16 の突き合わせ

メタデータ課金測定の、窓ごとの表の「合計」行から CloudWatch の Sum を足した。

| 項目 | バイト数 |
|---|---|
| `MetadataReadBytes`（6 窓の合計行: 451,476 + 24,758,796 + 24,750,604 + 8,346,124 + 36,864 + 158,684） | 58,502,548 |
| `DataReadBytes`（64 KiB の対照 1,000 個の読み取り。4 MiB の読み取りでは 0） | 65,972,000 |
| CloudWatch の合計 | 124,474,548 |
| 請求側 `APN1-Files-Read` 0.1165046692 を GiB（2^30）として換算 | 125,095,936 |

CloudWatch の合計 ÷ 請求は **0.995**（GB を 10^9 B として換算すると 1.068）。
`MetadataReadBytes` だけでは 0.468、`DataReadBytes` だけでは 0.527 にしかならない。
どちらか片方だけでは請求の数量を説明できず、両方を足すと 0.5% 以内で一致する。
4 MiB の読み取り（1 MiB I/O と 4 MiB I/O の両方）の `MetadataReadBytes` が、
請求の `APN1-Files-Read` に含まれていると読める。

書き込み側は合わない。請求の 0.07633209 GiB は 81,960,958 B にあたる。一方 CloudWatch の
`DataWriteBytes` は 0、`MetadataWriteBytes` は 12,288 B しかない。取り込み（高性能ストレージ
への書き込み）は CloudWatch の書き込み指標には出ず、請求の `APN1-Files-Write` には出ている。

## 2026-10-17 の突き合わせ

M-A の記録から取った。

| 項目 | 値 |
|---|---|
| FS-A の `DataReadBytes` 合計 | 2.46 GiB |
| `MetadataReadBytes` 合計（FS-A と FS-B） | 約 0.77 GiB |
| FS-B の `DataReadBytes` | CloudWatch に出ていない |
| CloudWatch の合計 | 約 3.23 GiB |
| 請求側 `APN1-Files-Read` | 3.246 GiB（比 約 0.995） |
| 請求側 `APN1-Files-Write` | 5.258 GiB |
| 取り込み量の見積り | 最大 `StorageBytes` 合計 5.42 GiB から読み取り前のベースラインを引いた量。請求の書き込みはこれの約 0.97 |
| 請求側 `APN1-Files-TimedStorage-ByteHrs` | 0.02176555 GB-Month（約 15.9 GiB-時間） |
| 保管の見合い | 2 つのファイルシステムの `StorageBytes`（最大 約 2.9 GiB ずつ）を数時間保持した量と桁が合う |

書き込みは 10-16 と同じく、CloudWatch の `DataWriteBytes` / `MetadataWriteBytes` に取り込み分が出ていない。
保管は時間積分での厳密な突き合わせをしていない。

## 言えること

1. 読み取りの請求数量は、`DataReadBytes` と `MetadataReadBytes` の合計に一致した（2 日、別々の測定、0.5% 以内）。
2. 4 MiB（と 1 MiB I/O）の読み取りの `MetadataReadBytes` は、請求の数量に含まれる。観測は 4 MiB のオブジェクトに限り、
   1 MiB と 16 MiB のオブジェクトは読んでいない。
3. 取り込みは `APN1-Files-Write` として計上される。CloudWatch の書き込み指標には出ない。
4. 単価は 0.04 / 0.07 / 0.36 で、モデルと同じ。
5. FS-B で `DataReadBytes` が CloudWatch に出なかったことは、請求の数量とも整合する（FS-B のデータ読み取りは
   請求にも載っていない）。

## 言えないこと

- 読み取り 1 回あたり約 6 回（4 MiB）の内訳（open / getattr 等）。
- 他のインスタンス型、`nconnect`、複数プロセス、他のオブジェクトサイズ。
- 書き込みの数量が `StorageBytes` の増分と一致する厳密な関係（M-A で約 0.97 まで）。
- `ImportFailures` 約 200,000 件の請求への影響。書き込みの数量が `StorageBytes` の増分に近いので、
  失敗した取り込みが大きく課金されている形跡はないが、切り分けていない。
- 請求額そのもの。クレジットで相殺されて正味 0 で、`Estimated: true` である。

## 証拠の段階

| 主張 | 段階 | 根拠 |
|---|---|---|
| 読み取りの請求数量が CloudWatch の合計に一致する | 検証済み（2 日、各 1 回の観測） | 名前を付けた環境（ap-northeast-1）での、別々の 2 測定の突き合わせ |
| 4 MiB のオブジェクトの読み取りに `MetadataReadBytes` が立ち、請求に含まれる | 検証済み（1 環境: m5.large、1 MiB I/O と 4 MiB I/O） | 上の 10-16 の表 |
| 取り込みが `APN1-Files-Write` で請求される | 検証済み（2 日） | 両日とも請求の書き込みがあり、CloudWatch の書き込み指標には取り込み分が出ない（10-16 は 81,960,958 B に対し 12,288 B） |
| 保管の請求が `StorageBytes` の時間積分に一致する | 未検証 | 桁が合うことまで。時間積分は未実施 |
| 請求額 | 確認していない | `Estimated: true`、クレジットで相殺され正味 0 |

**一致したのは、CloudWatch のバイトの合計と、請求の使用量である。** 請求書ではない。
Cost Explorer の値は推定で、確定した請求とは限らない。

## この記録の限界

**CloudWatch の合計は、突き合わせの時点で CloudWatch から取り直したものではなく、各測定の記録にある
段階ごとの表から足したものである。** したがって、表の転記に誤りがあれば、その誤りは突き合わせにも入る。
10-17 の値は記録にある概数（「約」）から割り算しており、桁の小さい差は読み取れない。

## 残る未確認

| 項目 | 状態 |
|---|---|
| 保管（`APN1-Files-TimedStorage-ByteHrs`）が `StorageBytes` の時間積分に一致するか | 未確認。桁が合うことまで |
| `ImportFailures` 約 200,000 件が請求に与える影響 | 未確認。切り分けていない |
| FS-B で `DataReadBytes` が CloudWatch に出なかった理由 | 未確認。請求の数量とは整合するが、CloudWatch に出ない理由は調べていない |
| 4 MiB の読み取り 1 回あたり約 6 回の内訳 | 未確認 |
| 他のインスタンス型、`nconnect`、複数プロセス、他のオブジェクトサイズ | 未測定 |

## FinOps モデルとの関係

この記録はモデルの数値を変えない。モデルの既定は、読み取り 1 回あたりメタデータ 1 操作 × 4 KiB、
高性能ストレージのアクティブ割合 100% のままである。観測した 4 MiB の約 6.0 回 × 約 4.1 KiB
（1 環境、1 回の観測）は、感度節の `metadata_multiplier` で試算できる。既定を動かすには、
他のインスタンス型やオブジェクトサイズでの反復が要る。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [S3 Files の `StorageBytes` 増分と作業セット比](s3files-active-ratio-measured.md) | 10-17 の測定（M-A）。`StorageBytes` の増分と、その課金側の位置づけ |
| [FinOps の費用構造](../reference/comparison/finops-s3-vs-s3ap.md) | メタデータ課金とアクティブ割合の前提、単価の出どころ |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
