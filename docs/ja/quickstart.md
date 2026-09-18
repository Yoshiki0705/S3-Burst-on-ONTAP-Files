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

**アクセスポイント経由の全リクエストは 1 つの識別情報で認可されます。** 呼び出し元ごとの区別は
付きません。ここでは既定で進めますが、**読み取り専用にしたい場合は AWS 側のポリシーと
ファイルシステム側の権限の 2 層を同時に決めます**（[収集側のデプロイ](deployment/aws-cloudformation.md#3-s3-access-point-の作成)）。

## 4. 書き込みとファイルからの読み取り

```bash
aws ssm start-session --target <VerificationHostId> --region ap-northeast-1
```

ホストの中で、SVM の NFS エンドポイントを取得してマウントします。

```bash
NFS_IP=$(aws fsx describe-storage-virtual-machines --region ap-northeast-1 \
  --storage-virtual-machine-ids <StorageVirtualMachineId> \
  --query 'StorageVirtualMachines[0].Endpoints.Nfs.IpAddresses[0]' --output text)
sudo mount -t nfs -o nfsvers=3,actimeo=0 "$NFS_IP":/origin_vol /mnt/origin-noac
```

**`actimeo=0` を付ける理由があります。** Linux の既定はディレクトリ一覧を最大 60 秒
キャッシュするので、**ストレージ側と無関係に、新しいファイルが最大 1 分見えません。**
鮮度を確かめたいときは付けてください（実測では削除の反映が 7 ms 対 2 秒以上）。

書いて、ファイルとして読みます。

```bash
AP=arn:aws:s3:ap-northeast-1:<account-id>:accesspoint/<access-point-name>
echo hello | aws s3api put-object --bucket "$AP" --key check.txt --body /dev/stdin
cat /mnt/origin-noac/check.txt
aws s3api delete-object --bucket "$AP" --key check.txt
```

**`hello` が返れば、この構成の中心にある主張を自分の環境で 1 回確かめたことになります。**
実測した所要時間と、そこから言えること・言えないことは
[S3 Access Point と NFS の可視性](verification/s3ap-nfs-visibility.md)にあります。

## 5. 撤去

**課金が止まるのは削除が終わったときで、削除を始めたときではありません。**

```bash
aws fsx detach-and-delete-s3-access-point --region ap-northeast-1 --name <access-point-name>
aws cloudformation delete-stack --stack-name s3burst-quickstart --region ap-northeast-1
aws cloudformation wait stack-delete-complete --stack-name s3burst-quickstart --region ap-northeast-1
make sweep
```

**`make sweep` を飛ばさないでください。** スタックを消しても止まらないものが 4 種類あります。
とくに**最終バックアップはタグを持たず、ファイルシステム ID も空**なので、タグで探す掃除では
1 件も見つかりません。消してよいと確認できたら `make sweep DELETE=1` です。

## ここで止める理由

**このままの構成で性能を測ると、測ったつもりのものとは別のものが出ます。** 既定値のうち
6 つが測定を無効にし、**どれも数値を不自然に見せません。**

| 既定値 | そのままだと |
|---|---|
| NFS マウントの TCP 接続が 1 本 | 約 590 MB/s で頭打ち。`nconnect` を付けると同じ測定が 4.95 倍になりました |
| `dd if=/dev/zero` のペイロード | ゼロブロックはストレージに行かないので、経路を測っていない |
| ボリュームのインライン効率化 | 圧縮がペイロードを吸収し、購入した上限を超えた値が返る |
| `DiskIopsConfiguration` が `AUTOMATIC` | SSD IOPS が先に上限になる |
| リードキャッシュを少しだけ超える読み取り | ディスク経路を測るつもりの読みがキャッシュから返る |
| SMB Multichannel が無効 | 1 MiB 逐次で 574 MB/s に張り付く。4 チャネルなら 3.88 倍 |

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
| 本番に持っていくときの差分 | [検証環境と本番の差分](from-verification-to-production.md) |

---

<!-- lang-switcher:start -->
🌐 [日本語](quickstart.md) | [English](../en/quickstart.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
