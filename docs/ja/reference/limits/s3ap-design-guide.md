# S3 Access Point — 設計ガイド（収集層の詳細）

<!-- 出典: 姉妹リポジトリ fsxn-s3ap-serverless-patterns の設計考慮事項・互換性ノート・
     性能考慮事項を、この構成の観点でまとめ直したもの。
     https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns -->

この構成の収集層（S3 Access Point）を設計する際に知っておくべき詳細を記載する。
上限値は[別ページ](s3-access-point.md)、構成全体は[構成の形](../../architecture.md)を参照。

## 対応 S3 オペレーション

FSx for ONTAP の S3 AP は「S3 互換」だが「Amazon S3 と同一」ではない。

### 動作確認済み

| オペレーション | 備考 |
|---|---|
| GetObject | Range GET 対応。ダウンロードにサイズ上限なし |
| PutObject | 単一 PUT は 5 GiB まで |
| ListObjectsV2 | Prefix / Delimiter / MaxKeys 対応 |
| HeadObject | — |
| DeleteObject | — |
| MultipartUpload | CreateMultipartUpload / UploadPart / CompleteMultipartUpload |
| CopyObject | 同一 AP 内のみ |

### 非対応（エラーが返る）

| オペレーション | 返却 | 代替手段 |
|---|---|---|
| 条件付き書き込み（If-None-Match） | 501 NotImplemented | アプリケーション側の排他制御 |
| S3 Annotations（PutObjectAnnotation 等） | 501 NotImplemented | 標準 S3 バケットに出力して annotation 付与 |
| UploadPartCopy | 404 NoSuchKey（実測） | CopyObject または NFS/SMB で移動 |

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

公開ドキュメントは「Not supported」と記載するが、ONTAP レイヤーでは動作する
（9.11.1 以降で SigV4、9.16.1 以降で SigV2 + SigV4）。
AWS サポートがドキュメント修正を提出済みだが**未公開**。
本番ワークロードでの依存は非推奨。

## 並行度とスループットの設計

**S3 AP、NFS、SMB はすべて同じ FSx for ONTAP プロビジョンドスループットを共有する。**
収集層（S3 AP 書き込み）と配布層（FlexCache NFS/SMB 読み取り）が同じファイルシステム上に
ある場合、帯域の取り合いが発生する。この構成では Origin と Cache が別クラスタなので
通常は問題にならないが、**Origin クラスタに直接 NFS アクセスするクライアントがいる場合**は
スループット分配を考慮する。

### 推奨並行度（S3 AP 書き込みのみ、他トラフィックなし）

| FSx for ONTAP Throughput Capacity | 推奨同時リクエスト数 | 想定用途 |
|---|---|---|
| 128 MBps | 2–5 | PoC / 小規模検証 |
| 256 MBps | 5–10 | 開発・テスト |
| 512 MBps | 10–20 | 小規模本番 |
| 1,024 MBps | 20–50 | 中規模本番 |
| 2,048+ MBps | 50–100 | 大規模本番 |

計算式: `最大並行度 ≈ プロビジョンドスループット ÷ 1 リクエストあたりの消費帯域`

**NFS/SMB の既存ワークロードがある場合は、その分を差し引いて設計する。**

### スループット飽和時の挙動

FSx for ONTAP のスループットが飽和すると S3 API は `SlowDown` (503) を返す。
Exponential backoff（base: 1 秒、max: 30 秒）で対処する。
boto3 の `adaptive` retry mode が推奨。

## ディレクトリ設計

### 1 ディレクトリあたりのファイル数

| シナリオ | 推奨上限 | 根拠 |
|---|---|---|
| 一般的なワークロード | 10 万件以下 | readdir 応答時間と ListObjectsV2 レスポンスの実用的な上限 |
| 高頻度書き込み（IoT / ログ） | 1 万件以下 | 書き込み頻度が高い場合、パーティション分割を細かくする |
| FlexGroup 利用時 | 5 万件以下 / constituent | constituent 間の均等分散を維持 |

10 万件を超えると、ListObjectsV2 のインメモリソートコストが増加し、`maxdir-size` 到達による
ファイル作成失敗のリスクも出る。

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

## マルチプロトコル一貫性

この構成では「S3 AP で書き、NFS/SMB で読む」のが主経路。逆方向や同時書き込みには注意が必要。

| シナリオ | 動作 | リスク |
|---|---|---|
| **S3 AP PutObject 完了 → NFS/SMB read** | **即座に一貫したデータが読める**（WAFL の原子的コミット） | なし。これが主経路 |
| NFS 書き込み中に S3 AP GET | 書き込み途中のデータが読まれる可能性（部分読み取り） | データ不整合 |
| S3 AP 書き込み + FlexCache write-back で同一ファイル | Cache のダーティデータが破棄される（XLD revoke） | データ競合 |
| NFS rename 直後に S3 AP GET（旧キー） | 旧キーでは NotFound（rename は即座に反映） | アプリ側のキー管理 |

### この構成での安全な使い方

**主経路（S3 AP → FlexCache NFS/SMB）は安全。** S3 AP の PutObject が完了した時点で、
FlexCache 経由の NFS/SMB read からも一貫したデータが見える（伝搬待ちはあるが、
見えた時点では常に完全なデータ）。

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

FlexGroup を Origin にした FlexCache では NAS バケットが作成可能（ただし[現時点では
FlexCache 上のデータアクセスが動作しない](../../verification/cross-protocol-directions.md)）。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [上限値](s3-access-point.md) | サイズ・名前・構成上の前提 |
| [サポート状況](../../support-matrix.md) | 収集層と配布層の対応マトリクス |
| [構成の形](../../architecture.md) | この構成が解くことと解かないこと |
| [姉妹リポジトリ: 互換性ノート](https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns) | Lambda / Step Functions 連携の詳細 |
