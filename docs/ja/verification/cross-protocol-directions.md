# 検証記録 — 全方向の可視性比較と NAS バケットの制約
<!-- lang-switcher:start -->
🌐 [日本語](cross-protocol-directions.md) | [English](../../en/verification/cross-protocol-directions.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->

## 概要

4 方向の反映速度を同一条件で比較し、加えて ONTAP の NAS バケット（FlexCache duality）を
FSx for ONTAP 上で有効化できるかを確認しました。

## 検証環境

| 項目 | 値 |
|---|---|
| 計測日 | 2026-08-09（UTC） |
| リージョン | ap-northeast-1 |
| ONTAP バージョン | NetApp Release 9.18.1P3D1（両クラスタ） |
| Origin クラスタ | ファイルシステム 1（`fs-0123456789abcdef0`、Origin 役）、SINGLE_AZ_1、128 MBps |
| Cache クラスタ | ファイルシステム 2（`fs-0abcdef1234567890`、オンプレミス相当の Cache 役）、SINGLE_AZ_1、128 MBps |
| 接続 | VPC ピアリング（同一リージョン、同一アカウント） |
| Origin ボリューム | `s3burst_origin_vol2`、SVM `fsxsvm02`、UNIX |
| Cache ボリューム | `s3burst_cache_vol2`、FlexCache |
| S3 Access Point | `s3burst-verify-ap`、UNIX（root） |
| クライアント | Cache VPC 内の EC2。Origin への NFS マウントは VPC ピアリング経由 |
| マウント | NFSv3、`actimeo=0` |
| オブジェクトサイズ | 64 B |
| 並列度 | 1 |
| 測定方法 | boto3 persistent session + 同一ホスト（単一クロック） |

> **識別情報についての注記**: この測定はアクセスポイントの識別情報を UNIX の root で行っています。アクセスポイント経由の全リクエストがこの 1 つの識別情報で認可されるため、root を指定するとファイル権限による絞り込みが効きません（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--絞り込みを担うファイルシステム側の権限)）。測定条件としてそのまま記録しますが、推奨構成ではありません。書き込みに必要な権限だけを持つ専用ユーザーを使い、用途ごとにアクセスポイントを分けてください（`FileSystemIdentity` は作成後に変更できません）。

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

### 結果: 通常ボリュームでは動作、FlexCache ボリュームでは S3 データアクセス不可

検証は段階的に進め、結論が各段階で変わりました。最終状態を先に述べ、経過を後に置きます。

**通常ボリュームの NAS バケット: 完全に動作**（NFS 書き込み → ONTAP S3 読み取り、内容一致）。
**FlexCache ボリュームの NAS バケット: 作成は成功するが、S3 データ操作は `AccessDenied`。**

#### 通常ボリューム（NAS バケット読み取り: 成功）

S3 AP を一度も使っていない SVM（`snapmirror-s3-test`）で、ONTAP CLI（SSH）経由で操作しました。
REST API では S3 ユーザー作成が拒否されますが、CLI では成功します。

| 操作 | 方法 | 結果 |
|---|---|---|
| S3 サービス確認 | CLI | ✅ 既存（`sm-s3-server`、HTTP port 80、`up`） |
| S3 ユーザー作成 | REST API | ❌ `The user does not have permission to access the requested resource` |
| S3 ユーザー作成 | CLI `vserver object-store-server user create` | ✅ access key + secret key 取得 |
| NAS バケット作成 | CLI | ✅（`type: nas`、`nas-path: /duality_test`） |
| バケットポリシー | CLI | ✅ |
| NFS 書き込み → `GetObject` | boto3 → `http://<data-lif>:80` | ✅ **成功。内容一致** |
| `ListObjectsV2` | 同上 | ✅ オブジェクト一覧取得 |
| `PutObject` | 同上 | ❌ `AccessDenied`（NAS バケットは読み取り専用ビュー、仕様どおり） |

#### FlexCache ボリューム（NAS バケット: 作成成功、データアクセス不可）

