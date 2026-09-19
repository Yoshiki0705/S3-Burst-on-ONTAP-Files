# 最初の 1 時間（最小構成で、S3 で書いたものがファイルから見えることを確かめる）
<!-- lang-switcher:start -->
🌐 [日本語](quickstart.md) | [English](../en/quickstart.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
この構成を**いちばん小さい形で 1 回通す**ためのページです。判断は求めません。
パラメータは 2 つだけ埋め、6 コマンドを順に実行し、最後に消します。

**性能はここでは測りません。** 既定のままの構成で測った数値は、測ったつもりのものとは
別のものになります（理由は最後の節）。

## このページで作るもの

| 項目 | 値 |
|---|---|
| 作るもの | FSx for ONTAP 1 台（128 MBps・SSD 1,024 GiB）、SVM、Origin ボリューム 10 GiB、検証ホスト 1 台（t3.small） |
| 確かめること | **S3 API で書いたオブジェクトが、同じボリュームを NFS でマウントしたホストからファイルとして読めること** |
| 所要時間 | 作成 25〜35 分、確認 10 分、撤去 40〜60 分 |
| 費用 | **約 $0.4/時**（ap-northeast-1 のリスト価格から計算、2026-09-04 取得。内訳は[検証パターンごとの費用構造](reference/comparison/finops-performance-test-patterns.md)） |
| 作らないもの | FlexCache、配布側、AD、SMB、性能測定用のクライアント |

**この 1 回で確かめられるのは意味論だけです。** 「書いたものが見える」ことと
「どれくらいの速さで読める」ことは別の検証で、後者は環境も費用も桁が変わります。

## 前提

- VPC 1 つとサブネット 1 つ。**ファイルシステムと検証ホストは同じサブネットに置きます**
- 認証済みの `aws` CLI と、Python 3.12 以降
- サブネットから Session Manager に到達できること。**到達できないと、ホストは正常に起動して
  Session Manager に現れません**（次の手順がそれを見ます）

**鍵は使いません。** 検証ホストには受信ルールがなく、Session Manager で入ります。

## 1. 前提の確認

```bash
git clone https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files
cd S3-Burst-on-ONTAP-Files
make preflight-pre VPC=vpc-xxxxxxxx SUBNET=subnet-xxxxxxxx MBPS=128
```

**ここで止まるものは、あとで止まると高くつくものです。**

| 読むもの | 通らないと |
|---|---|
| リージョン合計のスループットキャパシティ（既定 10,240 MB/s。**他の人のファイルシステムも同じ枠**） | 作成が失敗する。**25 分待ってから分かります** |
| サブネットが指定 VPC にあること、空き IP | 作成が失敗する |
| Session Manager への到達性 | ホストは起動して Session Manager に現れない。**原因が出ないまま 20 分失います** |

`preflight: nothing blocking` が出たら次へ進みます。

## 2. スタックの作成

**パラメータは 21 個ありますが、埋めるのは 2 個だけです。** 残りは既定のままで動きます。

```bash
aws cloudformation create-stack \
  --stack-name s3burst-quickstart --region ap-northeast-1 \
  --template-body file://environments/aws-origin/template.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-xxxxxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-xxxxxxxx

aws cloudformation wait stack-create-complete \
  --stack-name s3burst-quickstart --region ap-northeast-1
```

**`OriginVolumeSecurityStyle` の既定は `UNIX` で、NFS 向きです。**
SMB で配布する予定なら `NTFS` を指定してください。**あとから変えると配布側を作り直します**
（[最初に決めること](design-first-decisions.md)）。ここでは既定の UNIX で進みます。

出力から 3 つ控えます。

```bash
aws cloudformation describe-stacks --stack-name s3burst-quickstart \
  --region ap-northeast-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`OriginVolumeId`||OutputKey==`StorageVirtualMachineId`||OutputKey==`VerificationHostId`].[OutputKey,OutputValue]' \
  --output text
```

## 3. S3 Access Point の作成

**先に識別情報のユーザを作ります。** アクセスポイントは `FileSystemIdentity` に指定した
**UNIX ユーザ名で全リクエストを認可します**。新しい SVM には `root` / `pcuser` / `nobody` しか
いないので、**書き込み用のユーザは自分で作り、ボリュームルートの所有者にします。**

ONTAP 側の 2 コマンドです（管理エンドポイントは VPC 内なので、検証ホストから実行します）。

```bash
# 検証ホストの中で。PW は fsxadmin のパスワード（出力の OntapAdminSecretArn から取る）
H=https://management.<FileSystemId>.fsx.ap-northeast-1.amazonaws.com/api
curl -s -k -u "fsxadmin:$PW" -X POST -H 'Content-Type: application/json' \
  -d '{"svm":{"name":"origin_svm"},"name":"s3ap","id":1001}' "$H/name-services/unix-groups"
curl -s -k -u "fsxadmin:$PW" -X POST -H 'Content-Type: application/json' \
  -d '{"svm":{"name":"origin_svm"},"name":"s3ap-writer","id":1001,"primary_gid":1001}' \
  "$H/name-services/unix-users"
```

**そのユーザにボリュームルートを持たせます。** 手順 4 でマウントしてから実行してもよいですが、
**アクセスポイント作成前に済ませるほうが順番として素直です**（作成後に権限を直しても、
書けなかった理由を切り分ける手間が増えるだけです）。

```bash
sudo chown 1001:1001 /mnt/origin-noac     # マウントは手順 4 と同じ
```

> **非 root であること自体は制御になりません。** 効くのは**その識別情報がボリュームルートに対して
> 持つ実効権限**です。ここでは書き込みたいので所有者にしています。**読み取り専用にしたいなら、
> 逆にボリュームが書き込みを与えていない識別情報を選びます**（`755` で所有者でもグループでもない、
> など）。判断材料は[収集側のデプロイ](deployment/aws-cloudformation.md#3-s3-access-point-の作成)にあります。

```bash
cd environments/aws-origin
cp access-point.example.json access-point.json
# VolumeId と VpcId を上の出力の値に置き換え、"_comment" で始まるキーを削除する
aws fsx create-and-attach-s3-access-point \
  --region ap-northeast-1 --cli-input-json file://access-point.json
cd ../..
```

**JSON ファイルで渡します。** `--ontap-configuration` を位置引数で書く形は解析が壊れやすく、
そのときのエラーは引用符の問題を指してくれません。

> **`"Type": "ONTAP"` が必須です。** 例ファイルにはこれが入っていなかったので、
> **2026-09-19 にこの手順を初めて通したときに `Missing required parameter in input: "Type"` で
> 止まりました。** 例ファイルは修正済みですが、自分で組み立てる場合は忘れやすい場所です。

**アクセスポイント経由の全リクエストは 1 つの識別情報で認可されます。** 呼び出し元ごとの区別は
付きません。ここでは既定で進めますが、**読み取り専用にしたい場合は AWS 側のポリシーと
ファイルシステム側の権限の 2 層を同時に決めます**（[収集側のデプロイ](deployment/aws-cloudformation.md#3-s3-access-point-の作成)）。

## 4. 書き込みとファイルからの読み取り

```bash
aws ssm start-session --target <VerificationHostId> --region ap-northeast-1
```

ホストの中で、SVM の NFS エンドポイントを取得してマウントします。

**マウント先は DNS 名で指定します。** 形は
`<StorageVirtualMachineId>.<FileSystemId>.fsx.<region>.amazonaws.com` です。

```bash
SVM_DNS=<StorageVirtualMachineId>.<FileSystemId>.fsx.ap-northeast-1.amazonaws.com
sudo mount -t nfs -o nfsvers=3,actimeo=0 "$SVM_DNS":/origin_vol /mnt/origin-noac
```

> **ホストから `aws fsx describe-...` を呼ばないでください。** このサブネットには Session Manager
> の VPC エンドポイントしか無いので、**`fsx.<region>.amazonaws.com` 宛ては接続タイムアウトになります**
> （`Connect timeout on endpoint URL: "https://fsx.ap-northeast-1.amazonaws.com/"`）。
> **2026-09-19 にこのページの手順を実際に通して踏みました。** IP を引く必要があるなら
> 手元（API に到達できる側）で引いてください。**DNS 名なら API を呼ばずに解決できます。**

**`actimeo=0` を付ける理由があります。** Linux の既定はディレクトリ一覧を最大 60 秒
キャッシュするので、**ストレージ側と無関係に、新しいファイルが最大 1 分見えません。**
鮮度を確かめたいときは付けてください（実測では削除の反映が 7 ms 対 2 秒以上）。

書いて、ファイルとして読みます。

```bash
AP=arn:aws:s3:ap-northeast-1:<account-id>:accesspoint/<access-point-name>
echo hello > /tmp/check.txt
aws s3api put-object --bucket "$AP" --key check.txt --body /tmp/check.txt
cat /mnt/origin-noac/check.txt
aws s3api delete-object --bucket "$AP" --key check.txt
```

> **`--body` に標準入力を渡せません。** `--body /dev/stdin` は
> `Invalid length for parameter Body, value: 0` ではなく
> **`Blob values must be a path to a file`** で落ちます。**先にファイルへ書いてから渡してください**
> （上の `/tmp/check.txt` はそのためにあります）。**2026-09-19 にこの手順を初めて通したときに
> 踏みました。** パイプでつなぎたくなる場所なので、1 行増えるのは意図した形です。

**`hello` が返れば、この構成の中心にある主張を自分の環境で 1 回確かめたことになります。**
実測した所要時間と、そこから言えること・言えないことは
[S3 Access Point と NFS の可視性](verification/s3ap-nfs-visibility.md)にあります。

## 5. 撤去

**課金が止まるのは削除が終わったときで、削除を始めたときではありません。**

```bash
aws fsx detach-and-delete-s3-access-point --region ap-northeast-1 --name <access-point-name>

# **消えるまで待ちます。** 上のコマンドは即座に戻り、何も出力しません。
while aws fsx describe-s3-access-point-attachments --region ap-northeast-1 \
        --names <access-point-name> >/dev/null 2>&1; do sleep 15; done

aws cloudformation delete-stack --stack-name s3burst-quickstart --region ap-northeast-1
aws cloudformation wait stack-delete-complete --stack-name s3burst-quickstart --region ap-northeast-1
make sweep
```

> **待たずに次へ進むとスタック削除が失敗します。** `detach-and-delete-s3-access-point` は
> **戻り値を持たず、非同期です。** 直後にスタックを消すと、ボリュームの削除が
> `Cannot delete volume while it has one or multiple S3 access points: [<name>]` で止まり、
> スタックは `DELETE_FAILED` になります（**2026-09-19 に、このページの手順どおりに実行して
> 踏みました**。3 秒後でした）。
>
> **完了の判定は `describe-s3-access-point-attachments` が
> `S3AccessPointAttachmentNotFound` を返すことです。** detach コマンド自身の出力は空で、
> 成功も失敗も示しません。**そのあとスタック削除を再実行すれば通ります**（状態は壊れません）。

**`make sweep` を飛ばさないでください。** スタックを消しても止まらないものが 4 種類あります。
とくに**最終バックアップはタグを持たず、ファイルシステム ID も空**なので、タグで探す掃除では
1 件も見つかりません。消してよいと確認できたら `make sweep DELETE=1` です。

## ここで止める理由

**このままの構成で性能を測ると、測ったつもりのものとは別のものが出ます。** 下の既定値が測定を
無効にし、**どれも数値を不自然に見せません。**

| 既定値 | そのままだと |
|---|---|
| NFS マウントの TCP 接続が 1 本 | 約 590 MB/s で頭打ち。`nconnect` を付けると同じ測定が 4.95 倍になりました |
| `dd if=/dev/zero` のペイロード | ゼロブロックはストレージに行かないので、経路を測っていない |
| ボリュームのインライン効率化 | 圧縮がペイロードを吸収し、購入した上限を超えた値が返る |
| `DiskIopsConfiguration` が `AUTOMATIC` | SSD IOPS が先に上限になる |
| リードキャッシュを少しだけ超える読み取り | ディスク経路を測るつもりの読みがキャッシュから返る |
| SMB Multichannel が無効 | 1 MiB 逐次で 574 MB/s に張り付く。4 チャネルなら 3.88 倍 |
| **`tcp-max-xfer-size` が 64 KiB** | `rsize=1048576` を要求したマウントが成功したまま 64 KiB になる。上げると同じ測定が +21% |
| **クライアント 1 台・低い多重度で測る** | **その設定の値が出るだけで、上限ではありません。** 転送サイズと多重度を直すと 1,195 → 1,646 MB/s になった実測があります |

**測る前に読むものは 2 つです。** 数値と条件は[測る前に読む性能の期待値](performance-expectations.md)、
環境の作り方と合格条件は[再現の手引き](verification/reproduction-guide.md)にあります。
**自分で測らずに設計を進められるなら、そのほうが速くて安いです。**

## 次に読むもの

| 次の関心 | ドキュメント |
|---|---|
| この構成が解くこと・解かないこと | [構成の形](architecture.md) |
| いまの構成が当てはまるか | [いまの構成から選ぶ](reference/decision-trees/from-your-current-setup.md) |
| パラメータを自分の環境に合わせる | [パラメータの選び方](deployment/choosing-parameters.md) |
| 配布側（FlexCache）まで作る | [収集側のデプロイ](deployment/aws-cloudformation.md) → [配布側のデプロイ](deployment/onprem-terraform.md) |
| 性能の期待値 | [測る前に読む性能の期待値](performance-expectations.md) |
| 測った記録を一覧する | [測定記録の索引](verification/README.md) |
| 本番に持っていくときの差分 | [検証環境と本番の差分](from-verification-to-production.md) |

---

<!-- lang-switcher:start -->
🌐 [日本語](quickstart.md) | [English](../en/quickstart.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
