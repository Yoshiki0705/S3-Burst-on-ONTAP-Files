# 検証記録 — マルチパートアップロードの境界と、Internet origin 経由の書き込みスループット

## 概要

Amazon FSx for NetApp ONTAP のボリュームに付けた S3 Access Point に対して、次の 2 つを測った記録です。

- マルチパートアップロードのサイズ境界（パート 1 つの 5 GiB と、オブジェクト全体の 50 GiB）で何が起きるか
- 同じファイルシステムへの NFS 直書き込みと、S3 Access Point 経由の書き込みで、スループットがどれだけ違うか

**1 つの構成で、限られた回数だけ測ったサンプル実行です。本番の見積りではありません。**
値はすべて「`NetworkOrigin=Internet` の S3 Access Point を、同一リージョンの EC2 からインターネット経路で
呼んだ、この構成」のものです。S3 Access Point 一般の性質としては読めません。この測定では
`NetworkOrigin=VPC` の S3 Access Point を測っていません。段階の定義は[検証状況](../verification-status.md)に
従います。

| 問い | この測定での答え | 回数 |
|---|---|---|
| パート 1 つが 5 GiB ちょうど | 成功 | 1 |
| パート 1 つが 5 GiB を超える | 失敗。+1 MiB では S3 のエラー応答ではなく、クライアント側で接続エラーとして現れた | +1 MiB と +1 バイトで各 1 |
| 全体が 50 GiB ちょうど | 成功。`CompleteMultipartUpload` に 2,513 秒 | 1 |
| 全体 50 GiB 超を `CompleteMultipartUpload` で判定するか | **観測していない**（パート上限で先に拒否された） | 0 |
| NFS 直書き込みと S3 Access Point 経由の差 | NFS 124.4〜125.5 MiB/s、S3 Access Point 経由 16.4〜49.1 MiB/s | NFS 2 回、S3 Access Point は並列度ごとに 1 回 |

## 測定環境

| 項目 | 値 |
|---|---|
| 計測日 | 2026-10-07 |
| リージョン | ap-northeast-1 |
| ファイルシステム | 第一世代 SINGLE_AZ_1、HA ペア 1 組 |
| スループットキャパシティ | 128 MBps（`describe-file-systems` で確認） |
| SSD 容量 / SSD IOPS | 記録していない |
| ONTAP バージョン | 記録していない |
| ボリューム | 100 GB、セキュリティスタイル UNIX。インライン効率化の設定は記録していない |
| SVM | AWS Managed Microsoft AD（Standard Edition）に参加済み |
| S3 Access Point | `NetworkOrigin=Internet`、`FileSystemIdentity` は UNIX / root。エイリアスは `<ap-alias>` と表記 |
| クライアント | c5n.2xlarge（同一リージョン、ネットワーク帯域は「最大 25 Gbps」の表記）、Amazon Linux 2023、aws-cli 2.33.15 |
| 経路 | S3 Access Point へはインターネット経路。NFS はファイルシステムの NFS LIF（`<nfs-lif-ip>`）へ直接 |
| NFS マウント | NFS のバージョン、`rsize` / `wsize`、`nconnect` は記録していない |
| 認証 | 測定専用の IAM ユーザー。権限は対象の S3 Access Point への操作に限定し、測定後に削除した |
| 測定したもの | クライアント側の所要時間と、aws-cli / dd の表示。CloudWatch のメトリクスと ONTAP のカウンタはこの記録に含まれていない |

> **識別情報についての注記**: アクセスポイントの識別情報を UNIX の root にしています。アクセスポイント
> 経由の全リクエストがこの 1 つの識別情報で認可されるため、ファイル権限による絞り込みが効きません。
> 測定条件として記録しますが、推奨構成ではありません（`FileSystemIdentity` は作成後に変更できません）。

> **認証についての補足**: 長期のアクセスキーを持つ IAM ユーザーは測定条件の記録であり、推奨する形では
> ありません。EC2 から測るなら、インスタンスプロファイルの IAM ロールで足ります。

