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

> **セキュリティに関する補足**: `NTFS` を選ぶ場合、SVM に CIFS サーバーが必要です。
> **このテンプレートは CIFS サーバーの作成も Active Directory 参加も行いません。**
> AD 参加は必須ではなく、ドメインが利用できない場合は workgroup モードで構成できます
> （[公式手順](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html)。NTLM のみで Kerberos は非対応）。
> **AD 参加を選んだ場合**は、S3 Access Point 経由の**すべてのデータ操作**にドメインコントローラーへの
> 到達性が必要です。`HeadBucket` は AD が到達不能でも成功するため、疎通確認には使えません。
> 確認は必ずデータ操作で行ってください。

## 2. スタックの作成

```bash
cd environments/aws-origin
cp params.example.json params.json    # params.json は追跡されません
# VpcId と SubnetId を自分の値に変更する

aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name s3burst-origin \
  --parameter-overrides file://params.json \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

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
> `AWS::FSx::FileSystem` はバージョンを属性として公開していません。FSx の API も当てになりません
> （既存のファイルシステムでは `DescribeFileSystems` が `FileSystemTypeVersion` を返しませんでした）。
> 確実な取得元は ONTAP 自身です。このスタックが資格情報と 443 番ポートを用意しているのは
> そのためでもあります。

## 3. S3 Access Point の作成

CloudFormation には FSx for ONTAP のボリュームへ S3 Access Point を接続するリソースが
ありません。CLI で作成します。

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
| `FileSystemIdentity` | アクセスポイント経由の**全リクエストがこの 1 つの識別情報で認可されます**。呼び出し元ごとの区別は付きません。**絞り込みは 2 か所にあります。** AWS 側はアクセスポイントポリシーの明示的な拒否（`Allow` を狭くすることは絞り込みになりません）、ファイルシステム側はこの識別情報が持つファイル権限（mode bits / ACL）です。**確実に書けなくしたいなら、書き込み権限を持たない識別情報を指定してください。** 作成後に変更できないので、用途ごとにアクセスポイントを分けます（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--ファイルシステム側の権限が絞り込みを担う)） |
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
| アクセスポイント経由で `AccessDenied` | AWS 側（IAM とアクセスポイントポリシー）と ONTAP 側（ファイルシステム識別情報）の**両方**が許可している必要があります。**どちらから返ったかは切り分けられます。** AWS 側の拒否はエラー本文に `with an explicit deny in a resource-based policy` が入ります。ONTAP 側の拒否はアクセスポイントポリシーを付けていない状態でも起きるので、ボリュームルートの所有者と mode bits を確認します（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--ファイルシステム側の権限が絞り込みを担う)） |
| アクセスポイントを追加したら、それだけ `AccessDenied` になる | **VPC エンドポイントポリシーを絞っている環境では、新しいアクセスポイントの ARN が許可対象に入っていません。** 既定は全許可なので、絞っていない環境ではこの層の存在に気づきません（[ネットワークアクセスの設定](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)。AWS のドキュメント記載で、このリポジトリでは実測していません） |
| `HeadBucket` は通るのにデータ操作が失敗する | AD 参加 SVM ならドメインコントローラーへの到達性。`HeadBucket` は偽陽性になります |
| 書いたのに NFS に見えない | マウントオプション。`actimeo=0` のマウントポイントで確認してください |

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
