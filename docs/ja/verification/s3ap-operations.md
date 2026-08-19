# 検証記録 — presigned URL と UploadPartCopy

## 概要

参照ドキュメントが「未検証」と自ら名指ししていた 2 点を測りました。

- [設計ガイド](../reference/limits/s3ap-design-guide.md#presigned-url)の「実測されているのは
  `GetObject` で、**`PutObject` と `HeadObject` は未検証**である」
- 同ガイドの UploadPartCopy 行の「**同一 AP 内をソースにした測定は未実施**」

結果はどちらも公式対応表と逆向きでした。**対応表が非対応としている presigned URL は動作し、
対応表が対応としている同一 AP 内ソースの `UploadPartCopy` は失敗しました。**
どちらか一方をもう一方の根拠にはしていません。段階の判定は
[検証状況](../verification-status.md)に従います。

## 検証環境

| 項目 | 値 |
|---|---|
| 計測日 | 2026-08-19（UTC） |
| リージョン | ap-northeast-1 |
| ファイルシステム | 検証用の 1 台。SINGLE_AZ_1、1024 GiB、128 MBps |
| ボリューム | UNIX セキュリティスタイル、SnapLock なし |
| S3 Access Point | UNIX（root）識別情報、`NetworkOrigin` は VPC 制限なし |
| 比較用 Access Point | 同一ボリュームに接続された別の Access Point |
| ONTAP バージョン | **未特定。** FSx for ONTAP の API は公開していないため、ONTAP REST API か CLI が必要 |
| クライアント | **AWS 外のローカル端末からインターネット経由** |
| クライアント実行環境 | Python 3.14.6、boto3 / botocore 1.43.36 |
| オブジェクトサイズ | 64 B（latency フェーズ） |
| 並列度 | 1 |
| 反復 | n=30、実行 4 回 |
| 測定方法 | HTTPS 接続を再利用。各系列の初回はウォームアップとして破棄 |
| スクリプト | [`scripts/measure_s3ap_operations.py`](../../../scripts/measure_s3ap_operations.py) |

> **測定位置についての注記**: クライアントが AWS 外にあるため、**すべての数値にインターネットの
> 往復遅延が含まれます**。同一条件で測った経路どうしの比較には使えますが、ストレージ側の
> 応答時間としては読めません。VPC 内から測った値はここにはありません。

> **識別情報についての注記**: この測定は Access Point の識別情報を UNIX の root で行っています。
> Access Point 経由の全リクエストがこの 1 つの識別情報で認可されるため、root を指定すると
> ファイル権限による絞り込みが効きません。測定条件としてそのまま記録しますが、推奨構成では
> ありません。用途ごとに Access Point を分け、必要な権限だけを持つユーザーを使ってください
> （`FileSystemIdentity` は作成後に変更できません）。

## presigned URL

### 結果: `PutObject` / `HeadObject` / `GetObject` はいずれも成功

| オペレーション | 署名 | 結果 |
|---|---|---|
| `PutObject` | SigV4 | HTTP 200 |
| `HeadObject` | SigV4 | HTTP 200 |
| `GetObject` | SigV4 | HTTP 200 |
| `PutObject` | SigV2 | HTTP 200（Content-Type を空で送った場合） |

対照として同一実行内で次を確認しています。

| 対照 | 期待 | 結果 |
|---|---|---|
| presigned で書いたオブジェクトを署名済み API 呼び出しで読む | 成功する（本当に書けている） | 成功、14 バイト |
| 署名を改変した URL | 拒否される（エンドポイントが素通しでない） | HTTP 403 `SignatureDoesNotMatch` |

公式対応表は `Presign — Not supported` と記載しています。**測定は 3 つのオペレーションすべてで
成功しました。** 設計ガイドが説明していた機構と整合します — presigning はクライアント側の署名計算で、
生成された URL が実行するのは通常の `GetObject` / `PutObject` / `HeadObject` です。
NetApp KB のバージョン別記載（9.11.1 以降で v4、9.16.1 以降で v2 + v4）とも整合し、
**v2 と v4 の両方が動作しました**。

**対応表が `Not supported` としている間、本番ワークロードを依存させない判断は変えません。**
動作したことは、非推奨通知なしに挙動が変わらないことの保証ではありません。

### SigV2 は署名対象ヘッダーが増えるため壊れやすい

| 経路 | 結果 |
|---|---|
| SigV2 PUT、クライアントが Content-Type を自動付与 | HTTP 403 `SignatureDoesNotMatch` |
| SigV2 PUT、Content-Type を空で明示 | HTTP 200 |
| SigV4 PUT、クライアントが Content-Type を自動付与 | HTTP 200 |

SigV2 は Content-Type を署名対象に含めるため、**クライアントが自分で付けたヘッダーが署名を無効化
します**。SigV4 の既定の署名対象ヘッダーは `host` だけなので、この影響を受けません。

**boto3 で presigned URL を作るときは署名バージョンを明示してください。**

```python
# 明示しないと SigV2 が生成される。client.meta.config.signature_version は
# どちらの場合も "s3v4" を返すため、報告値では判別できない
client = boto3.client("s3", config=Config(signature_version="s3v4"))
```

これはクライアント側の挙動であり、FSx for ONTAP の性質ではありません。

### latency: presigned URL 経由の追加コストは測れなかった

p50、4 回の実行にわたる範囲。

| 経路 | p50 の範囲 |
|---|---|
| presigned `PutObject` | 48〜57 ms |
| presigned `PutObject` + `Expect: 100-continue` | 50〜53 ms |
| presigned `HeadObject` | 37〜53 ms |
| 署名済み API `HeadObject` | 44〜50 ms |

**`HeadObject` は presigned と署名済み API で範囲が重なり、差を検出できませんでした。**
presigned URL を使うこと自体のコストは、この測定では観測されていません。

### `PutObject` の差は署名ではなくリクエストの符号化

| 経路 | p50 の範囲 |
|---|---|
| presigned `PutObject` | 48〜57 ms |
| SDK `PutObject`（botocore 既定） | 105〜232 ms |
| SDK `PutObject`（`request_checksum_calculation="when_required"`） | 58〜66 ms |

botocore の既定（`when_supported`）は、**64 B の本文でも `aws-chunked` 符号化と CRC32 トレーラーを
使います**。送信されるヘッダーは次のとおりです。

```text
Content-Encoding: aws-chunked
Transfer-Encoding: chunked
X-Amz-Content-SHA256: STREAMING-UNSIGNED-PAYLOAD-TRAILER
X-Amz-Trailer: x-amz-checksum-crc32
Expect: 100-continue
```

`when_required` に変えると符号化が固定長本文に戻り、p50 は presigned の範囲と重なります。
**差は presigned か署名済み API かではなく、この符号化です。**

`Expect: 100-continue` は要因ではありませんでした。presigned PUT に同ヘッダーを付けても
50〜53 ms で、付けない場合の 48〜57 ms と重なります。

> **トレードオフに関する補足**: `when_required` はアップロード時の CRC32 による整合性検査を
> 省きます。**速いほうを選べという話ではありません。** 既定が整合性検査を行う理由があり、
> この符号化のコストが問題になる場合に初めて検討する選択肢です。

### 測れなかったもの

| 項目 | 状態 |
|---|---|
| 書き込み直後の `HeadObject` | **実行ごとに p50 が 86〜787 ms と不安定**。整定済みキーの 44〜50 ms より明確に遅いが、値として公開できる安定性がない。オブジェクトサイズと書き込み後の待ち時間を振った専用の測定が必要 |
| VPC 内から測った値 | 未測定。上記はすべて AWS 外からの値 |
| 64 B 以外のオブジェクトサイズ | 未測定 |
| 並列実行時の挙動 | 未測定（並列度 1） |
| ONTAP バージョンとの対応 | **バージョンを特定できていないため、この結果をバージョンに紐付けられない** |

## UploadPartCopy

### 結果: 同一 Access Point 内をソースにしても `NoSuchKey` を返す

公式対応表は `UploadPartCopy` を**同一 AP 内・同一リージョンで対応**としています。
6 MiB のソースオブジェクトを同一 Access Point に置き、同じ Access Point 上の宛先に対して
`UploadPartCopy` を実行しました。

| 操作 | 結果 |
|---|---|
| `UploadPartCopy`、ソースは同一 Access Point | **`NoSuchKey`** |

**同一実行内の対照がすべて成功しているため、手順の誤りではありません。**

| 対照 | 期待 | 結果 |
|---|---|---|
| ソースオブジェクトを `HeadObject` で読む | 成功する（キーは存在する） | 成功、6,291,456 バイト |
| 同じマルチパートアップロードに `UploadPart`（コピーでない） | 成功する（セッションは有効） | 成功 |
| **同一の `CopySource` を与えた `CopyObject`** | — | **成功** |

最後の行が判定の要です。**同じソース、同じ Access Point、同じ実行の中で、`CopyObject` は成功し
`UploadPartCopy` は `NoSuchKey` を返します。** ソースの指定が解決できているのに、
オペレーションの側で失敗しています。

`CopySource` を文字列形式（`<ap-arn>/<key>`）で渡した場合は
`InvalidArgument: Invalid resource in copy source ARN` になりました。
辞書形式（`{"Bucket": <ap-arn>, "Key": <key>}`）は `CopyObject` が受理する形式です。

### 別の Access Point をソースにすると、両方とも拒否される

同一ボリュームに接続された別の Access Point 経由で同じオブジェクトを指した場合です。

| 操作 | 結果 |
|---|---|
| `UploadPartCopy`、ソースは同一ボリュームの別 Access Point | `InvalidArgument: Invalid copy source header` |
| `CopyObject`、ソースは同一ボリュームの別 Access Point | `InvalidArgument: Invalid copy source header` |

対照の `HeadObject` はどちらの Access Point 経由でも成功しており、オブジェクトは見えています。
設計ガイドが Cross-AP Copy を「機能として存在しない」に置いているのと整合します。

### この測定が答えていないこと

**`UploadPartCopy` そのものが非対応なのかどうかは、この測定では判定できません。**
判定するには、このエンドポイントでコピーが成立する別のソース名前空間が必要ですが、
**別 Access Point 経由のコピーは `CopyObject` でも拒否されるため、そのような名前空間がありません。**
言えるのは次の範囲です。

> このエンドポイントでコピーが成立する唯一のソース形式（同一 Access Point）を与えたとき、
> `UploadPartCopy` は `NoSuchKey` を返し、同じソースで `CopyObject` は成功する。

| 項目 | 状態 |
|---|---|
| 標準 S3 バケットをソースにした `UploadPartCopy` | 未測定。この測定の範囲（Access Point 1 つ）を超えるため実施していない |
| 6 MiB 以外のパートサイズ | 未測定 |
| 複数パートでの `UploadPartCopy` | 未測定（パート 1 で失敗するため到達しない） |
| ONTAP バージョンとの対応 | **バージョンを特定できていないため紐付けられない** |

### 先の 1 回の観測との関係

設計ガイドは「ソースが同一 AP 内に**ない**条件で `404 NoSuchKey`」という
**再現を確認していない 1 回の観測**を記録し、そこから非対応と一般化しないと注意していました。

今回の測定は、**同一 AP 内のソースでも `NoSuchKey` になり**、
**同一 AP 内に「ない」ソース（別 AP）では `InvalidArgument` になる**ことを示しています。
先の観測が `NoSuchKey` をソースの位置に帰していたのであれば、**その帰属は今回の結果と合いません。**
1 回の観測から原因を決めなかった判断は妥当でした。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [設計ガイド](../reference/limits/s3ap-design-guide.md) | オペレーションごとの対応状況と設計上の注意 |
| [上限値](../reference/limits/s3-access-point.md) | サイズ・名前・構成の上限 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
| [PoC チェックリスト](../poc-checklist.md) | 未検証項目を確かめる順序 |
