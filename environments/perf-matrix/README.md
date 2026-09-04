# プロトコル別性能測定の環境

Amazon EFS と Amazon FSx for NetApp ONTAP を同じサブネットの同じクライアントから測るための環境を、
他の人が再現できる形に置く。**測定結果はここには無い。** 手順と、実行前に必要な確認だけを持つ。

- 何を測るかは[測定計画](../../docs/ja/verification/throughput-protocol-matrix-plan.md)
- どの組み合わせがマウントできるかは[プロトコル別の可否](../../docs/ja/verification/protocol-matrix-efs-vs-ontap.md)
- 測る前の考慮点は[性能検証の考慮点](../../docs/ja/reference/performance-testing-guide.md)
- 費用は[検証パターンごとの費用構造](../../docs/ja/reference/comparison/finops-performance-test-patterns.md)

## 先に読む — 費用と、止まらない課金

**この環境は時間あたり約 $60 課金される。** 内訳は次のとおりで、**EC2 は停止すれば止まるが、
ストレージ側は止まらない。**

| リソース | 時間 | 停止で止まるか |
|---|---|---|
| EFS Provisioned 3,072 MiBps | **$30.30** | **止まらない**（削除のみ） |
| FSx for ONTAP 第二世代 6,144 MBps + 200,000 IOPS | **$22.66** | **止まらない**（削除、または指定値の引き下げ） |
| FSx for ONTAP 第一世代 2,048 MBps + 80,000 IOPS | $4.90 | 止まらない（指定値の引き下げ） |
| c5n.9xlarge ×1 | $2.45 | 止まる |
| c5n.2xlarge ×8 | $4.35 | 止まる |

**EFS Elastic を選んだ場合はこの表に載らない。** 予約課金がなく、**読み書きした量に $0.07/GB** で
かかる。測定を短くしても下がらないので、読む総量を先に決める。

**消し忘れるとストレージ側だけで月 $24,090 になる。** 全パターンが終わったら
`./teardown.sh` を実行し、**最後の検証行が「nothing tagged for deletion remains」になることを
確認する。** 削除 API がエラーを返さなかったことは、消えた証拠ではない。

## この環境で測らないもの

**SMB は測らない。** 既存 SVM は `MEAS.FSXN.LOCAL` に参加した記録を持つが、**その記録の DNS
アドレスに ENI が存在せず、アカウントに Managed AD の ENI も 1 つも無い。** ドメイン
コントローラが消えている。SVM の `CREATED` は参加時の設定が残っているだけで、いま参加できる
ことを意味しない。

したがって SMB を測るには先にディレクトリを立てる必要がある。**この環境はそこを含めない。**
ディレクトリを用意したら、Windows クライアントと SMB のケースを同時に追加する。

## 必要なもの