| 操作 | 結果 |
|---|---|
| FlexVol Origin → FlexCache → NAS バケット作成 | ❌ `Only FlexCache volumes with FlexGroup origin volumes support NAS buckets` |
| FlexGroup Origin 作成（CLI `-auto-provision-as flexgroup`） | ❌ `No suitable storage... Aggregates not matching FabricPool requirements: aggr1` |
| FlexGroup Origin 作成（FSx for ONTAP API `VolumeStyle: FLEXGROUP`、200 GiB、`ConstituentsPerAggregate: 2`） | ✅ |
| FlexGroup Origin → FlexCache 作成（50 GB） | ✅ |
| FlexCache 上に NAS バケット作成 | ✅（`type: nas`、`nas-path: /duality_fc_fg`） |
| バケットポリシー（`* / *` ワイルドカード） | ✅ |
| `HeadBucket` | ✅ |
| `ListObjectsV2` | ❌ **`AccessDenied`** |
| `GetObject`（ファイルは NFS 経由で書き込み済み、権限 `644`） | ❌ **`AccessDenied`** |

**同じ SVM、同じ S3 ユーザー、同じバケットポリシーで、通常ボリュームでは `GetObject` が
成功し、FlexCache ボリュームでは拒否されます。** ファイルの UNIX パーミッションを
world-readable にしても結果は変わりません。

#### 決定的な切り分け: 同一条件での比較

同一セッション内で、FlexVol（通常）と FlexCache の両方にNAS バケットを作り、
同一の S3 ユーザー・同一のワイルドカードポリシー・同一のデータ LIF で同時にテストしました。

| 操作 | FlexVol NAS バケット（`getobj_flexvol`） | FlexCache NAS バケット（`duality_fc_fg`） |
|---|---|---|
| HeadBucket | ✅ | ✅ |
| ListObjectsV2 | ✅（KeyCount=1） | ❌ AccessDenied |
| GetObject | ✅ **SUCCESS**（`FLEXVOL-GETOBJECT-TEST`） | ❌ AccessDenied |
| NFS での読み取り | ✅ | ✅ |

ファイルはどちらも NFS 経由で書き込み、`chmod 644` で world-readable にしています。
**問題は FlexCache ボリューム固有**であり、FlexGroup であるかどうかではありません
（通常ボリュームのテストも FlexVol で成功しています）。

### 前回の結論からの訂正

前回「S3 ユーザーが作れないためアクセス不可」と報告していました。これは REST API のみを
試した時点の結論で、**ONTAP CLI（SSH）経由では S3 ユーザーの作成に成功します。**
REST API と CLI で `fsxadmin` の権限マッピングが異なることが原因でした。

### FSx for ONTAP 固有の制約（まとめ）

| 項目 | 状態 |
|---|---|
| S3 AP 有効 SVM で ONTAP S3 を操作 | ❌ 権限が AWS 側に移される |
| S3 AP 未使用 SVM で ONTAP S3 を操作（CLI） | ✅ |
| S3 AP 未使用 SVM で ONTAP S3 を操作（REST API） | ❌ ユーザー作成が拒否される |
| 通常ボリュームに NAS バケット → S3 読み取り | ✅ |
| FlexCache ボリュームに NAS バケット → S3 読み取り | ❌ → ✅ **`-is-s3-enabled true` で動作確認済み**（下記参照） |
| FlexGroup を CLI で作成 | ❌ FabricPool アグリゲートとの互換性エラー |
| FlexGroup を FSx for ONTAP API で作成 | ✅（最小 100 GiB / constituent） |

### この構成への影響

**追記（2026-08-10）: FlexCache duality は `-is-s3-enabled true` の設定で動作することが確認されました。**

NetApp プロダクトチームからのフィードバックにより、FlexCache ボリュームに対して S3 アクセスを
明示的に有効化する必要があることが判明しました：

```bash
set -privilege advanced
flexcache config modify -vserver snapmirror-s3-test -volume duality_fc_s3en -is-s3-enabled true
```

設定後の結果:

| 操作 | `-is-s3-enabled` 未設定 | `-is-s3-enabled true` 設定後 |
|---|---|---|
| HeadBucket | ✅ | ✅ |
| ListObjectsV2 | ❌ AccessDenied | ✅ KeyCount=1 |
| GetObject | ❌ AccessDenied | ✅ **内容一致** |

