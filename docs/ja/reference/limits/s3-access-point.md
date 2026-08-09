# 上限値 — 収集層（FSx for ONTAP S3 Access Point）

数値は出典と段階を併記する。段階の定義は[検証状況](../../verification-status.md)にある。

## サイズ

| 項目 | 値 | 段階 | 備考 |
|---|---|---|---|
| 単一 `PutObject` | 5 GiB | 検証済み | 姉妹リポジトリでの実測。ドキュメントの「5 GB」表記に対して実測は 2 進接頭辞（5,368,709,120 バイト） |
| `UploadPart` 1 パート | 5 GiB | 検証済み | 同上 |
| オブジェクト全体 | 50 GiB | 検証済み | 同上。判定は `CompleteMultipartUpload` の時点で行われるため、全ペイロードの転送後に失敗する。クライアント側で先に検証する |

出典: 姉妹リポジトリ
[fsxn-s3ap-serverless-patterns](https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns)
の実測記録。

## 名前

| 項目 | 値 | 段階 | 出典 |
|---|---|---|---|
| S3 オブジェクト名 | 1024 バイト | ドキュメント記載 | [NAS データ要件](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html) |
| ファイル / ディレクトリ名 | 255 文字 | ドキュメント記載 | 同上 |
| 同名の衝突 | `part1/part2` と `part1/part2/part3` は NAS 上で同時に存在できない | ドキュメント記載 | 同上。前者がファイル、後者が同名ディレクトリを要求するため |
| ボリューム名 | 英数字とアンダースコアのみ | ドキュメント記載 | — |

スラッシュを含まない名前はすべてルートディレクトリに集まる。数が多いと性能問題になる。
上記出典は、NAS フレンドリでない名前を多用するアプリにはオブジェクトストアのほうが適すると
明記している。

## 構成上の前提

| 項目 | 値 | 段階 | 出典 |
|---|---|---|---|
| 最小 ONTAP バージョン | 9.17.1 | ドキュメント記載 | [制限事項](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html) |
| リージョン | アクセスポイントとボリュームが同一リージョン | ドキュメント記載 | 同上 |
| アカウント | アクセスポイントとボリュームが同一アカウント | ドキュメント記載 | 同上 |
| `NetworkOrigin` | 作成後は変更できない | ドキュメント記載 | 同上。`Internet` origin は S3 Gateway VPC エンドポイントからは到達しない |
| 認可 | AWS 側と ONTAP 側の両方が許可する必要がある | ドキュメント記載 | [二層認可](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/s3-ap-manage-access-fsxn.html) |

## 対象外の機能

| 機能 | 状態 |
|---|---|
| イベント通知 | 対象外。ポーリングまたは FPolicy を検討する |
| ライフサイクル | 対象外 |
| バージョニング | 対象外 |

## 配布層（FlexCache）

| 項目 | 値 | 段階 | 備考 |
|---|---|---|---|
| Origin あたりの Cache 数 | AWS ドキュメントは Origin ボリュームが 10 を超える場合に write-around を推奨 | ドキュメント記載 / 挙動は未検証 | ファンアウト数の設計に影響する可能性がある |
| 対応構成 | 3 通り | ドキュメント記載 | [移植性](../../portability.md)に一覧 |
| セキュリティスタイル | Cache 作成時に Origin から継承される項目として扱われる | 未検証 | 根拠は Azure NetApp Files のキャッシュボリューム要件。この構成の主経路では未確認（[最初に決めること](../../design-first-decisions.md)） |

## 書かない数値

性能値とコスト値は、実測して環境を併記できるまで書かない。
環境の併記がない数値は再現できないので、比較にも見積りにも使えない。
必要な項目は[検証状況](../../verification-status.md)にある。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [S3 AP 設計ガイド](s3ap-design-guide.md) | 対応オペレーション詳細、並行度設計、ディレクトリ設計、マルチプロトコル一貫性 |
| [サポート状況](../../support-matrix.md) | 制約の全体像 |
| [検証状況](../../verification-status.md) | 段階の定義と現在の状態 |
| [構成の形](../../architecture.md) | この構成が解かないこと |
