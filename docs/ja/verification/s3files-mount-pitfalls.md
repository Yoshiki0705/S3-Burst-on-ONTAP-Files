# 検証記録 — S3 Files のマウントで踏んだ落とし穴（EFS 由来の経路を含む）

<!-- ontap-version-exempt-file: this records Amazon S3 Files / Amazon EFS mount behaviour; ONTAP is
     not involved. -->

**この記録は、S3 Files のスループット測定（[測定計画](s3files-throughput-matrix-plan.md) の
S-1〜S-4）に入る前に、マウントが通らず止まった事象の切り分けである。** 測定値はまだ無い。
ここに置くのは、同じ構成で測ろうとする人が同じ所で止まらないための、原因と対処である。

S3 Files は Amazon EFS 上に構築されており、マウント経路は EFS のマウントヘルパー
（`amazon-efs-utils` の `efs-proxy`）をそのまま使う。**したがって EFS のマウント落とし穴が
そのまま effective で、S3 Files 固有の前提がそこに乗る。** 両方を分けて記録する。

## 症状

専用 VPC（IGW + パブリックサブネット、c5n.9xlarge、Amazon Linux 2023、`amazon-efs-utils` 3.3.2）で
`mount -t s3files -o accesspoint=... <fs>:/ <mnt>` が **15 秒ごとにタイムアウトして進まない。**

- `efs-proxy` は起動し、マウントターゲットの 2049 へ TCP を**確立している**（`ss` で ESTAB を確認）
- S3 への 443 も、サービスエンドポイントの 2049 も到達する
- それでも `mount.nfs4 127.0.0.1:/` が完了しない

**ネットワーク・DNS・到達性はすべて正常で、原因はそこではなかった。**

## 原因 — CloudWatch Logs の経路によるマウントのブロック

`efs-proxy` のログ（`/var/log/amazon/efs/<fs>.*.efs-proxy.log`）に決め手があった。

```text
WARN  cw_publisher Failed to create log group: AccessDeniedException ... logs:CreateLogGroup
      on resource arn:aws:logs:...:log-group:/aws/efs/utils ... no identity-based policy allows
WARN  cw_publisher Failed to emit CloudWatch metric: AccessDenied ... cloudwatch:PutMetricData
ERROR nfs::nfs_reader Error sending message batch to dispatcher DispatchingFailure
INFO  controller Proxy incarnation restarted, restart_count=3
```