`fsxadmin` で advanced 権限コマンドが実行可能であることも確認済みです。
出典: [Enable S3 access to NAS FlexCache volumes](https://docs.netapp.com/us-en/ontap/flexcache/enable-flexcache-duality.html)

**ただし、この構成は引き続き「Cache 側は NFS/SMB で使う」を推奨します。** 理由:

- ONTAP ネイティブ S3（NAS バケット）と AWS マネージドの S3 Access Point は別の機構
- NAS バケットは読み取り専用（PutObject 不可）
- advanced 権限 + S3 ユーザー管理が追加で必要
- IAM 統合やアクセスポイントポリシーによるガバナンスがない

## 検証環境の状態

すべてのリソースは削除済みです（[FlexCache 検証記録](flexcache-s3ap-visibility.md)の
「検証環境の作成と削除」節と同じ形式）。

## SMB での追加検証

### 検証環境（SMB 追加分）

| 項目 | 値 |
|---|---|
| 計測日 | 2026-08-10（UTC） |
| CIFS サーバー | `SMBTEST01`（SVM `snapmirror-s3-test`、ドメイン `s3burst.local`） |
| Active Directory | AWS Managed AD（Standard）、`s3burst.local` |
| マウント方法 | `mount -t cifs`、オプション `cache=none`、SMB 3.0 |
| 比較対象 | 同一環境の NFS（`actimeo=0`）を並行測定 |

### 結果: S3 AP PutObject → FlexCache 読み取り（プロトコル比較）

| プロトコル | マウント方法 | p50 | p90 | max | n |
|---|---|---|---|---|---|
| **SMB** | `mount -t cifs`, `cache=none` | **7 ms** | 8 ms | 9 ms | 30 |
| **NFS** | `mount -t nfs`, `actimeo=0` | **7 ms** | 8 ms | 15 ms | 30 |

**持続接続では SMB と NFS は同等です。** プロトコルによる差はありません。

### smbclient での測定（参考値）

`smbclient`（毎回プロセス起動 + セッション確立）を使った場合：

| プロトコル | 方法 | p50 | p90 | max |
|---|---|---|---|---|
| SMB | `smbclient`（毎回セッション確立） | 43 ms | 68 ms | 443 ms |
| NFS（同一環境、参考） | `mount -t nfs`, `actimeo=0` | 7 ms | 17 ms | 28 ms |

43 ms の大部分は SMB セッション確立のオーバーヘッドです。これは `aws s3api` CLI の
コールドスタート問題（初回測定で NFS→S3 AP が 873 ms と出た原因）と同じ構造であり、
**持続接続を使う本番環境では発生しません。**

### 含意

- この構成の「利用（読み取り）」層は NFS でも SMB でも同じパフォーマンスが得られます
- プロトコル選択は性能ではなく、クライアント OS とセキュリティモデルで決まります
- SMB を使う場合、SVM に CIFS サーバーが必要です。**Active Directory 参加は必須ではありません**（[workgroup モードの公式手順](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html)。NTLM のみで Kerberos 非対応、GPO・VSS・SMB3 CA 共有も対象外）。workgroup モードのローカル Windows ユーザーで S3 Access Point の Windows 識別情報が機能した実測があります（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2-の前提--ファイルシステム側に実在している必要のある固定-id)）。**この測定は AWS Managed AD 参加の環境で行っており、workgroup モードは試していません**
- UNIX セキュリティスタイルの Origin に SMB でアクセスする場合、NTFS ACL ではなく
  UNIX パーミッションに基づくアクセス制御が適用されます

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [FlexCache 検証記録](flexcache-s3ap-visibility.md) | 初回の FlexCache 伝搬測定 |
| [同一ボリュームの検証記録](s3ap-nfs-visibility.md) | 初回の同一ボリューム測定（NFS → S3 方向は本記録で訂正） |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
| [用語の整理](../reference/glossary/object-access-on-ontap.md) | 機構の区別 |
| [性能の語の日英対訳](../reference/glossary/performance-terms-ja-en.md) | 上限の種別と測定条件の語 |

---

<!-- lang-switcher:start -->
🌐 [日本語](cross-protocol-directions.md) | [English](../../en/verification/cross-protocol-directions.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
