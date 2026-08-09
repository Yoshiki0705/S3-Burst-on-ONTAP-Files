# 検証記録 — 全方向の可視性比較と NAS バケットの制約

## 概要

4 方向の反映速度を同一条件で比較し、加えて ONTAP の NAS バケット（FlexCache duality）を
FSx for ONTAP 上で有効化できるかを確認しました。

## 検証環境

| 項目 | 値 |
|---|---|
| 計測日 | 2026-08-09（UTC） |
| リージョン | ap-northeast-1 |
| ONTAP バージョン | NetApp Release 9.18.1P3D1（両クラスタ） |
| Origin クラスタ | FsxId002ec851eba809979（`fsxmaru`）、SINGLE_AZ_1、128 MBps |
| Cache クラスタ | FsxId09ffe72a3b2b7dbbd（`FSxN_OnPre_Sim`）、SINGLE_AZ_1、128 MBps |
| 接続 | VPC ピアリング（同一リージョン、同一アカウント） |
| Origin ボリューム | `s3burst_origin_vol2`、SVM `fsxsvm02`、UNIX |
| Cache ボリューム | `s3burst_cache_vol2`、FlexCache |
| S3 Access Point | `s3burst-verify-ap`、UNIX（root） |
| クライアント | Cache VPC 内の EC2。Origin への NFS マウントは VPC ピアリング経由 |
| マウント | NFSv3、`actimeo=0` |
| オブジェクトサイズ | 64 B |
| 並列度 | 1 |
| 測定方法 | boto3 persistent session + 同一ホスト（単一クロック） |

## 全 4 方向の測定結果

| # | 方向 | p50 | p90 | p99 | max | n |
|---|---|---|---|---|---|---|
| 1 | NFS 書き込み（Origin）→ S3 AP GetObject | 44 ms | 49 ms | 328 ms | 328 ms | 30 |
| 2 | NFS 書き込み（Origin）→ FlexCache NFS 読み取り | 6 ms | 7 ms | 25 ms | 25 ms | 30 |
| 3 | S3 AP PutObject → FlexCache NFS 読み取り | 8 ms | 9 ms | 19 ms | 19 ms | 30 |
| 4 | S3 AP PutObject → Origin NFS 直接読み取り | 3 ms | 5 ms | 8 ms | 8 ms | 30 |

## 読み取れること

**方向 3 と 4 の差が FlexCache の加算分です。** p50 で +5 ms（3 ms → 8 ms）。
同一リージョン VPC ピアリング経由では FlexCache はほぼ透過です。

**方向 2 は方向 3 より速い。** NFS 書き込みは Origin のファイルシステムに直接コミットされるため
S3 API のオーバーヘッドがなく、FlexCache への伝搬も p50 6 ms で届きます。
この構成で「書き込みは Origin に集約する」と述べている根拠の一つです。

**方向 1（NFS → S3 AP）は最も遅い。** p50 44 ms で、S3 AP 側の読み出し処理が支配的です。
ただしこれは S3 API 呼び出し 1 回あたりのオーバーヘッドであり、ボリューム自体の遅延ではありません。

### 先の測定（873 ms）との食い違いについて

初回の測定では NFS → S3 AP 方向が p50 873 ms と報告していました。
この差は**測定方法の差**です。初回は `aws s3api get-object` コマンドを毎回起動しており、
CLI のプロセス起動と TLS ハンドシェイクが毎回発生していました。今回は boto3 の
persistent session を使い、接続を再利用しています。

873 ms のうち大部分は CLI の起動コストであり、ストレージの反映遅延ではありませんでした。
**正しい値は今回の p50 44 ms です。**

初回の記録（[同一ボリュームの検証記録](s3ap-nfs-visibility.md)）には、この訂正への参照を
追加しています。固定的な周期を示唆する記述は、CLI オーバーヘッドの誤認に基づいていたため、
撤回します。

## ONTAP S3 NAS バケット（FlexCache duality）の検証

### 結果: FSx for ONTAP では実質的に利用できない

ONTAP 9.18.1 は FlexCache ボリュームに対する NAS バケット（S3 マルチプロトコル）を
サポートしており、**NAS バケットの作成自体は成功しました。** ただし S3 ユーザーの作成が
プラットフォーム制約で拒否されるため、**作成したバケットに ONTAP ネイティブの S3 経由で
アクセスすることはできません。**

| 操作 | S3 AP 有効 SVM | S3 AP 未使用 SVM |
|---|---|---|
| S3 サービスの確認・作成 | `Only one object store server is supported per SVM`（FSx for ONTAP が内部で使用） | 既存サービスが利用可能（`enabled: true`） |
| S3 ユーザーの作成 | `The user does not have permission` | **同じエラー** |
| NAS バケットの作成 | `not authorized for that command` | **成功** |
| NAS バケット経由のアクセス | — | ユーザーが作れないためアクセス不可 |

> **検証上の補足**: S3 AP 未使用の SVM（`snapmirror-s3-test`）では S3 サービスが存在し
> NAS バケットの作成に成功しましたが（`type: nas`、`nas_path: /`）、S3 ユーザーの作成は
> どの SVM でも `fsxadmin` から拒否されました。FSx for ONTAP では S3 の認証は AWS 側
> （IAM + S3 Access Point ポリシー）で管理されるため、ONTAP ネイティブの S3 ユーザーは
> 存在しない設計です。

### これはプラットフォーム制約です

設定の誤りや手順の問題ではありません。FSx for ONTAP では:

- S3 AP **未使用**の SVM であれば S3 サービスは存在し、NAS バケットの作成も可能
- ただし **S3 ユーザーの作成はどの SVM でも `fsxadmin` から拒否される**
- S3 のオブジェクトアクセスに対する認証は AWS 管理の IAM + S3 Access Point ポリシーで行われるため、
  ONTAP ネイティブの S3 ユーザーという概念自体が FSx for ONTAP には存在しない
- 結果として、NAS バケットを作成できても ONTAP ネイティブ S3 クライアントからアクセスする手段がない

### この構成への影響

**FlexCache duality（ONTAP ネイティブ S3 を Cache ボリュームに付ける）は、
ベアメタル ONTAP / ONTAP Select / Cloud Volumes ONTAP のように
クラスタ管理者が完全な権限を持つ環境でのみ利用可能です。**

FSx for ONTAP で Cache ボリュームに S3 アクセスを提供する唯一の経路は、
FSx for ONTAP 管理の S3 Access Point を FlexCache ボリュームに接続することです。
これは本リポジトリの[サポート状況](../support-matrix.md)が**未確認**としている項目であり、
この構成の設計では意図的に使っていません。

この結果は、**2 つの機構がさらに明確に分かれている**ことを実証しています。
「ONTAP 9.18.1 で NAS バケットが FlexCache をサポートした」という事実は、
「FSx for ONTAP ユーザーが FlexCache ボリュームに NAS バケットを作れる」ことを意味しません。
プラットフォームの制約がそれを分離しています。

## 検証環境の状態

すべてのリソースは削除済みです（[FlexCache 検証記録](flexcache-s3ap-visibility.md)の
「検証環境の作成と削除」節と同じ形式）。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [FlexCache 検証記録](flexcache-s3ap-visibility.md) | 初回の FlexCache 伝搬測定 |
| [同一ボリュームの検証記録](s3ap-nfs-visibility.md) | 初回の同一ボリューム測定（NFS → S3 方向は本記録で訂正） |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
| [用語の整理](../reference/glossary/object-access-on-ontap.md) | 機構の区別 |