**マウントヘルパーは、NFS 接続を確立する前に CloudWatch Logs のロググループ `/aws/efs/utils` を
作ろうとする。** その API 呼び出しが失敗（権限不足）すると `efs-proxy` が再起動を繰り返し、
NFS マウントが完了しない。これは AWS の記事が「原因不明でマウントが無限にハングする」の
根本原因として明示している挙動である
（[プライベートサブネットでの S3 Files マウント](https://repost.aws/articles/ARPg3C_iUzSkWA3l1gdUPUJA/mounting-amazon-s3-files-on-ec2-instances-in-private-subnets-without-internet-access)）。

**この環境は IGW を持つので CloudWatch Logs 自体には到達できる。** 詰まったのは到達性ではなく、
**ホストロールに `logs:CreateLogGroup` と `cloudwatch:PutMetricData` が無かったこと**だった。
記事の環境（プライベートサブネット）では「CloudWatch Logs の VPC エンドポイントが無い」が原因になる。
**到達できないのと、到達できるが権限が無いのは、同じ症状（無言のハング）に化ける。**

## 対処（3 つ、どれでも解消する）

| # | 対処 | 使いどころ |
|---|---|---|
| 1 | ホストロールに `logs:CreateLogGroup` / `logs:CreateLogStream` / `logs:PutLogEvents` と `cloudwatch:PutMetricData` を付与 | IGW か CloudWatch 系エンドポイントがあり、監視メトリクスも使いたいとき。本検証で採用 |
| 2 | マウントヘルパーの CloudWatch ロギングを無効化（`/etc/amazon/efs/s3files-utils.conf`） | 権限もエンドポイントも足したくないとき。測定だけが目的なら十分 |
| 3 | CloudWatch Logs の VPC エンドポイント（`com.amazonaws.<region>.logs`）を作る | プライベートサブネット（IGW/NAT 無し）のとき |

**本検証は 1 を採る。** スループット測定では proxy の CloudWatch メトリクス（接続性・バイト数）を
頭打ちの帰属に使うため、無効化（2）はしない。

> **成功レスポンスは成功の証拠ではない、の裏返し。** `aws s3files create-mount-target` も
> `create-file-system` も成功を返す。マウントが通らないのは作成の失敗ではなく、**ホスト側の
> ロギング経路**にある。作成 API の成功は、マウントできることの根拠にならない。

## S3 Files 固有の前提（EFS と違う点）

マウントヘルパーは EFS と共通だが、S3 Files では次が追加で要る。省くとマウントかデータ経路の
どちらかで止まる。

| 前提 | 省いたときの症状 | 出典 |
|---|---|---|
| **botocore を dnf で入れる**（`pip3` では入らない） | `access denied by server while mounting 127.0.0.1:/`、または CloudWatch メトリクス不可 | [Prerequisites for S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-prereq-policies.html) |
| ホストロールに `s3files:ClientMount`（最低限）、書き込むなら `ClientWrite`、root なら `ClientRootAccess` | `Access denied during mount`、または非 root の書き込み拒否 | [Troubleshooting S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-troubleshooting.html) |
| バケットに `s3:GetObject` / `s3:GetObjectVersion` のインラインポリシー | **マウントは成功するが、1 MiB 以上の読み取りが高性能ストレージ経由に落ちる**（intelligent read routing が効かない） | 同上 |
| マウントターゲットがクライアントと**同一 AZ** | `Failed to resolve file system DNS name` | 同上 |
| マウントターゲット SG が EC2 SG から 2049 inbound | `Connection timed out` | 同上 |

## intelligent read routing の確認（測定の正しさに直結）

S3 Files は小さい読みを高性能ストレージから、1 MiB 以上をバケット直読から返す。**どちらを通ったかは
推測せず、CloudWatch のクライアント接続性メトリクスで確かめる。**

| メトリクス | 0 のときの意味 |
|---|---|
| `NFSConnectionAccessible` | NFS 経路が確立していない |
| `S3BucketAccessible` | proxy がバケットに到達できていない |
| `S3BucketReachable` | ネットワーク経路（エンドポイント / NAT）が無い |

**どれかが 0 のまま測ると、経路の違う数値を 1 つの表に混ぜることになる。** S-2（大ファイル）と
S-3（キャッシュ温度）の帰属は、このメトリクスが 3 つとも 1 であることを確認してから読む。

## `nodirects3read` と 5 秒ストール（別の落とし穴）

これはハングとは別の、既定マウントが毎回払う固定費である。**S3 ゲートウェイエンドポイントが無い
構成**では、proxy が新規マウントごとに S3 への直読を 1 回試み、**5 秒のタイムアウト**を待ってから
サービス経路へ落ちる。`nodirects3read` を付けるとこの直読経路を飛ばす。

| 構成 | 既定マウント | `nodirects3read` |
|---|---|---|
| ゲートウェイエンドポイント無し | 毎マウント 5 秒ストール、スループットも落ちる | ストール無し |
| ゲートウェイエンドポイント有り（本検証） | 直読が速い（大きい逐次読みで有利） | 直読を捨てるので付けない |

数値（記事記載、実機未確認）: 直読が無効な経路で 5 MB ファイルが 5,374 ms / 977 kB/s、
`nodirects3read` で 244 ms / 22.1 MB/s。**本検証はゲートウェイエンドポイントを置いたので
`nodirects3read` は付けない**（大ファイル直読が S-2 の論点そのもの）。

> **監査上の違いも記録する。** `nodirects3read` では S3 アクセスログの principal が **S3 Files の
> サービスロール**、ゲートウェイエンドポイント経由の直読では **EC2 インスタンスロール**になる。
> アクセスログで誰が読んだかを見る設計では、この差が効く。

## クライアント側のデバッグログの出し方

切り分けに使ったもの。`/etc/amazon/efs/s3files-utils.conf` を編集して再マウントする。

| 対象 | 設定 | 出力先 |
|---|---|---|
| マウントヘルパー / watchdog | `[DEFAULT] logging_level = DEBUG` | `/var/log/amazon/efs/mount.log` |
| proxy | `[proxy] proxy_logging_level = DEBUG` | `/var/log/amazon/efs/*.efs-proxy.log` |
| TLS トンネル（stunnel） | `[mount] stunnel_debug_enabled = true` | 既定は無効 |

**proxy ログがこの切り分けの決め手だった。** マウントヘルパーの `mount.log` だけ見ていると
「15 秒タイムアウト」しか分からず、CloudWatch Logs でブロックされていることは proxy ログの
`cw_publisher` 行で初めて見える。

## 測定計画への反映

[測定計画](s3files-throughput-matrix-plan.md) の環境要件に次を追加する（この記録で判明したぶん）。

- ホストロールに CloudWatch Logs（`logs:CreateLogGroup` / `CreateLogStream` / `PutLogEvents`）と
  `cloudwatch:PutMetricData` を付ける。無いとマウントが無言でハングする
- botocore は dnf で入れる（`pip3` 不可）
- マウント後、`NFSConnectionAccessible` / `S3BucketAccessible` / `S3BucketReachable` が
  3 つとも 1 であることを確認してから測る
- ゲートウェイエンドポイントの有無で `nodirects3read` の要否が変わる。本検証は有りなので付けない

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [S3 Files のファイルシステム性能の測定計画](s3files-throughput-matrix-plan.md) | S-1〜S-4。この記録はその前段の切り分け |
| [Amazon S3 Files の実測](s3files-measured.md) | 反映と意味論の実測（別ホスト・別 VPC で成功した回） |
| [S3 Files 検証環境セットアップ](../deployment/aws-s3files-compare.md) | 作成・マウント・破棄の手順 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |

## 出典

| ドキュメント | 参照した内容 |
|---|---|
| [Troubleshooting S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-troubleshooting.html) | マウント失敗の原因分類、intelligent read routing のメトリクス、デバッグログ |
| [Mounting S3 file systems on EC2](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html) | マウントヘルパーの動作、既定オプション、`tls` と `iam` の強制 |
| [Prerequisites for S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-prereq-policies.html) | botocore、IAM、`s3files-utils.conf` |
| [プライベートサブネットでの S3 Files マウント（repost.aws）](https://repost.aws/articles/ARPg3C_iUzSkWA3l1gdUPUJA/mounting-amazon-s3-files-on-ec2-instances-in-private-subnets-without-internet-access) | CloudWatch Logs がマウントをブロックする根本原因、`nodirects3read`、最小権限 |
