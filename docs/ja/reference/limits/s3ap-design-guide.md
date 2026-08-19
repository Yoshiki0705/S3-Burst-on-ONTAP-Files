# S3 Access Point — 設計ガイド（収集層の詳細）
<!-- lang-switcher:start -->
🌐 [日本語](s3ap-design-guide.md) | [English](../../../en/reference/limits/s3ap-design-guide.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->

<!-- 出典: 姉妹リポジトリ FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns の設計考慮事項・互換性ノート・
     性能考慮事項を、この構成の観点でまとめ直したもの。
     https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns -->

この構成の収集層（S3 Access Point）を設計する際に知っておくべき詳細を記載する。
上限値は[別ページ](s3-access-point.md)、構成全体は[構成の形](../../architecture.md)を参照。

## 対応 S3 オペレーション

FSx for ONTAP の S3 AP が対応するのは S3 API の一部である。Amazon S3 と同一ではない（[対応表](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)）。

### 動作確認済み

| オペレーション | 備考 |
|---|---|
| GetObject | Range GET 対応。ダウンロードにサイズ上限なし |
| PutObject | 単一 PUT は 5 GiB まで |
| ListObjectsV2 | Prefix / Delimiter / MaxKeys 対応 |
| HeadObject | — |
| DeleteObject | — |
| MultipartUpload | CreateMultipartUpload / UploadPart / CompleteMultipartUpload |
| CopyObject | 同一 AP 内・同一リージョンのみ。`x-amz-object-annotation-directive` ヘッダーは非対応（[対応表](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)） |

### 非対応（エラーが返る）

| オペレーション | 返却 | 代替手段 |
|---|---|---|
| 条件付き書き込み（If-None-Match） | 501 NotImplemented | アプリケーション側の排他制御 |
| S3 Annotations（PutObjectAnnotation 等） | 501 NotImplemented | 標準 S3 バケットに出力して annotation 付与 |

### 条件つきで対応

| オペレーション | 条件 | このリポジトリでの状態 |
|---|---|---|
| UploadPartCopy | 対応表は同一 AP 内・同一リージョンのみ対応と記載 | **同一 AP 内をソースにして実測したところ `NoSuchKey` を返した**（[検証記録](../../verification/s3ap-operations.md)、2026-08-19）。**同一の `CopySource` を与えた `CopyObject` は同一実行内で成功しており**、対照が取れている。測定は対応表と逆向き。ただし**このエンドポイントでコピーが成立する別のソース名前空間が無いため、`UploadPartCopy` そのものが非対応なのかは判定できない**（別 AP 経由は `CopyObject` でも拒否される）。先の「同一 AP 内に無いソースで `404 NoSuchKey`」という 1 回の観測は、**別 AP では `InvalidArgument` になったため帰属が合わない** |

### 機能として存在しない

| 機能 | 代替手段 |
|---|---|
| S3 Event Notification | FPolicy + EventBridge、またはポーリング |
| ライフサイクルルール | FabricPool / ONTAP Tiering Policy |
| バージョニング | ONTAP Snapshot |
| Object Lock / WORM | SnapLock Compliance / Enterprise |
| S3 Select | Athena + Glue Data Catalog |
| SSE-S3 / SSE-KMS | NAE / NVE（ONTAP ボリューム暗号化） |
| Cross-AP Copy | DataSync / rsync |

### Presigned URL

**公式対応表は現時点で `Presign — Not supported` と記載している**（[対応表](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)）。

一方で、presigning はクライアント側の署名計算であってサーバーへの API 呼び出しではない。
生成された URL が実行するのは通常の `GetObject` で、署名が Authorization ヘッダーではなく
クエリパラメータに入るだけである。`GetObject` は対応済みなので、`GetObject` 自体を壊さずに
presigned URL 経由だけを止めることはできない。姉妹リポジトリでは `GetObject` の presigned URL が
成功することを実測している（ONTAP 9.18.1P3D1）。ONTAP のバージョン別のサポート範囲は
NetApp KB に記載がある（9.11.1 以降で v4、9.16.1 以降で v2 + v4）。
機構の説明、バージョン要件、代替手段の一覧は
[姉妹リポジトリの互換性ノート](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/s3ap-compatibility-notes.md)にある。

**公開ドキュメントが `Not supported` としている間は、本番ワークロードを依存させない。**
非推奨通知なしに挙動が変わる可能性がある。時間制限つきのアクセスが必要なら、
API Gateway + Lambda、CloudFront signed URL、一時的な STS 認証情報のいずれかを設計する。
**`PutObject` と `HeadObject` も実測した**（[検証記録](../../verification/s3ap-operations.md)、
2026-08-19）。`GetObject` を含む 3 つとも成功し、SigV4 と SigV2 の両方で動作した。
NetApp KB のバージョン別記載（9.11.1 以降で v4、9.16.1 以降で v2 + v4）と整合する。
**対応表が `Not supported` としている間は依存させないという上記の判断は変えない。**
動作したことは、非推奨通知なしに挙動が変わらないことの保証ではない。

**SigV2 は Content-Type を署名対象に含めるため、クライアントが自動で付けたヘッダーで署名が
無効になる。** SigV4 の既定の署名対象は `host` だけなのでこの影響を受けない。
boto3 では署名バージョンを明示する必要がある — 明示しない `generate_presigned_url` は
SigV2 を生成し、`client.meta.config.signature_version` はどちらの場合も `s3v4` を返すため
報告値では判別できない（クライアント側の挙動であり、FSx for ONTAP の性質ではない）。

この構成の経路では presigned URL を使わない。

## 並行度とスループットの設計

**S3 AP、NFS、SMB はすべて同じ FSx for ONTAP プロビジョンドスループットを共有する。**
収集層（S3 AP 書き込み）と配布層（FlexCache NFS/SMB 読み取り）が同じファイルシステム上に
ある場合、帯域の取り合いが発生する。この構成では Origin と Cache が別クラスタなので
通常は問題にならないが、**Origin クラスタに直接 NFS アクセスするクライアントがいる場合**は
スループット分配を考慮する。

### 並行度の決め方

**このリポジトリに並行度の実測はない。** 出発点になるのは次の関係だけである。

```text
最大並行度 ≈ プロビジョンドスループット ÷ 1 リクエストあたりの消費帯域
```

1 リクエストあたりの消費帯域は、オブジェクトサイズと 1 リクエストの所要時間から出す。
どちらも自分のワークロードで測る必要があり、スループット段からは導出できない。

決め方は次の順序になる。

1. 代表的なオブジェクトサイズで、並行度 1 のときの所要時間とスループットを測る
2. 並行度を上げながら、`SlowDown`（503）の発生率と p99 を記録する
3. 発生率が許容範囲を超える手前を上限とする

**NFS/SMB の既存ワークロードがある場合は、その分を差し引いて設計する。**

### スループット飽和時の挙動

FSx for ONTAP のスループットが飽和すると S3 API は `SlowDown` (503) を返す。
Exponential backoff（base: 1 秒、max: 30 秒）で対処する。
boto3 の `adaptive` retry mode が推奨。

## ディレクトリ設計

### 1 ディレクトリあたりのファイル数

**上限を決めているのはボリュームの `maxdir-size` である。** ディレクトリがこの値に達すると、
クライアントには領域不足（`ENOSPC`）が返り、ファイルを作れなくなる。値はボリュームごとの設定で、
`volume modify -maxdir-size` で増やせるが、**増やすと性能に影響する可能性があるとドキュメントに
明記されている**（[最大ディレクトリサイズ](https://docs.netapp.com/us-en/ontap/volumes/cautions-increasing-maximum-directory-size-concept.html)）。

したがって設計時に確認するのは 2 つである。

1. **対象ボリュームの現在の `maxdir-size`。** 既定値は ONTAP のバージョンとシステムメモリに依存する
2. **1 ディレクトリに入るエントリ数の見込み。** エントリ数が増えると `readdir` と
   `ListObjectsV2` の応答時間が伸びる

**このリポジトリにエントリ数と応答時間の実測はない。** 件数のしきい値を持たないのはそのためで、
自分の環境で `maxdir-size` を確認し、想定エントリ数がその手前に収まる粒度まで分割する。

### 推奨パーティション設計

この構成の収集層では、S3 PutObject のキーがディレクトリ構造に直結する。

```text
# Hive-style 日付パーティション（推奨）
s3://<ap-alias>/data/year=2026/month=08/day=10/sensor_001.json

# テナント + 日付ハイブリッド
s3://<ap-alias>/tenant-a/2026/08/10/report.pdf

# ハッシュバケット（大量の均一ファイル）
s3://<ap-alias>/objects/a3/b2/object-uuid-001.bin
```

### アンチパターン

| やってはいけないこと | 問題 | 対策 |
|---|---|---|
| ルート `/` での全件 LIST | ボリューム全体を走査。数十万件で数十秒〜タイムアウト | Prefix を必ず指定 |
| スラッシュなしのフラットキー大量投入 | 全ファイルがルートディレクトリに集中 | 階層パーティションを使う |
| 再帰的 LIST（Delimiter なし） | 全サブディレクトリを再帰走査 | 階層ごとに LIST |
| 投入ボリュームを FlexCache する | 書き込み先をキャッシュする意味がなく、スループットを食い合う | 投入用と消費用でボリュームを分ける |
| NFS 側で `find /mnt/vol/` | パーティション構造を無視して全走査 | マニフェストまたはパス生成で探索 |

### パーティション粒度の決め方

**1 つのディレクトリに入るエントリ数が `maxdir-size` の手前に収まる粒度まで切る。**
下の表は形の出発点で、**実測に基づく数値ではない。** 自分の投入レートと `maxdir-size` から
必要な分割数を出したうえで使う。

| 投入レート | 出発点になる粒度 | 例 |
|---|---|---|
| 数百件/日 | `year/month/day/` | バッチ投入、レポート |
| 数千件/時 | `year/month/day/hour/` | IoT テレメトリ |
| 数万件/時 | `year/month/day/hour/` + デバイス別 | 大規模 IoT |
| 数十万件/時 | ハッシュバケット 2 桁（256 分割） | UUID ベースのオブジェクト |

## ボリューム設計 — 投入用と消費用を分ける

**S3 キー設計は NFS 側のディレクトリ構造そのものです。** 同じボリュームに大量投入と NFS 読み取りが
同居すると、スループット競合とディレクトリ肥大化が同時に起こる。

### 推奨構成

```text
Origin FS (FSx for ONTAP)
├── vol_ingest_telemetry    ← S3 AP アタッチ（IoT 投入用）
│   └── /year=YYYY/month=MM/day=DD/hour=HH/{device}_{uuid}.json
├── vol_ingest_artifacts    ← S3 AP アタッチ（CI/CD 成果物）
│   └── /{repo}/{branch}/{build_id}/{artifact}
├── vol_shared_data         ← S3 AP アタッチ（設計データ・共有素材）
│   └── /{project}/{version}/{filename}
└── vol_processed           ← NFS only（処理済み、配布用）
    └── /{output_type}/{date}/{result}

Cache Site (FlexCache)
├── fc_shared_data          ← vol_shared_data のキャッシュ
└── fc_processed            ← vol_processed のキャッシュ
    （vol_ingest_* は FlexCache しない）
```

### 設計原則

| 原則 | 理由 |
|---|---|
| 投入用ボリュームは FlexCache しない | 書き込み先をキャッシュする意味がない。スループットの無駄 |
| FlexCache は消費用ボリュームのみ | 必要なデータだけが pull される |
| 投入と消費でボリュームを分ける | スループット競合を避け、それぞれ独立にサイズ/ティアリング設定可能 |
| S3 AP は投入用ボリュームにアタッチ | 消費用は NFS/SMB のみで十分 |

### 投入ボリュームのティアリング

高頻度投入 → すぐに消費 → cold 化するデータには `AUTO` ティアリングが有効。
31 日（デフォルト cooling period）経過したデータは capacity tier に移り、SSD コストを抑える。
FlexCache 側は hot data だけを保持するため、ティアリングの影響を受けない。

## NFS 側のファイル探索戦略

S3 AP で投入されたデータを NFS/SMB で消費する際、ディレクトリを走査するのではなく
**「何が投入されたかを知る仕組み」** を用意する。

### マニフェストパターン（推奨）

投入完了時にマニフェストファイルを書き、NFS 側はそれだけ読む：

```text
# 投入側（Lambda / パイプライン）の最後に
s3://ap-alias/data/year=2026/month=08/day=10/_manifest_14.json
内容: {"files": ["hour=14/sensor_001.json", ...], "count": 42, "timestamp": "..."}

# NFS 側のスクリプト
cat /mnt/cache/data/year=2026/month=08/day=10/_manifest_14.json | jq -r '.files[]'
# → ディレクトリを走査せず、投入されたファイルだけを処理
```

### パス生成パターン

パーティション構造が既知なら、スクリプト側でパスを生成して直接アクセス：

```bash
# 昨日のデータを処理するスクリプト — find を使わない
YESTERDAY=$(date -d "yesterday" +%Y/month=%m/day=%d)
for f in /mnt/cache/data/year=$YESTERDAY/*.json; do
  process "$f"
done
```

### inotifywait / FPolicy イベント

検出の遅れを詰めたい場合は、「ファイルが現れたら処理」のイベント駆動にする。ただし
**`inotify` はこの構成では使えない。** `inotify` はローカルカーネルの VFS を見る仕組みで、
ネットワークファイルシステムを監視している場合、**変更がリモートで行われたイベントは通知されない**
（[inotify(7)](https://man7.org/linux/man-pages/man7/inotify.7.html)）。この構成の書き込みは S3 Access Point 経由で Origin に届き、
Cache は後からそれを取り込むため、Cache をマウントしているクライアントの `inotify` は発火しない。

サーバー側で検出する場合は [FPolicy](https://docs.netapp.com/us-en/ontap/nas-audit/fpolicy-config-types-concept.html)になる。**この構成では未検証である。**
FPolicy が S3 Access Point 経由の書き込みをイベントとして扱うか、Cache 側で発火するかは
確かめていない。検証していない機構を前提に設計しないこと。

ポーリング（定期的な `ls`）はコストがディレクトリのエントリ数に比例して増える。
[ディレクトリあたりのファイル数](#ディレクトリ設計)で分割してあれば実用になる。

## マルチプロトコル一貫性

この構成では「S3 AP で書き、NFS/SMB で読む」のが主経路。逆方向や同時書き込みには注意が必要。

| シナリオ | 動作 | リスク |
|---|---|---|
| **S3 AP PutObject 完了 → NFS/SMB read** | **見えた時点では常に完全なデータ。** ただし反映には時間差がある（同一ボリュームで p50 9 ms、FlexCache 経由で p50 8 ms。[検証記録](../../verification/flexcache-s3ap-visibility.md)） | 低い。これが主経路。**ただしクライアント側のキャッシュが支配的になる**（既定マウントの `acdirmin=30` / `acdirmax=60` では最大 1 分見えないことがある） |
| NFS 書き込み中に S3 AP GET | 書き込み途中のデータが読まれる可能性（部分読み取り） | データ不整合 |
| S3 AP 書き込み + FlexCache write-back で同一ファイル | Cache のダーティデータが破棄される（XLD revoke） | データ競合 |
| NFS rename 直後に S3 AP GET（旧キー） | 旧キーでは NotFound（rename は即座に反映） | アプリ側のキー管理 |

### この構成での安全な使い方

**主経路（S3 AP → FlexCache NFS/SMB）で、中途半端なデータを読むことはない。**
マルチパートアップロードは `CompleteMultipartUpload` まで NFS 側に現れず、単一 `PutObject` も
見えた時点では常に完全なデータである（[検証記録](../../verification/flexcache-s3ap-visibility.md)）。

**「完了と同時に見える」ではない。** サーバ側の反映に数ミリ秒かかり、そのうえで
クライアント側のキャッシュ期限が乗る。既定マウントでは削除の反映に 2,171 ms かかった実測がある
（[同一ボリュームの検証記録](../../verification/s3ap-nfs-visibility.md)）。
鮮度が要件なら `actimeo` を明示する。

**避けるべきパターン:**

- 同一ファイルへの S3 AP 書き込みと NFS/SMB 書き込みの同時実行
- FlexCache の write-back と S3 AP の書き込みが同一ファイルを対象にすること
  （この構成は Cache を読み取り用途に限定しているため、通常は発生しない）

## FlexVol vs FlexGroup の選択

| 判断基準 | FlexVol | FlexGroup |
|---|---|---|
| 最大サイズ | 約 100 TB（実用的上限） | PB スケール |
| ファイル数上限 | 約 20 億 | constituent 数 × 20 億 |
| FlexCache Origin 対応 | ONTAP 9.12.1 以降 | ONTAP 9.13.1 以降（制約あり） |
| S3 AP 対応 | ✅ | ✅ |
| 推奨用途 | 単一ワークロード / PoC | 大規模データ / マルチテナント |
| この構成での推奨 | 検証・小規模から開始 | 本番の大規模データ |

FlexGroup を Origin にした FlexCache では NAS バケットが作成可能（`-is-s3-enabled true` の設定で
[S3 データアクセスも動作する](../../verification/cross-protocol-directions.md)）。

## 読み取り側のコスト設計手順

利用側が AWS の外にいる場合、読み取り側の課金は**データ転送**と**リクエスト**の 2 つで、
効く手が違う。片方だけを見た設計は、もう片方で戻ってくる。
金額の試算は[FinOps の費用構造](../comparison/finops-s3-vs-s3ap.md)にあるので、ここでは手順だけを置く。

### 手順 1 — 4 つの量を押さえる

これが揃わないと判定できない。推測で埋めない。

| 量 | 何を測るか | 測り方の例 |
|---|---|---|
| データセット量 | 保持している論理バイト数 | S3 Storage Lens、`aws s3 ls --summarize`、ボリュームの使用量 |
| 作業セット量 | 1 か月に実際に触るユニークなバイト数 | S3 サーバーアクセスログまたは CloudTrail データイベントから、ユニークキーの合計サイズを出す |
| 平均オブジェクトサイズ | データセット量 ÷ オブジェクト数 | S3 Storage Lens のオブジェクト数 |
| 同一データの読み取り回数 | 同じキーが月に何回読まれるか | アクセスログのキー別 GET 回数の分布。平均ではなく中央値と上位を見る |

読み取り回数は**平均で潰さない**。一部のファイルだけが何百回も読まれる分布はよくあり、
その場合は全体平均ではなく上位のキーで判定する。

### 手順 2 — どちらが支配項か計算する

```text
月間転送量      = 作業セット量 × 読み取り回数
転送料金        = 月間転送量 × 転送単価（インターネットは段階制、DX は定額）

月間リクエスト数 = (作業セット量 ÷ 平均オブジェクトサイズ) × 読み取り回数
リクエスト料金   = 月間リクエスト数 × GET 単価

リクエスト占率   = リクエスト料金 ÷ (転送料金 + リクエスト料金)
```

占率で打ち手が変わる。目安は[FinOps の費用構造](../comparison/finops-s3-vs-s3ap.md)の
「転送とリクエストを同時に見る」の表にある。

| 占率 | 支配項 | 打つ手 |
|---|---|---|
| おおむね 5% 未満 | 転送 | 運ぶバイト数を減らす。作業セットだけを配布側に置く |
| 5〜30% | 転送寄り、ただしリクエストも効く | まず転送、次にオブジェクトのまとめ方 |
| 30% 以上 | 両方 | まとめる（リクエスト）とキャッシュする（転送）の併用。片方では残る |

### 手順 3 — 支配項に応じて設計する

**転送が支配項のとき。** 減らすのはバイト数である。

- 配布側に作業セットだけを置く。全量コピーは作業セットの何倍かを運ぶことになる
- 利用側を AWS に移せるなら、それが最も効く（同一リージョン内は無料）
- Direct Connect で単価を下げる。ポート料金と回線費用が別に載るので、転送量との損益で判断する
- **オブジェクトを大きくしても転送は減らない。** 回数は減るがバイト数は同じ

**リクエストが支配項のとき。** 減らすのは呼び出し回数である。

- 収集の段階でまとめる。1 ファイルを大きくすれば読み出し回数も減る
- 読み出しをファイルプロトコルに寄せる。NFS / SMB の読み出しは S3 リクエストにならない
- 一覧取得を減らす。`ListObjectsV2` は Tier1 単価で、GET より 1 桁高い

**両方のとき。** 両方やる。片方だけでは残る側が支配項になる。

### 手順 4 — 収集側の設計と衝突しないか確かめる

読み取り側のためにオブジェクトを大きくまとめると、収集側の制約に当たる。

| まとめた結果 | 当たる制約 |
|---|---|
| 単一オブジェクトが 5 GiB を超える | S3 AP の単一 `PutObject` の上限。マルチパートに切る |
| オブジェクト全体が 50 GiB を超える | S3 AP の上限。判定は転送後なので、送る前にクライアント側で検証する |
| 利用側が必要とする粒度より大きい | 使わない部分まで運ぶことになり、転送量が増える。読み出し単位と揃える |

逆に、利用側の読み出し単位より細かく分割すると、1 回の処理で複数回の読み出しが必要になり、
リクエスト回数が増える。**まとめる粒度は利用側の読み出し単位に合わせる**のが基準になる。

### 手順 5 — 前提が崩れていないかを運用で見る

試算は仮定に乗っている。次の 3 つがずれると結論が変わる。

| 監視するもの | ずれたときに起きること | 見る場所 |
|---|---|---|
| キャッシュのヒット率 | 作業セットの想定より大きくなると、ミスが増えて転送量が想定を超える | FlexCache のヒット率（Harvest 経由で取得できる） |
| 読み取り回数の分布 | 回数が減ると、キャッシュの固定費を回収できなくなる | アクセスログのキー別 GET 回数 |
| 転送量 | 段階単価の境界を越えると単価が変わる | Cost Explorer の `APN1-DataTransfer-Out-Bytes` |

ヒット率が落ちたときの対処は Cache の拡張だが、
**Cache ボリュームは階層化できない**ので、拡張分はそのまま SSD の費用になる。
作業セットの増加は費用に直結する。

## 層をまたぐ境界値と落とし穴

上限値そのものは[別ページ](s3-access-point.md)にある。
ここでは**層が違う上限どうしが噛み合って問題になる組み合わせ**を集める。
どれも単独のページを読んだだけでは気づきにくい。

### サイズの境界は層ごとに違う

| 境界 | 値 | 効く層 | 段階 |
|---|---|---|---|
| S3 AP 単一 `PutObject` | 5 GiB | 収集 | 検証済み |
| S3 AP `UploadPart` 1 パート | 5 GiB | 収集 | 検証済み |
| S3 AP オブジェクト全体 | 50 GiB | 収集 | 検証済み |
| S3 AP `GetObject` | サイズ上限なし（Range GET 対応） | 収集 | 検証済み |
| FlexCache write-back の検証済みファイルサイズ | 100 GB 未満 | 配布 | ドキュメント記載（[ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)） |
| FlexCache write-back の検証済み WAN 往復 | 200 ms 以内 | 配布 | 同上 |

**S3 AP から収集する限り、この 2 つは衝突しない。** オブジェクト全体が 50 GiB で止まるため、
write-back の検証範囲である 100 GB の内側に必ず収まる。

衝突するのは経路が変わったときである。**Cache 側の NFS / SMB から直接ファイルを書く場合、
サイズを止めるものが S3 AP 側にない。** write-back を有効にしていると、
100 GB を超えたファイルは検証済みの範囲外に出る。
配布側で大きなファイルを生成する設計（レンダリング出力、シミュレーション結果、
アーカイブの組み立てなど）では、この境界を設計時に確認する。

### 50 GiB の判定はペイロード転送後に行われる

オブジェクト全体の 50 GiB は `CompleteMultipartUpload` の時点で判定される。
つまり**全パートを転送し終えてから失敗する**。転送に使った時間とリクエスト課金は戻らない。
クライアント側で送信前にサイズを検証する。

### スナップショットの取得間隔と write-back

Origin でスナップショットを取ると、その Origin ボリュームに紐づく
**すべての write-back Cache から未処理のダーティデータを回収する**。
書き込みが多い時間帯では、この回収に複数回の再試行が必要になる
([ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html))。

保護のためにスナップショットを短い間隔で取る運用と、write-back は相性が悪い。
両方が要るなら、スナップショットの間隔と書き込みのピークをずらす、
あるいは配布側の書き込みを Origin に寄せる。

### シンプロビジョニングと write-back の無言の切り替え

write-back Cache は、**Origin ボリュームの空き容量が 20% 以下になると自動的に
write-around へ切り替わる**。閾値は Origin の報告する空き容量と、
アグリゲートの物理空き容量の**両方**で評価される。
Origin をオーバープロビジョニングしていると、想定より早く切り替わる ([ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html))。

切り替わってもエラーは出ない。書き込み遅延が増えることで気づく。
容量を詰めた設計をしているなら、write-back に依存した性能前提を置かない。

### Cache は階層化できないので、作業セットの増加がそのまま SSD になる

Cache ボリュームは階層化されない ([対応機能一覧](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html))。
Origin 側で `AUTO` ティアリングを効かせて SSD を小さく保っていても、
**配布側にはその逃げ場がない**。作業セットが増えた分は SSD の増設になる。

サイジングの指針は Origin の最低 10%、作成時の既定値も 10% ([サイジング指針](https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html))。
小さい Origin では、比率よりも SSD 1 TiB の下限が先に効く。
費用の出方は[FinOps の費用構造](../comparison/finops-s3-vs-s3ap.md)にまとめている。

### Cache は FlexGroup でなければならない、write-back は単一コンスティチュエントを推奨

AWS のドキュメントは **FlexCache ボリュームは FlexGroup であること**を求めている
([FlexCache の作成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/create-flexcache.html))。
一方 write-back のガイドラインは、意図しない退避を避けるために
**Cache ボリューム全体を単一コンスティチュエントで構成すること**を推奨している
([ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html))。
両方を満たすと「コンスティチュエントが 1 つの FlexGroup」になる。

加えて、この構成の検証では **FlexGroup を ONTAP CLI で作成しようとすると
FabricPool アグリゲートとの互換性エラーになり、FSx for ONTAP の API で作成する必要があった**
（[検証記録](../../verification/cross-protocol-directions.md)）。
作成経路によって成否が変わるので、CLI で失敗しても仕様上不可能とは判断しない。

### Origin ボリュームが 10 を超えるなら write-around

AWS のドキュメントは、読み取り中心で遅延に敏感でない場合、
**あるいは Origin ファイルシステムの FlexCache Origin ボリュームが 10 を超える場合**に
write-around を挙げている ([FlexCache での複製](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html))。
拠点数を増やすファンアウト設計では、この本数が write-back の可否に効く。

### リネームは両方の層で高くつく

S3 のキーは NFS 側のパスそのものなので、パーティションの付け替えはディレクトリのリネームになる。
write-back を有効にしている場合、**リネームしたファイルは Cache から退避され、
ダーティデータを Origin へ流し切るまで他の操作ができない** ([ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html))。

キー設計をやり直す前提で運用しない。最初から動かさない構造にする。
（代替案として S3 Files を採る場合も、リネームはプレフィックス配下の全オブジェクトの
コピーと削除になる。詳細は[FinOps の費用構造](../comparison/finops-s3-vs-s3ap.md)にある）

### 名前の衝突はキー設計の段階でしか防げない

`part1/part2` と `part1/part2/part3` は NAS 上で同時に存在できない。
前者がファイル、後者が同名ディレクトリを要求するためである ([NAS データ要件](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html))。

マニフェストを `.../day=10/_manifest_14.json` に置き、
同じ階層に `.../day=10/_manifest_14/` を作る設計にすると衝突する。
リーフとその下の階層に同じ名前を使わない。

### write-back で Cache 側から変更できる属性は限られる

write-back 有効の Cache で設定できるのは、タイムスタンプ、モードビット、NT ACL、
所有者、グループ、サイズだけである。それ以外の属性変更は Origin へ転送され、
**ファイルが Cache から退避される場合がある** ([ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html))。
拡張属性を使うアプリケーションを配布側で動かす場合は、事前に確認する。

### SMB の書き込み oplock は write-back で使えない

write-back 有効の Cache では、書き込みの SMB Opportunistic Lock が非対応である
([ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html))。
SMB クライアントの性能前提が oplock に依存している場合、write-back と併用できない。

### バージョン要件は Origin と Cache の両方に掛かる

| 項目 | 要件 |
|---|---|
| S3 AP（収集層） | ONTAP 9.17.1 以降 |
| FlexCache write-back | ONTAP 9.15.1 以降で利用可能。9.17.1P1 で重要な改善が入り、Origin と Cache の両方でそれ以降を強く推奨。9.15.1 は本番向けに推奨されない（[ガイドライン](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)） |
| FlexCache duality（NAS バケット） | ONTAP 9.18.1 以降。加えて `-is-s3-enabled true`（advanced 権限） |

収集層の要件だけを見て版数を決めると、配布側で write-back を使う段階で足りなくなる。
**両側の要件を先に足し合わせてから版数を決める。**

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [上限値](s3-access-point.md) | サイズ・名前・構成上の前提 |
| [FinOps の費用構造](../comparison/finops-s3-vs-s3ap.md) | 課金次元、構成別の試算、代替案の仕様上の制約 |
| [サポート状況](../../support-matrix.md) | 収集層と配布層の対応マトリクス |
| [構成の形](../../architecture.md) | この構成が解くことと解かないこと |
| [最初に決めること](../../design-first-decisions.md) | セキュリティスタイルとボリューム設計の決定順序 |
| [PoC チェックリスト](../../poc-checklist.md) | 何をどの順に確かめるか |
| [姉妹リポジトリ: 互換性ノート](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns) | Lambda / Step Functions 連携の詳細 |

---

<!-- lang-switcher:start -->
🌐 [日本語](s3ap-design-guide.md) | [English](../../../en/reference/limits/s3ap-design-guide.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->