> **クライアントについての補足**: c5n.2xlarge は「最大」表記のインスタンスです。この記録の最大値は
> 125.5 MiB/s（約 1.05 Gbps）で、[既存の記録](throughput-iops-concurrency.md#計測ホストに-c5n9xlarge-を選んだ理由)は
> 128 MBps 構成なら「最大」表記のインスタンスでも足りると判断しています。この測定でネットワーク
> クレジットが関与したかどうかは確認していません。

## マルチパートアップロードのサイズ境界

| 試験 | 内容 | 結果 |
|---|---|---|
| A1-control | パート 1 つ、5 GiB ちょうど（5,120 MiB = 5,368,709,120 バイト） | **成功。** ETag が返り、`ServerSideEncryption: aws:fsx` |
| A1-over | パート 1 つ、5 GiB + 1 MiB | **失敗。** aws-cli の表示は `SSL validation failed` / unknown error。`EntityTooLarge` のような S3 のエラーコードは返っていない |
| A2 | 5 GiB × 10 パート、全体 50 GiB ちょうど | **成功。** `ContentLength=53687091200`。アップロード 539 秒 + `CompleteMultipartUpload` 2,513 秒 = 計 3,052 秒 |
| A4 | パート 1〜9 が 5 GiB、パート 10 が 5 GiB + 1 バイト（全体 50 GiB + 1 バイト） | **パート 10 の `UploadPart` で失敗**（記録上のラベルは `UPLOAD_PART_FAILED`）。パート 1〜9 は成功。`CompleteMultipartUpload` には到達していない |

パート 1 つは 5 GiB ちょうどで通り、1 バイト超えた時点で拒否されました（A1-control と A4 のパート 10、
各 1 回）。[上限値](../reference/limits/s3-access-point.md#サイズ)にある `UploadPart` 1 パート 5 GiB
（姉妹リポジトリでの実測）と同じ境界です。

### 接続エラーとして現れた 5 GiB 超のパートの拒否

A1-over の失敗で、aws-cli は S3 のエラーコードを表示しませんでした。aws-cli が表示したのは
`SSL validation failed` / unknown error で、接続の層の失敗に見えます。**同じセッションで 5 GiB ちょうどの
パート（A1-control）が成功しているので、経路や認証の故障ではなくサイズに起因すると判断しました。**

**観測したのはクライアント側での現れ方だけです。** サーバー側が接続をリセットしたのか、閉じたのか、
何かを返したのかは捕まえていません。パケットキャプチャも aws-cli のデバッグログもこの記録にはなく、
A4 のパート 10 で返ったエラーの文面も記録していません。**1 回観測、再現は未確認です。**

エラーコードで分岐するエラー処理は、この失敗をサイズ超過ではなく通信障害として扱い、再試行する
可能性があります（未確認）。パートの大きさは送信前にクライアント側で 5 GiB 以下に抑えてください。

### 2,513 秒かかった 50 GiB の `CompleteMultipartUpload`

A2 では、aws-cli の `complete-multipart-upload` 呼び出しが 2,513 秒（約 42 分）戻らず、接続は切れないまま
最後に成功しました。パートを送り終えるまでの 539 秒の 4.7 倍です。観測したのはクライアント側の呼び出しが
戻らなかったことだけで、その間サーバーが何を送っていたかは捕まえていません。**1 回観測、再現は未確認です。**

Amazon S3 の [API リファレンス](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html)は、
`CompleteMultipartUpload` の処理に数分かかることがあり、その間 200 OK のヘッダーを返したうえで空白文字を
定期的に送って接続のタイムアウトを防ぐ、と記載しています。200 OK のあとでエラーになりうるので本文を
解釈する必要がある、とも書いています。**これは Amazon S3 についての記載で、FSx for ONTAP の
S3 Access Point についての記載ではありません。** FSx for ONTAP の
[Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)
（2026-10-08 に開いた。対応表と、その下の Limitations 節と Multipart upload 節）には、
`CompleteMultipartUpload` の所要時間にも空白文字の送出にも記載がありませんでした。

今回接続が保たれたことは Amazon S3 の記載と矛盾しません。ただし応答のバイト列を捕まえていないので、
**同じ仕組みで保たれていたというのは未検証の仮説です。**

50 GiB に近いオブジェクトを S3 Access Point で収集する設計では、完了待ちを含めた所要時間を、呼び出し側の
上限（関数の実行時間上限、プロキシやロードバランサーのアイドルタイムアウト）と比べてください。
所要時間がオブジェクトサイズやスループットキャパシティとどう関係するかは測っていません。

### 全体サイズの判定に届かなかった A4 の設計

A4 では全体を 50 GiB + 1 バイトにするために、パート 10 を 5 GiB + 1 バイトにしました。このパートは
パート単位の 5 GiB 上限を超えるので `UploadPart` の段階で拒否され、全体サイズを判定する
`CompleteMultipartUpload` まで進みませんでした。

**したがって「50 GiB を超えるアップロードは `CompleteMultipartUpload` の時点で拒否される」は、この測定では
観測していません。** [上限値](../reference/limits/s3-access-point.md#サイズ)の該当行（ドキュメント記載と、
姉妹リポジトリでの実測）の段階は変えていません。

測り直すときは、どのパートも 5 GiB 以下に保ったまま全体を 50 GiB 超にします。下は未実施の形です。

```bash
# 未実施。<ap-alias> は S3 Access Point のエイリアス、<upload-id> は create-multipart-upload の戻り値
aws s3api create-multipart-upload --bucket <ap-alias> --key a4-redo.bin
# パート 1〜10: 各 5 GiB ちょうど（5,368,709,120 バイト）。パート 11: 1 MiB。
# 全体は 50 GiB + 1 MiB になり、どのパートも 5 GiB を超えない
aws s3api upload-part --bucket <ap-alias> --key a4-redo.bin --part-number 11 \
  --upload-id <upload-id> --body part11.bin
aws s3api complete-multipart-upload --bucket <ap-alias> --key a4-redo.bin \
  --upload-id <upload-id> --multipart-upload file://parts.json
# 失敗したら中止する。未完了のパートは親ファイルシステムの StorageUsed に残る
aws s3api abort-multipart-upload --bucket <ap-alias> --key a4-redo.bin --upload-id <upload-id>
```

未完了のパートは宛先ボリュームではなく親ファイルシステムの `StorageUsed` に現れます
（[マルチパートアップロードの副作用](../reference/limits/s3-access-point.md#マルチパートアップロードの副作用)）。
合計 50 GiB を超えるパートを置ける空き容量を、ボリュームとファイルシステムの両方で先に確保してください。
今回のボリュームは 100 GB でした。

## NFS 直書き込みと S3 Access Point 経由の書き込みの差

同じファイルシステム、同じクライアント、同じデータ（`/dev/urandom` から作った 10 GiB、非圧縮）で、
書き込みだけを測りました。

| 経路 | 手段 | 回 | 結果 |
|---|---|---|---|
| NFS 直書き込み | `dd bs=1M conv=fsync` | run1 | 125.5 MiB/s（dd の表示 132 MB/s） |
| NFS 直書き込み | `dd bs=1M conv=fsync` | run2 | 124.4 MiB/s（dd の表示 131 MB/s） |

| 経路 | 手段 | 並列度（`max_concurrent_requests`） | 回 | 結果 | NFS 直書き込みに対する比 |
|---|---|---|---|---|---|
| S3 Access Point 経由 | `aws s3 cp` | 1 | 1 | 37.9 MiB/s | 30% |
| S3 Access Point 経由 | `aws s3 cp` | 8 | 1 | 16.4 MiB/s | 13% |
| S3 Access Point 経由 | `aws s3 cp` | 32 | 1 | 49.1 MiB/s | 39% |

dd の `conv=fsync` は終了前に出力ファイルのデータを書き出すので、NFS の値はページキャッシュへの書き込み
ではなく fsync の完了までを含みます。`aws s3 cp` は 10 GiB をマルチパートで送りますが、分割サイズ
（`multipart_chunksize`）は記録していません。比は NFS 直書き込みの 2 回の値（124.4〜125.5 MiB/s）に対する
ものです。

### 指定値の付近で揃った NFS 直書き込み

NFS 直書き込みは 2 回とも 124.4〜125.5 MiB/s（dd の表示で 131〜132 MB/s）で、2 回の差は 0.9% でした。
指定値 128 MBps の付近です。

10 進の MB/s で読むと指定値を 2〜3% 上回ります。**この差が単位の読み方によるのかバーストによるのかは
調べていません。** 同じ 128 MBps 構成を別の日に測った既存の記録でも、NFS 書き込み（129.5〜142.6 MB/s）と
S3 Access Point 経由の書き込み（`NetworkOrigin=VPC`、129.5〜131.2 MB/s）が指定値を 1〜11% 上回っており、
その記録はこれを指定値で止まった値として扱っています
（[NFS](throughput-iops-concurrency.md#ファイル経路の結果)、
[S3 Access Point](throughput-iops-concurrency.md#書き込みが購入した指定値で止まることの確認)）。

### 各並列度 1 回だけの S3 Access Point 経由の値

S3 Access Point 経由は 37.9 / 16.4 / 49.1 MiB/s で、NFS 直書き込みの 13〜39% でした。並列度 8 が最も低く、
並列度に対して単調ではありません。**各点 1 回しか測っていないので、この逆転が再現する性質なのか
1 回のばらつきなのかは区別できません。**

**この 3 点は[プロトコル別測定の結果](perf-matrix-results.md)の規律（複数回の測定、幅での報告、VDBENCH、
キャッシュ状態の記録）を満たしていません。** 同じ表に並べないでください。値を引用するときは
「1 回測定・ばらつき未収束」を添えてください。

### 律速の所在の推定

同じファイルシステム・同じクライアント・同じデータで、NFS 直書き込みは指定値の付近に達し、
S3 Access Point 経由はその 13〜39% で止まりました。ここから、**この構成で書き込みを止めていたのは
ファイルシステムのスループットキャパシティではなく、S3 Access Point 経由の経路の側だと推定します。**
経路の側には、インターネット経路の往復、S3 プロトコルの処理、マルチパートのパートごとのオーバーヘッドが
含まれますが、**3 つの内訳は測っていません。**

この推定の範囲を狭める事実が、同じセッションと既存の記録に 1 つずつあります。

| 事実 | 推定への影響 |
|---|---|
| 同じセッションの A2（5 GiB パート × 10）は 50 GiB を 539 秒で送っており、平均 95.0 MiB/s（99.6 MB/s）。上の表の S3 Access Point 経由のどの値よりも高い。A2 でパートを並列に送ったかどうかは記録していない | 上の表の値は、この経路で出せる上限ではない。パートの大きさ（A2 は 5 GiB、`aws s3 cp` は記録していない分割サイズ）か送り方の違いが値を動かしている可能性がある（未検証） |
| 既存の記録では、同じ 128 MBps 構成の S3 Access Point（`NetworkOrigin=VPC`、S3 ゲートウェイエンドポイント経由、boto3 の `PutObject`、並列度 16〜64）で書き込みが 129.5〜131.2 MB/s に達している。同じ記録は 1 リクエストあたり約 330 ms の固定費も測っている（[実測](throughput-iops-concurrency.md#1-リクエストあたりの固定費の差)） | 「S3 Access Point 経由だから指定値に届かない」とは読めない。ただし origin の種別、エンドポイント、クライアントのツールとインスタンス、リクエストの形（オブジェクトごとの `PutObject` か、1 オブジェクトのマルチパートか）が同時に違うので、この差を origin の種別に帰すこともできない |

言えるのは「`NetworkOrigin=Internet` のこの経路で、`aws s3 cp` で 10 GiB を書いたとき、NFS 直書き込みの
13〜39% だった」までです。

## この測定が答えていないこと

| 項目 | 状態 |
|---|---|
| 全体 50 GiB 超を `CompleteMultipartUpload` で判定するか | 未観測。A4 がパート上限で先に拒否されたため |
| 5 GiB 超のパートに対してサーバー側が何をしたか | 未観測。クライアント側の表示だけを記録 |
| 2,513 秒のあいだ接続が保たれた仕組み | 未検証の仮説（Amazon S3 の空白文字の記載と矛盾しない） |
| 各観測の再現 | 未確認。A の各試験 1 回、S3 Access Point 経由は並列度ごとに 1 回、NFS 直書き込みは 2 回 |
| `NetworkOrigin=VPC` での値 | この測定では測っていない |
| 128 MBps 以外の指定値での値 | 測っていない |
| 律速の内訳（往復・プロトコル処理・マルチパート） | 測っていない |
| NFS 直書き込みが 10 進で指定値を 2〜3% 上回った理由 | 調べていない |
| 読み取り | 測っていない |
| ONTAP バージョン | 記録していない。次に測るときは作成直後に `/api/cluster?fields=version` を読む |

## 測り直しの候補

| # | 測るもの | 閉じる問い |
|---|---|---|
| 1 | A4 の作り直し。各パート 5 GiB 以下で全体 50 GiB 超（例: 5 GiB × 10 + 11 個目に小さなパート）。形は[上の節](#全体サイズの判定に届かなかった-a4-の設計) | 全体サイズの超過が `CompleteMultipartUpload` で判定されるか。そのときの所要時間とエラーの現れ方 |
| 2 | S3 Access Point 経由の書き込みを複数回測って幅で報告する。`multipart_chunksize` を記録し、`NetworkOrigin=VPC` でも同じ手順で測る | 並列度 8 の逆転が再現するか。Internet origin と VPC origin の差 |
| 3 | スループットキャパシティの大きいファイルシステム（例: 第二世代、6,144 MBps）で同じ手順を測る | S3 Access Point 経由の経路の律速が、ファイルシステムの指定値に依存するか（今回は 128 MBps だけ） |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [上限値](../reference/limits/s3-access-point.md) | サイズ・名前・構成の上限と、その段階 |
| [設計ガイド](../reference/limits/s3ap-design-guide.md#ペイロード転送後に行われる-50-gib-の判定) | 50 GiB の判定が転送後に行われることの設計への影響 |
| [スループット / IOPS / 並列度の実測](throughput-iops-concurrency.md) | `NetworkOrigin=VPC` での S3 Access Point 経由と NFS の値（複数の指定値） |
| [プロトコル別測定の結果](perf-matrix-results.md) | 複数回・幅で報告した NFS / SMB / EFS の値。この記録の値と同じ表に並べない |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
