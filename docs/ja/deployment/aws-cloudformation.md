# 収集側のデプロイ（AWS / CloudFormation）

<!-- lang-switcher:start -->
🌐 [日本語](aws-cloudformation.md) | [English](../../en/deployment/aws-cloudformation.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->

この構成の収集側 — FSx for ONTAP、SVM、Origin ボリューム、そして VPC 内の検証ホスト — を
1 スタックで作ります。テンプレートは
[`environments/aws-origin/template.yaml`](../../../environments/aws-origin/template.yaml) です。

配布側は別のツールで作ります（[配布側のデプロイ](onprem-terraform.md)）。
理由は[環境テンプレートの索引](../../../environments/README.md)にあります。

## 所要時間

| 手順 | 目安 |
|---|---|
| 1. 前提の確認 | 5 分 |
| 2. スタックの作成 | 25〜40 分（FSx for ONTAP の作成待ちが大半） |
| 3. S3 Access Point の作成 | 5 分 |
| 4. マウントと疎通確認 | 10 分 |
| 5. 削除 | 20 分 |

## 1. 前提

- **利用拠点のプロトコルを決めてあること。** NFS なら UNIX、SMB なら NTFS を
  `OriginVolumeSecurityStyle` に指定します。**後から変えると配布側を作り直すことになります。**
  理由と出典は[最初に決めること](../design-first-decisions.md)にあります。
  MIXED は選べないようにしてあります
- VPC とサブネットが 1 つずつあること。ファイルシステムと検証ホストは同じサブネットに置きます
- サブネットから SSM に到達できること（NAT ゲートウェイ、または SSM の VPC エンドポイント）。
  検証ホストは受信ルールを持たず、キーペアも使いません
- `aws` CLI が認証済みであること

> **ネットワークに関する補足**: **配布側を繋ぐなら、このテンプレートが開けないポートが 2 つあります。**
> クラスタピアリングは**インタークラスタ LIF 間の TCP 11104-11105** を使い、そこは
> **双方のファイルシステムのセキュリティグループに、相手側からの許可を自分で足す**必要があります。
> このテンプレートは 1 台分しか作らないので、相手側の存在を知りません。
>
> | 何を許可するか | どちらの SG に | ポート |
> |---|---|---|
> | クラスタピアリング | **双方向**（Origin 側 SG に Cache 側 SG から、Cache 側 SG に Origin 側 SG から） | TCP **11104-11105** |
> | ONTAP REST / CLI | 相手側の SG に、作業ホストの SG から | TCP 443 / 22 |
> | NFSv3 | Cache 側 SG に、利用側の SG から | TCP 2049 / 111 / 635 / 4045-4046 |
>
> **リージョンを跨ぐ場合は SG 参照が使えず、CIDR で書くことになります**
> （[配布側のデプロイ](onprem-terraform.md)に既出）。到達性そのものの確認手順は
> [PoC チェックリスト](../poc-checklist.md)にあります。

> **セキュリティに関する補足**: `NTFS` を選ぶ場合、SVM に CIFS サーバーが必要です。
> **このテンプレートは CIFS サーバーの作成も Active Directory 参加も行いません。**
> AD 参加は必須ではなく、ドメインが利用できない場合は workgroup モードで構成できます
> （[公式手順](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html)。NTLM のみで Kerberos は非対応）。
> **AD 参加を選んだ場合**は、S3 Access Point 経由の**すべてのデータ操作**にドメインコントローラーへの
> 到達性が必要です。`HeadBucket` は AD が到達不能でも成功するため、疎通確認には使えません。
> 確認は必ずデータ操作で行ってください。

## 2. スタックの作成

**パラメータは 19 個ありますが、書き換えが必要なのは 2 個だけです。** 残りは既定のまま動きます。
**1 個だけ、既定のままにしてはいけないもの（作り直しになる決定）があります。**

| 何を | どうする | なぜ |
|---|---|---|
| `VpcId` / `SubnetId` | **必ず自分の値に置き換える** | 置き換えないと存在しない ID で失敗します |
| `OriginVolumeSecurityStyle` | **既定は `UNIX`。SMB で読むなら `NTFS` に変える** | **後から変えられません。**[最初に決めること](../design-first-decisions.md)にある唯一の不可逆な選択です |
| 残り 16 個 | **触らなくてよい** | 検証に使った値です。費用は下の見積りのとおりで、`StorageCapacityGiB` と `ThroughputCapacityMBps` を上げると比例して増えます |

**`VpcId` と `SubnetId` は次で調べられます。**

```bash
# 自分のアカウントの VPC を一覧する（Name タグ付き）
aws ec2 describe-vpcs --region ap-northeast-1 \
  --query 'Vpcs[].[VpcId,CidrBlock,Tags[?Key==`Name`].Value|[0]]' --output table

# 選んだ VPC のサブネットを一覧する。ファイルシステムと検証ホストは同じサブネットに置きます
aws ec2 describe-subnets --region ap-northeast-1 \
  --filters Name=vpc-id,Values=<選んだ VpcId> \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,AvailableIpAddressCount]' --output table
```

**`AvailableIpAddressCount` を見てください。** ファイルシステムは複数の IP を取るので、
空きが乏しいサブネットでは作成が失敗します（下の[うまくいかないとき](#うまくいかないとき)の 1 行目）。

```bash
cd environments/aws-origin
cp params.example.json params.json    # params.json は追跡されません
# VpcId と SubnetId を上で調べた値に変更する
#
# スループットを測る場合は params.throughput.example.json を使う。t3.small ではなく
# c5n.9xlarge を指定し、ホストに S3 のデータ経路権限を与える構成で、費用が上がる。
# 差分の理由はそのファイルの _comment に書いてある

aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name s3burst-origin \
  --parameter-overrides file://params.json \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

> **共有アカウントで先に見るパラメータ。** `HostS3DataAccess=true` は 3 つのステートメントを
> 開けます。**既定はすべて `"*"` で、これはファイルシステムやバケットがこのテンプレートの外で
> 作られるためです。** ARN が決まったら 3 つとも絞ってください。
>
> | パラメータ | 絞る値 | `"*"` のまま置いた場合 |
> |---|---|---|
> | `HostS3ResourceArns` | バケット / S3 Access Point の ARN | アカウント内の全バケットにオブジェクト操作 |
> | `HostS3FilesResourceArns` | `arn:aws:s3files:<region>:<account>:file-system/<id>` | アカウント内の全 S3 Files ファイルシステムにマウント権 |
> | `HostEfsResourceArns` | `arn:aws:elasticfilesystem:<region>:<account>:file-system/<id>` | アカウント内の全 EFS ファイルシステムにマウント権 |
>
> **3 つとも絞れます。** マウント系の 2 つは以前「リソースレベル ARN を取らないので絞れない」と
> 書いていましたが、[認可リファレンス](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3files.html)は
> `ClientMount` / `ClientWrite` / `ClientRootAccess` に `file-system` を必須と示しています。

`fsxadmin` のパスワードは Secrets Manager で生成され、テンプレートの外に出ません。
検証ホストの IAM ロールだけがこのシークレットを読めます。

> **運用上の補足**: この「シークレットをファイルシステムと一緒に作る」形は、既存の検証環境で
> 実際に困ったことへの対処です。そこでは `fsxadmin` のシークレットが既に存在しない
> ファイルシステムを指しており、ONTAP しか持たない操作（FlexCache の作成など）に
> 着手できませんでした。ファイルシステムと同時に作られた資格情報はこの問題を起こしません。

### 出力の確認

```bash
aws cloudformation describe-stacks --stack-name s3burst-origin \
  --query 'Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}' --output table
```

`ManagementEndpoint` は**VPC 内からのみ**到達します。手元の端末からは届きません。
ONTAP のバージョンとSVM の NFS エンドポイントは CloudFormation の属性として取得できないため、
出力にはそれを読むためのコマンドが入っています。

> **バージョンに関する補足**: 公開する測定値には ONTAP のバージョンを併記する必要がありますが、
> `AWS::FSx::FileSystem` はバージョンを属性として公開していません。Amazon FSx の API も当てになりません <!-- allow:naming - サービスファミリーの API 名。FSx for ONTAP の略記ではない -->
> （既存のファイルシステムでは `DescribeFileSystems` が `FileSystemTypeVersion` を返しませんでした）。
> 確実な取得元は ONTAP 自身です。このスタックが資格情報と 443 番ポートを用意しているのは
> そのためでもあります。

## 3. S3 Access Point の作成

`AWS::FSx::S3AccessPointAttachment` があるので、推奨は 2 つ目のスタックで作ることです。
[`patterns/collect/s3-access-point-attachment/`](../../../patterns/collect/s3-access-point-attachment/README.md)
を使います。上のスタックに含めない理由は、アクセスポイントの設定が全て create-only で、
ポリシーを変えるだけで置き換えになること、そしてアクセスポイントの改名でボリュームを持つ
スタックを動かしたくないことの 2 点です。

```bash
aws cloudformation deploy \
  --template-file patterns/collect/s3-access-point-attachment/template.yaml \
  --stack-name s3burst-collect-ap \
  --parameter-overrides file://params.json \
  --region ap-northeast-1
```

以下の CLI も有効で、スタックに持たせる必要のない 1 回限りの作成では短い経路です。

```bash
cp access-point.example.json access-point.json
# VolumeId と VpcId を出力の値に置き換え、_comment で始まるキーを削除する
# （API は未知のトップレベルメンバーを拒否します）

aws fsx create-and-attach-s3-access-point \
  --region ap-northeast-1 \
  --cli-input-json file://access-point.json
```

**位置引数ではなく JSON ファイルを渡してください。** `--ontap-configuration` の位置引数形式は
解析が壊れやすく、そのときのエラーメッセージは引用符の問題を指してくれません。

決めることが 2 つあります。

| 設定 | 判断 |
|---|---|
| `FileSystemIdentity` | アクセスポイント経由の**全リクエストがこの 1 つの識別情報で認可されます**。呼び出し元ごとの区別は付きません。**絞り込みは 2 か所にあります。** AWS 側はアクセスポイントポリシーの明示的な拒否（`Allow` を狭くすることは絞り込みになりません）、ファイルシステム側はこの識別情報が持つファイル権限（mode bits / ACL）です。**読み取り専用にしたいなら、2 層を同時に決めてください。** 判定するのは識別情報が root でないことではなく、**その識別情報がボリュームルートに対して持つ実効権限**（`uid` / `gid` / mode bits）です。非 root にしても、ボリュームルートがその識別情報に書き込みを与えていれば書けます。AWS 側で止めるならアクセスポイントポリシーの明示的な拒否で、この場合は識別情報が root でも書けません。作成後に変更できないので、読み取り専用の利用側と書き込み側はアクセスポイントを分けます。**分けること自体は実測ではなく、下の実測から導かれる設計上の帰結です。** 実測されているのは、アクセスポイントポリシーを付けない状態でボリュームルートの `uid` / `gid` / mode bits だけを変えると `PutObject` が拒否と成功の間で切り替わることです（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--絞り込みを担うファイルシステム側の権限)）。ポリシー無しで非 root の識別情報（`nobody`、uid 65535）を固定すると `GetObject` は成功し `PutObject` は `AccessDenied` になること、同一ボリューム・同一呼び出し元で root に替えると両方成功することも実測されています（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#非-root-の-id-固定によるポリシー無しでの書き込み停止)。`ap-northeast-1`、ONTAP 9.18.1P3D1、2026-08-18）。**ただしその測定はボリュームが `755`（others に `w` が無い）である前提に依存します。** `775` や `777`、あるいはその識別情報が所有者かグループに該当する場合は書けます。**mode bits を確認せずに「非 root だから読み取り専用」とは言えません。** |
| `NetworkOrigin` | **作成後は変更できません。** `VPC` にすると単一ホストでの測定が公開経路を通らずに済みます。`Internet` は VPC の外からも書けます。**どちらの場合も、VPC 内から呼ぶなら S3 の VPC エンドポイントが要り、そのサブネットのルートテーブルに経路が関連付いている必要があります。** 姉妹リポジトリでは、経路のない VPC 内 Lambda から接続タイムアウトになる例が観測されています |

## 4. マウントと疎通確認

検証ホストへは Session Manager で入ります。

```bash
aws ssm start-session --target <VerificationHostId> --region ap-northeast-1
```

SVM の NFS エンドポイントを取得してマウントします。マウントポイントは 2 つ用意されています。

```bash
NFS_IP=$(aws fsx describe-storage-virtual-machines --region ap-northeast-1 \
  --storage-virtual-machine-ids <StorageVirtualMachineId> \
  --query 'StorageVirtualMachines[0].Endpoints.Nfs.IpAddresses[0]' --output text)

sudo mount -t nfs -o nfsvers=3,actimeo=0 "$NFS_IP":/origin_vol /mnt/origin-noac
sudo mount -t nfs -o nfsvers=3          "$NFS_IP":/origin_vol /mnt/origin-cached
```

**マウントオプションで結果が変わります。** これは実測です。
Linux の既定は `acdirmin=30` / `acdirmax=60` なので、クライアントが既に一覧を取得した
ディレクトリに現れたファイルは、ストレージ側と無関係に最大 1 分見えないことがあります。
削除の反映は `actimeo=0` で 7 ms、既定値では 2 秒を超えました。
測定するときと鮮度が要るときは `actimeo=0`、同じファイルを繰り返し読むときは既定値を使います。

疎通確認は**データ操作**で行います。

```bash
AP=arn:aws:s3:ap-northeast-1:<account-id>:accesspoint/s3burst-origin-ap
echo hello | aws s3api put-object --bucket "$AP" --key check.txt --body /dev/stdin
cat /mnt/origin-noac/check.txt          # 数十 ms 以内に見えるはず
aws s3api delete-object --bucket "$AP" --key check.txt
```

実測した所要時間と、そこから言えること・言えないことは
[検証記録](../verification/s3ap-nfs-visibility.md)にあります。

## 5. 削除

**順序が結果を変えます。** 配布側を残したまま収集側を消さないでください。

1. 配布側を先に削除する（[配布側のデプロイ](onprem-terraform.md)の削除手順）
2. SVM ピア、クラスタピアを解除する

   > **この手順を飛ばすと 4 で止まります。** SVM ピアが残っている間、FSx for ONTAP は SVM を削除せず、
   > スタックは `svmLifecycle should be DELETING, but get: MISCONFIGURED` で `DELETE_FAILED`
   > になります。
   >
   > **そして 4 は、2 を実行できる唯一のホストを先に消します。** 管理 LIF はプライベート
   > アドレスなので、検証ホストが消えると ONTAP に到達する経路がありません。
   >
   > 順序を間違えたときの復旧は 4 段階です。**同じサブネットに ONTAP へ到達できるホストを
   > 立て直し**、ピアを消し、**`aws fsx delete-storage-virtual-machine` で SVM を直接削除して**
   > からスタック削除を再試行します。**CloudFormation は `MISCONFIGURED` を見て呼び出す前に
   > 断りますが、FSx for ONTAP の API 自体は同じ状態でも受け付けます。**
   >
   > 4 段階目は**そのホストをいつ消すか**です。**SVM が消えたことを確認するまで残してください** —
   > `aws fsx describe-storage-virtual-machines` がその SVM を返さなくなるまでです。
   > **再試行が失敗すると、同じホストがもう一度必要になります。**
   > この段階は姉妹リポジトリ（VMware-Migration-EC2-ONTAP）の DR runbook の追加で、
   > **こちらはホストを消したあとに SVM がまだ `MISCONFIGURED` だと気づいて立て直しました。**
   >
   > 実際に踏んだ記録は[継承の検証記録](../verification/flexcache-security-style-inheritance.md#この手順で踏んだ罠)にあります。
3. S3 Access Point を外す

   ```bash
   aws fsx detach-and-delete-s3-access-point --region ap-northeast-1 --name s3burst-origin-ap
   ```

4. スタックを削除する

   ```bash
   aws cloudformation delete-stack --stack-name s3burst-origin --region ap-northeast-1
   aws cloudformation wait stack-delete-complete --stack-name s3burst-origin --region ap-northeast-1
   ```

Secrets Manager のシークレットは既定で復旧期間を持って削除されます。同じ名前で作り直す場合は
待つか、`--force-delete-without-recovery` を明示してください。

> **不可逆操作に関する補足**: このテンプレートは SnapLock も改ざん防止 Snapshot も
> 有効化しません。有効化するとボリューム・SVM・**ファイルシステム全体**が保持期間中
> 削除できなくなります。検証環境はそれを置く場所として最悪です。
> 保持期間を明示した指示がない限り有効化しないでください。

## うまくいかないとき

| 症状 | 見るところ |
|---|---|
| スタックがファイルシステムの作成で失敗する | サブネットの空き IP、`fsxadmin` パスワードに ONTAP が拒否する文字が入っていないか |
| 管理エンドポイントに届かない | VPC 内から実行しているか。ONTAP の管理面は VPC 限定で、手元の端末からは届きません |
| `mount` がタイムアウトする | セキュリティグループ。NFSv3 は 2049 だけでなく 111 / 635 / 4045-4046 も使います |
| アクセスポイント経由で `AccessDenied` | AWS 側（IAM とアクセスポイントポリシー）と ONTAP 側（ファイルシステム識別情報）の**両方**が許可している必要があります。**どちらから返ったかはエラー本文で切り分けられます。**<br>・修飾のない `Access Denied` **だけ** → **Layer 2**。ファイル権限が足りていません。**ポリシーを探しても原因はありません。** ボリュームルートの所有者と mode bits を見ます<br>・`... with an explicit deny in a resource-based policy` → Layer 1。アクセスポイントポリシーの明示的な拒否に当たっています<br>・`... because no identity-based policy allows the s3:<action> action` → Layer 1。どのポリシーも許可していません（暗黙的な拒否のまま）<br>**3 通りとも同一環境で実測されています**（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#非-root-の-id-固定によるポリシー無しでの書き込み停止)）。ONTAP 側の拒否はアクセスポイントポリシーを付けていない状態でも起きます（[同](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--絞り込みを担うファイルシステム側の権限)） |
| アクセスポイントを追加したら、それだけ `AccessDenied` になる | **VPC エンドポイントポリシーを絞っている環境では、新しいアクセスポイントの ARN が許可対象に入っていません。** 既定は全許可なので、絞っていない環境ではこの層の存在に気づきません（[ネットワークアクセスの設定](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)。AWS のドキュメント記載で、このリポジトリでは実測していません） |
| `HeadBucket` は通るのにデータ操作が失敗する | AD 参加 SVM ならドメインコントローラーへの到達性。`HeadBucket` は偽陽性になります |
| 書いたのに NFS に見えない | マウントオプション。`actimeo=0` のマウントポイントで確認してください |
| FlexCache の作成が `Volumes of this type must be at least 50GB` で失敗する | **Cache ボリュームは 50 GB 未満で作れません。** Origin より小さくはできますが、この下限は別です |
| FlexCache の作成が `Aggregates not matching FabricPool requirements` で失敗する | **`use_tiered_aggregate`（CLI は `-use-tiered-aggregate`）を有効にしてください。** FSx for ONTAP のアグリゲートは FabricPool 有効で、既定は「階層化アグリゲートに Cache を置かない」です |
| Cache ボリュームが `volume delete` で消えない | **FlexCache は専用の削除経路です**（CLI は `volume flexcache delete`、REST は `/storage/flexcache/flexcaches/{uuid}`）。**先に unmount して offline にする必要があります** |
| Cache を消したのに Origin が「まだ Cache がある」と言って消えない | **Cache を解放する前に Origin を offline にすると、Cache 削除時の Origin 側 cleanup が失敗します。** `Origin` に触るのは解放が終わったあとです。復旧は[継承の検証記録](../verification/flexcache-security-style-inheritance.md#この手順で踏んだ罠)にあります |
| スタック削除が `svmLifecycle should be DELETING, but get: MISCONFIGURED` で失敗する | **SVM ピアが残っています。** 解除は ONTAP 側からで、**そのホストを消す前に行ってください**（[削除](#5-削除)） |

**上の 5 行は 2026-09-13 に実際に踏んだものです**（ONTAP 9.18.1P6、両側 FSx for ONTAP）。
エラー文はそのまま検索できる形で載せてあります。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [配布側のデプロイ](onprem-terraform.md) | FlexCache 側 |
| [最初に決めること](../design-first-decisions.md) | Origin を作る前に決める項目 |
| [検証記録](../verification/s3ap-nfs-visibility.md) | 実測値と測定条件 |
| [PoC チェックリスト](../poc-checklist.md) | 確かめる順序 |
| [構成の形](../architecture.md) | 全体像 |

---

<!-- lang-switcher:start -->
🌐 [日本語](aws-cloudformation.md) | [English](../../en/deployment/aws-cloudformation.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