| 項目 | 理由 |
|---|---|
| VPC とサブネット 1 つ | **全ターゲットと全クライアントを同じサブネットに置く。** 別 AZ にすると片側だけに AZ ホップが乗る |
| 既存の第一世代 FSx for ONTAP の ID | A と E で流用する。このディレクトリは作らない（作ると削除もできてしまう） |
| Secrets Manager のシークレット（`password` キー） | 第二世代の `fsxadmin` パスワード。テンプレートのパラメータにしないため |
| VDBENCH と Java | auto_vdbench の前提。VDBENCH は Oracle のサイトでライセンス同意のうえ取得する |
| [auto_vdbench](https://github.com/shuichi-taketani/auto_vdbench) | ファイルプロトコル側の測定器 |

クライアントは鍵ペアを持たず、パブリックアドレスも持たない。**接続は AWS Systems Manager
（Session Manager）で行う。** 共有アカウントに鍵を残さないため。

## 手順

```bash
export AWS_REGION=ap-northeast-1
export VPC_ID=vpc-xxxxxxxxxxxxxxxxx        # 既存の FSx for ONTAP と同じ VPC
export SUBNET_ID=subnet-xxxxxxxxxxxxxxxxx  # 全ターゲットと全クライアントを同じサブネットに
export GEN1_FS_ID=fs-xxxxxxxxxxxxxxxxx     # 既存の第一世代
export FSXADMIN_SECRET_ARN=arn:aws:secretsmanager:...
export NAME_PREFIX=perfmatrix
export VOLUME_SIZE_GIB=900                 # 省略時 900。runbook がバイトへ換算する
```

### 1. クライアントと共有セキュリティグループ

```bash
./runbook.sh clients
```

**先にクライアントを作る。** 各ターゲットの ingress は CIDR ではなくこのセキュリティグループを
参照するので、これが無いとターゲットが作れない。

### 2. 可否の確認と NVMe キャッシュのゲート

```bash
./runbook.sh preflight
```

**ここが最も重要な確認である。** 非対応の組み合わせを一覧し、そのうえで **NVMe リードキャッシュが
無効になっているか**を訊く。有効なまま読み取りを測ると、キャッシュから返る値を測ることになり、
SSD IOPS の設定は結果に効かない。**前回いちばん測り直しが発生した箇所。**

無効化は AWS API ではできない。ONTAP CLI で行う。

```text
system node external-cache show
system node external-cache modify -node * -is-enabled false
system node external-cache show          # 両ノードが false になったことを確認する
```

**`modify` がエラーを返さなかったことではなく、2 回目の `show` で判定する。**

キャッシュを無効化すると、超えるべきはインメモリキャッシュだけになる。2,048 MBps と
6,144 MBps のどちらも 256 GB なので、**一度に 512 GB 以上を読む。**

### 3. ターゲットの作成

```bash
./runbook.sh efs          # 約 $30.30/時 が作成完了時点から始まる
./runbook.sh gen2         # 約 $22.66/時
./runbook.sh raise-gen1   # 既存の第一世代を 2048 MBps へ。確認プロンプトあり
```

**`raise-gen1` は 24 分かかった実測がある。** 測定の合間に上げ下げする運用にはしない。

### 4. 測定

ファイルプロトコル側:

```bash
python3 ../../scripts/protocol_matrix_harness.py \
  --target ontap --host <svm-nfs-dns> --export /<volume-junction> \
  --mount-root /mnt/bench --report-root report/ --summary summary-ontap.json
```

ハーネスは**プロトコルを 1 つずつマウントし、要求値ではなく実効のマウントオプションを記録して**
auto_vdbench を呼ぶ。非対応の組み合わせは理由つきでスキップし、失敗として記録しない。

**EFS はマウント方法を変える。** 素の `mount -t nfs` ではクライアント 1 台あたり 500 MiBps で
止まる。`amazon-efs-utils` 2.0 以降のヘルパーで 1,500 MiBps になる。**どちらを使ったかを記録する。**
ハーネスは素のマウントを使うので、EFS のヘルパー経路は別に測って両方を残す。

S3 API 側（A-1）は別の測定器を使う。

```bash
python3 ../../scripts/measure_s3_throughput.py --help
```

**auto_vdbench は S3 API のワークロードを生成しない。** VDBENCH はマウントパスに対して動く。
2 つの結果を同じ表に並べるときは、測定器が違うことを表に書く。

### 5. 台数を増やす試験

クライアントは 8 台すべて作られる。**1 / 2 / 4 / 6 / 8 台の測定は、起動する台数を変えて行う。**
同じホストが各段に参加するので、段ごとに別の集合を測ることにならない。

```bash
aws ec2 start-instances --instance-ids <ladder-1>            # 1 台
aws ec2 start-instances --instance-ids <ladder-2>            # 2 台
# ...
```

### 6. 費用の確認

```bash
./runbook.sh costs
```

**フェーズの合間に実行する。** いま何が課金されているかを一覧する。「止めたつもりだった」を
防ぐため。

### 7. 削除

```bash
./teardown.sh
```

高い順に削除し、**最後に状態を読み直して検証する。** 削除タグの付いたものが残っていれば
非ゼロで終了する。第一世代は削除せず 128 MBps に戻す（他の測定が載っているため）。

## 記録に添える項目

**どれか 1 つ欠けると再現できない。** 一覧は
[性能検証の考慮点](../../docs/ja/reference/performance-testing-guide.md#記録に必ず添える項目)にある。
この環境に固有のものは次の 3 つ。

- **EFS のスループットモードと、マウントに使ったクライアント**（素の `mount` かヘルパーか）
- **NVMe リードキャッシュの状態**と、読んだ量とインメモリキャッシュ量の比
- **世代**（第一世代か第二世代か）と、指定したスループットキャパシティ

## テンプレートが意図的にやらないこと

- **VPC・サブネット・既存ファイルシステムを作らない。** すべて渡す。既存を再利用することが
  比較の前提で、サブネットを増やすと片側だけに AZ ホップが乗る。
- **不可逆な保持機能を一切有効にしない。** SnapLock、保持期間、Object Lock、特権削除の無効化は
  どれも入っていない。**この環境は削除される前提で存在する。**
- **バックアップを取らない。** 中身は `/dev/urandom` から生成したテストデータで、その複製に
  課金する意味がない。
- **クライアントに鍵ペアを与えない。** Session Manager で入る。
