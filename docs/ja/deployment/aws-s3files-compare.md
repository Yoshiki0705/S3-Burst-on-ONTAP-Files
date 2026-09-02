# S3 Files 検証環境セットアップ

**この手順は 2026-09-01 に実機で通しました。** 通したのは CLI での同等手順で、
[`environments/s3files-compare/`](../../../environments/s3files-compare/) の CloudFormation
テンプレート自体はまだデプロイしていません。実機で判明した差分は下記「実機で追加が必要だったもの」
に反映済みです。実測値と落とし穴は[実測記録](../verification/s3files-measured.md)にあります。

## 実機で追加が必要だったもの

テンプレートを書いた時点では想定していなかったもので、これが無いと計測に入れません。

| # | 追加が必要なもの | 理由 |
|---|---|---|
| 1 | **アクセスポイント**（POSIX uid/gid + root ディレクトリ） | スコープを絞った IAM（`ClientMount` + `ClientWrite`）だけでは、マウントルートで root の `mkdir` すら拒否されます。`ClientRootAccess` を足すか、アクセスポイントで POSIX ユーザーにマップするかの二択で、後者が公式の推奨です |
| 2 | **計測ホストに Python 3.12** | Amazon Linux 2023 の既定 `python3` は 3.9 で、このリポジトリのスクリプト（`datetime.UTC`）は動きません。`dnf install python3.12` を使います |
| 3 | **botocore は `dnf install python3-botocore`** | `pip3 install` は失敗します。無くてもマウントは成功しますが、`mount.log` に `Failed to import botocore` が記録され CloudWatch メトリクスが使えません |
| 4 | **計測スクリプトの `--key-prefix`** | アクセスポイントの root ディレクトリの分だけ S3 キーとマウントパスがずれます。渡さないと全方向がタイムアウトします |

アクセスポイントの作成例。`rootDirectory` を指定すると、そのパスがマウントルートになります。

```bash
aws s3files create-access-point --region ap-northeast-1 \
  --file-system-id fs-0123456789abcdef0 \
  --posix-user "uid=1000,gid=1000" \
  --root-directory "path=/measure,creationPermissions={ownerUid=1000,ownerGid=1000,permissions=0755}"
```

## この環境の目的

