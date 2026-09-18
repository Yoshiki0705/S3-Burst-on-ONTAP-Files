# パラメータの選び方（考える必要があるのは 5 個）
<!-- lang-switcher:start -->
🌐 [日本語](choosing-parameters.md) | [English](../../en/deployment/choosing-parameters.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
[`environments/aws-origin/template.yaml`](../../../environments/aws-origin/template.yaml) の
パラメータは 21 個あります。**埋めないと動かないのは 2 個、判断が要るのは 3 個で、
残りは既定のままで動きます。**

先に費用から書きます。**桁が変わるのは 3 箇所だけで、そこ以外を細かく調整しても額は動きません。**

## 費用が桁で変わる 3 箇所

| パラメータ | 既定 | 単価 | 128 と 2048 の差 |
|---|---|---|---|
| **`ThroughputCapacityMBps`** | 128 | **$0.906/MBps-月**（第一世代） | 128 で約 $0.16/時、2048 で約 **$2.58/時**。**使わなくても課金されます** |
| **`HostInstanceType`** | `t3.small` | インスタンス単価 | `t3.small` は約 $0.03/時、`c5n.9xlarge` は **$2.448/時**。**停止すれば止まります** |
| **`StorageCapacityGiB`** | 1024 | **$0.15/GB-月** | 1,024 GiB で約 $0.21/時。**プロビジョニングした量に課金され、使用量ではありません** |

単価は ap-northeast-1 のリスト価格（2026-09-04 取得）。内訳と他の課金次元は
[検証パターンごとの費用構造](../reference/comparison/finops-performance-test-patterns.md)にあります。

**4 番目の費用はこのテンプレートの外にあります。** SSD IOPS は
`DiskIopsConfiguration` で、テンプレートはパラメータに出していません。既定は
`AUTOMATIC`（SSD 1 GiB あたり 3 IOPS）で、**読み取りの上限として先に効きます。**
上げるなら作成後に `aws fsx update-file-system` です（**追加分が $0.0204/IOPS-月**、
反映に実測 18〜23 分、**下げるには 6 時間のクールダウン**）。

> **「大きいほうを買っておく」が効かない場所です。** 第一世代 2048 MBps を保持するだけで
> 月約 $1,855 になります。**必要なのが意味論の確認なら 128 で足り**、性能を測るときだけ
> 上げて、測ったら下げるか消してください。

## 埋めないと動かない 2 個

| パラメータ | 決め方 |
|---|---|
| `VpcId` | 既存の VPC。テンプレートは作りません |
| `SubnetId` | **ファイルシステムと検証ホストが同じサブネット**になります。管理エンドポイントへ到達でき、AZ をまたぐ遅延が測定に入らないためです |

```bash
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,Tags[?Key==`Name`]|[0].Value]' --output table
aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-xxxxxxxx \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock]' --output table
```

**選んだサブネットが要件を満たすかは `make preflight-pre` が読みます**（空き IP、
Session Manager への到達性、リージョンの枠）。

## あとから変えられない 3 個

| パラメータ | 変えられない理由 | 決め方 |
|---|---|---|
| **`OriginVolumeSecurityStyle`** | **Cache が Origin から継承すると扱っています。** 変えると配布側を作り直すことになります | 配布が **NFS なら `UNIX`**、**SMB なら `NTFS`**。`MIXED` は選べません（AWS が上級者向けとしているため）。`NTFS` は SVM に CIFS サーバーが必要で、このテンプレートは作りません |
| S3 Access Point の `FileSystemIdentity` | 作成後に変更不可 | **アクセスポイント経由の全リクエストがこの 1 つの識別情報で認可されます。** 読み取り専用と書き込みはアクセスポイントを分けます |
| S3 Access Point の `NetworkOrigin` | 作成後に変更不可 | 単一ホストでの確認なら `VPC`。どちらでも、VPC 内から呼ぶなら S3 の VPC エンドポイントと経路が要ります |

**下 2 つはこのテンプレートのパラメータではありません**（アクセスポイントは別スタックか CLI で
作ります）。それでも**ここに並べてあるのは、決める順番がこの 3 つで同じだからです** — どれも
作ってから気づくと作り直しになります。根拠は[最初に決めること](../design-first-decisions.md)。

## 判断が要る 3 個

| パラメータ | 既定 | 変える条件 |
|---|---|---|
| `DeployVerificationHost` | `true` | **既に VPC 内にホストがあるなら `false`。** ホストが無いと ONTAP 側の操作（FlexCache、ピアリング、版の確認）が一切できません。管理エンドポイントはプライベートアドレスです |
| `AssociatePublicIp` | `false` | **NAT も VPC エンドポイントも無いサブネットなら `true`。** 受信経路にはなりません（ホストの SG に受信ルールはありません）。判断は `make preflight-pre` の出力で足ります |
| `HostS3DataAccess` | `false` | **ホスト自身が S3 に書くなら `true`。** マウントするだけなら不要です。`true` にしたら `HostS3ResourceArns` を実際の ARN に絞ってください（既定は `*`） |

> **`*` が既定である理由は隠していません。** S3 Access Point は別スタック、S3 Files は別の手順で
> 作るので、**このテンプレートを適用する時点でどちらの ARN も存在しません。** 他の人のバケットが
> 同じアカウントにあるなら、作成後に絞ってください。`HostS3FilesResourceArns` と
> `HostEfsResourceArns` は別のステートメントで、`HostS3ResourceArns` を絞っても届きません。

## 残りを変える条件

| パラメータ | 既定 | 触る場面 |
|---|---|---|
| `FileSystemName` / `SvmName` / `OriginVolumeName` | `s3burst-origin` / `origin_svm` / `origin_vol` | 1 アカウントに複数立てるとき。**ONTAP の名前は英数字とアンダースコアだけ**で、ハイフンは使えません |
| `OriginVolumeSizeMB` | 10240（10 GiB） | 測定するとき。**読み取りの測定には、インメモリキャッシュの 2 倍以上を 1 回で読めるサイズ**が要ります |
| `HostVolumeSizeGiB` | 20 | 測定器やログを置くとき（VDBENCH と JDK で数 GiB） |
| `AllowFlexCachePeering` / `PeerSecurityGroupId` | `false` / 空 | **Cache 側を別スタックで作るときだけ。** 2 つ揃って初めて効きます。**有効にすると撤去が順序依存になります**（[撤去](aws-cloudformation.md#5-削除)） |
| `HostS3ResourceArns` / `HostS3FilesResourceArns` / `HostEfsResourceArns` | `*` | 上記のとおり、作成後に絞る |
| `ProjectName` / `Environment` | `s3-burst-on-ontap-files` / `verify` | タグ。**`prod` は選択肢に入れていません** — このテンプレートは検証環境を作るもので、本番の型ではありません（[検証環境と本番の差分](../from-verification-to-production.md)） |

## 自分の環境での見積もり手順

**このリポジトリの数値をそのまま使わないでください。** リージョンと時期で単価が変わります。

1. **構成を決める**（上の 3 箇所だけ）
2. **時間単価を出す**: `ThroughputCapacityMBps × $/MBps-月 ÷ 730` + `StorageCapacityGiB × $/GB-月 ÷ 730` + インスタンス単価
3. **保持時間を掛ける。** 撤去に時間がかかることを入れてください（実測で
   ファイルシステムの削除に 53 分、2.2 TiB では 63 分）
4. **撤去後に `make sweep` を読む。** 最終バックアップと未アタッチ EBS は、消し忘れると
   月単位で残ります（実測で io2 4 本が月 $361）

単価の取得元と課金次元の分解は
[FinOps の費用構造](../reference/comparison/finops-s3-vs-s3ap.md)にあります。

## 関連ドキュメント

- [最初の 1 時間](../quickstart.md) — 最小構成で 1 回通す
- [収集側のデプロイ](aws-cloudformation.md) — 全手順と、うまくいかないときの表
- [最初に決めること](../design-first-decisions.md) — Origin 作成前に決める 1 つ
- [検証環境と本番の差分](../from-verification-to-production.md) — このテンプレートを本番に持っていくとき
- [検証パターンごとの費用構造](../reference/comparison/finops-performance-test-patterns.md) — 単価と消し忘れ

---

<!-- lang-switcher:start -->
🌐 [日本語](choosing-parameters.md) | [English](../../en/deployment/choosing-parameters.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