Amazon S3 Files をこのリポジトリの構成と**同じホスト・同じクロック**で測るための環境です。
比較したいのは同じ要求（S3 API で集め、ファイルプロトコルで読む）に対する 2 つの設計であり、
そのためには測定条件を揃える必要があります。揃えられるものと揃えられないものがあり、
後者は[この節](#計測手法を揃えるうえでの限界)にまとめてあります。

数値は[比較検証](../verification/s3files-vs-flexcache.md)側にあります。
**実測前なので表は空です。**

## 前提条件

S3 Files 側の前提は AWS のドキュメントに記載があるものです。省略すると作成か
マウントのどちらかで失敗します。

| 項目 | 要件 | 出典 |
|---|---|---|
| バケット種別 | 汎用バケット | [Prerequisites for S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-prereq-policies.html) |
| バージョニング | **有効が必須。** 同期にバージョン指定の API 操作を使う | 同上 |
| 暗号化 | SSE-S3 または SSE-KMS のいずれか | 同上 |
| クライアント | `amazon-efs-utils` 3.0.0 以降と botocore | 同上 |
| IAM ロール | 2 つ。サービスがバケットを読み書きするもの、コンピュートがマウントするもの | 同上 |
| セキュリティグループ | マウントターゲットに TCP 2049 のインバウンド、EC2 に同ポートのアウトバウンド | 同上 |
| リージョン | GA 時点で 34 リージョン。ap-northeast-1 で**実際に作成・マウント・削除まで確認**（2026-09-01） | [What's New](https://aws.amazon.com/about-aws/whats-new/2026/04/amazon-s3-files/) |

テンプレートはこのうちバケット・バージョニング・暗号化・同期ロール・
セキュリティグループを作ります。**クライアントの導入と、検証ホストのロールへの権限追加は
テンプレートの外です。** 後者は別スタックが所有する IAM ロールの変更なので、
テンプレートに隠さず出力として提示しています。

## 既存環境から引き継ぐパラメータ

[収集側のスタック](aws-cloudformation.md)が作った環境をそのまま使います。
新しく作るのはファイルシステムとマウントターゲットだけです。

| 引き継ぐもの | 値の出どころ | 揃える理由 |
|---|---|---|
| リージョン | ap-northeast-1 | 既存計測と同一（[検証記録](../verification/s3ap-nfs-visibility.md)） |
| VPC | 収集側スタックの `VpcId` | ファイルシステムに紐づく VPC は 1 つだけ |
| サブネット | 収集側スタックの `SubnetId` | マウントターゲットはアベイラビリティーゾーンごとに 1 つで、クライアントは自分のゾーンのものを使う。ゾーンをまたぐと片側だけがホップを 1 つ多く払う |
| セキュリティグループ | 収集側スタックの `HostSecurityGroup` | マウントターゲットのインバウンドの送信元にする。アドレスをどこにも書かずに済む |
| 計測ホスト | 収集側スタックの `VerificationHost`（既定 `t3.small`） | **同一インスタンス。** 2 台に分けるとクロックの比較になる |

## 再現用スクリプト

実機で通した CLI 手順を、冪等にして [`runbook.sh`](../../../environments/s3files-compare/runbook.sh)
に置いてあります。CloudFormation テンプレートは同じものを宣言的に作りますが、**まだデプロイして
いません。**根拠があるのはこちらです。

```bash
VPC_ID=vpc-0123456789abcdef0 SUBNET_ID=subnet-0123456789abcdef0 \
  environments/s3files-compare/runbook.sh create
environments/s3files-compare/runbook.sh measure   # ホストで流すコマンドを表示
environments/s3files-compare/runbook.sh metrics   # CloudWatch の課金バイトと同期遅延
environments/s3files-compare/runbook.sh destroy   # 破棄し、残存 0 件を件数で確認
```

`destroy` は削除 API の戻り値ではなく**一覧 API の件数**で判定します。

## デプロイの順序

埋めるパラメータは 3 つで、**出どころが 2 種類あります。** VPC とサブネットは収集側スタックの
**パラメータ**（出力ではありません）で、セキュリティグループは**リソース**です。
出力を探しても 3 つとも見つかりません。

```bash
STACK=<収集側スタック名>

# 1a. VPC とサブネットは、収集側スタックに渡した「パラメータ」から読む
aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Parameters[?ParameterKey==`VpcId` || ParameterKey==`SubnetId`]' \
  --output table

# 1b. 検証ホストのセキュリティグループは、論理 ID から物理 ID を引く
aws cloudformation describe-stack-resource --stack-name "$STACK" \
  --logical-resource-id HostSecurityGroup \
  --query 'StackResourceDetail.PhysicalResourceId' --output text

# 2. params.example.json をコピーして 3 つを埋める
cp environments/s3files-compare/params.example.json /tmp/params.json

# 3. デプロイ
aws cloudformation create-stack \
  --stack-name s3burst-s3files-compare \
  --template-body file://environments/s3files-compare/template.yaml \
  --parameters file:///tmp/params.json \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

デプロイ後の手順は 3 つあり、順番に意味があります。

1. **検証ホストのロールに権限を足す。** スタックの `HostPolicyToAttach` 出力が必要な 2 つを
   示します。マウント用のマネージドポリシーと、バケットのオブジェクトを直接読むための
   インラインポリシーです。前者がないとマウントが失敗し、**後者がないとマウントは成功した
   まま、1 MiB 以上の読み取りがバケットから直接ストリームされる経路を失います**
   （4 番目の計測方向がまさにその経路の話なので、黙って測ると別のものを測ります）。
2. **マウントターゲットが `available` になるまで待つ。** スタックが `CREATE_COMPLETE` に
   なったことは別の合図です。到達可能になる前のマウントは、セキュリティグループの問題に
   見える形で失敗します。確認コマンドは `HowToReadTheMountTargetState` 出力にあります。
3. **マウントする。** 次節。

## マウント

```bash
FILE_SYSTEM_ID=<スタックの FileSystemId 出力> \
  bash environments/s3files-compare/mount-s3files.sh
```

スクリプトはクライアントの導入、マウントターゲットの状態表示、マウント、そして
**実際に効いたマウントオプションの表示**を行います。最後のものが要点です。
要求したオプションが効いたことの証拠は、要求そのものではありません。

S3 Files はマウントヘルパー経由で、ファイルシステム種別 `s3files` としてマウントします。
ヘルパーが付けるオプションは次のとおりで、`tls` と `iam` は無効化できません。

| オプション | 値 | 意味 |
|---|---|---|
| `nfsvers` | 4.2 | NFS のバージョン。4.1 も対応 |
| `rsize` / `wsize` | 1048576 | 1 回の READ / WRITE の最大バイト数 |
| `hard` | — | サーバが応答するまで再試行を続ける |
| `timeo` | 600 | 再試行前の待ち時間（デシ秒）。60 秒 |
| `retrans` | 2 | 再試行回数 |
| `noresvport` | — | 再接続時に非特権ポートを使う |
| `tls` / `iam` | — | 常に付き、無効化できない |

出典: [Mounting S3 file systems on Amazon EC2](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html)

## 計測手法を揃えるうえでの限界

**マウントオプションは揃いません。** 既存計測は NFSv3 に `actimeo=0` を付けたものです
（[検証記録](../verification/s3ap-nfs-visibility.md)）。S3 Files は NFSv4.1 と 4.2 だけに
対応し、ヘルパーは 4.2 を既定にします。プロトコルのバージョンが違うので、
両者を「同一条件」と書くことはできません。

`actimeo=0` がこのヘルパーで効くかは**未確認**です。計測の意図としてはクライアント側の
属性キャッシュを外したいので渡しますが、効かなかった場合の数値はサービスの反映時間ではなく
クライアントのキャッシュ期限を含みます。だからスクリプトは `findmnt` の出力を記録し、
JSON の `mount_options_effective` に残します。

**揃うのは方法です。** 同一ホスト、同一クロック、30 回、64 B、並列度 1、
boto3 の持続セッション、パーセンタイルの計算方法（最近接順位、補間なし）。
これは[計測スクリプト](../../../scripts/measure_s3files_visibility.py)が
`measure_visibility.py` から `percentiles()` を読み込むことで担保しています。

| 揃うもの | 揃わないもの |
|---|---|
| ホストとクロック、リージョン、サブネット | NFS のバージョン（3 対 4.2） |
| 反復回数、オブジェクトサイズ、並列度 | `tls` と `iam`（S3 Files では常時） |
| パーセンタイルの算出方法 | 属性キャッシュの扱い（`actimeo=0` の可否が未確認） |
| S3 クライアント（boto3 の持続セッション） | ストレージの実体（ONTAP ボリューム 対 S3 バケット + 高性能ストレージ） |

## 破棄の順序

**バージョニングが破棄の順序を決めます。** これは S3 Files の前提条件なので外せません。
計測が書いたオブジェクトにはバージョンの連鎖があり、削除したものには削除マーカーが残ります。
`aws s3 rm --recursive` は現行バージョンだけを消すので、バケットは空になりません。
CloudFormation は空でないバケットを削除できないため、`delete-stack` は数分動いたあと
**ファイルシステムを消し終えた状態で最後のリソースで失敗します。**

```bash
STACK_NAME=s3burst-s3files-compare bash environments/s3files-compare/teardown.sh
```

スクリプトはアンマウント、バージョンと削除マーカーの削除、スタックの削除、
そして削除されたことの確認を順に行います。最後が独立した手順である理由は、
`delete-stack` の戻り値が「要求が受け付けられた」を意味するだけだからです。

この環境には不可逆な機能を一切入れていません。S3 Object Lock、オブジェクトの保持設定、
Vault Lock はどこにもないので、すべてのオブジェクトとバージョンは要求すれば消えます。
バージョニングは不可逆性ではありません。

検証ホストのロールに手で足したポリシーは、スクリプトが消さずに提示します。
別スタックが所有するロールの変更なので、意図したキーストロークであるべきです。

## この環境が測らないこと

| 問い | 測らない理由 |
|---|---|
| スループット | 並列度 1 での可視性を測る構成。集約スループットの測定ではない |
| 大量の小ファイル | 逐次 1 件ずつ。同期の毎秒処理件数の上限には遠く及ばない |
| SMB | S3 Files は NFSv4.1 と 4.2 のみ。SMB を提供しない |
| ロックの挙動 | S3 Files のロックは advisory のみで、mandatory locking は非対応 |
| アーカイブ系ストレージクラス | Glacier 系と Intelligent-Tiering のアーカイブ層はファイルシステムから読めない |
| 費用 | [FinOps の費用構造](../reference/comparison/finops-s3-vs-s3ap.md)側の問い。ここでは測らない |

## 出典

| ドキュメント | 参照した内容 |
|---|---|
| [Working with Amazon S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html) | 構成、高性能ストレージ、128 KiB と 1 MiB の境界、NFS 4.1 / 4.2 |
| [Prerequisites for S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-prereq-policies.html) | バージョニング必須、暗号化、IAM ロール 2 つ、TCP 2049 |
| [Mounting S3 file systems on Amazon EC2](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html) | マウントヘルパー、既定オプション、`tls` と `iam` |
| [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) | 同期の方向ごとの所要と上限、初回アクセスの遅さ |
| [Unsupported features, limits, and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) | 非対応 NFS 機能、クォータ、アーカイブ層 |
| [What's New](https://aws.amazon.com/about-aws/whats-new/2026/04/amazon-s3-files/) | GA 日と 34 リージョン |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [S3 Files 実測記録](../verification/s3files-measured.md) | この環境で出した実測値と落とし穴 |
| [S3 Files と本構成の比較検証](../verification/s3files-vs-flexcache.md) | 同一手法で並べる比較表 |
| [収集側のデプロイ](aws-cloudformation.md) | この環境が引き継ぐパラメータの出どころ |
| [代替案との比較](../reference/comparison/alternatives.md) | S3 Files の代償を含む選択肢の整理 |
| [FinOps の費用構造](../reference/comparison/finops-s3-vs-s3ap.md) | 費用面での比較 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
