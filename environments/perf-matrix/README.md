# プロトコル別性能測定の環境

Amazon EFS と Amazon FSx for NetApp ONTAP を同じサブネットの同じクライアントから測るための環境を、
他の人が再現できる形に置く。**測定結果はここには無い。** 手順と、実行前に必要な確認だけを持つ。

- 何を測るかは[測定計画](../../docs/ja/verification/throughput-protocol-matrix-plan.md)
- どの組み合わせがマウントできるかは[プロトコル別の可否](../../docs/ja/verification/protocol-matrix-efs-vs-ontap.md)
- 測る前の考慮点は[性能検証の考慮点](../../docs/ja/reference/performance-testing-guide.md)
- 費用は[検証パターンごとの費用構造](../../docs/ja/reference/comparison/finops-performance-test-patterns.md)

## 先に読む — 費用と、止まらない課金

**通常の状態で時間あたり約 $37、EFS Provisioned を立てている間は約 $67 課金される。** 内訳は次の
とおりで、**EC2 は停止すれば止まるが、それ以外は止まらない。**

| リソース | 時間 | 停止で止まるか |
|---|---|---|
| EFS Provisioned 3,072 MiBps（**1 パターンだけ**） | **$30.30** | **止まらない**（削除のみ。引き下げは 24 時間不可） |
| FSx for ONTAP 第二世代 6,144 MBps + 200,000 IOPS + SSD 2,048 GiB | **$22.78** | **止まらない**（削除、または指定値の引き下げ） |
| FSx for ONTAP 第一世代 2,048 MBps + 80,000 IOPS | $4.90 | 止まらない（指定値の引き下げ） |
| c5n.2xlarge ×8（台数を増やす試験） | $4.35 | 止まる |
| c5n.9xlarge ×1（Linux、単体測定） | $2.45 | 止まる |
| c5n.9xlarge ×1（Windows、SMB 測定） | $2.45 | 止まる |
| AWS Managed Microsoft AD Standard | $0.15 | **止まらない**（削除のみ。**停止という状態が無い**） |

**EFS Elastic を選んだ場合はこの表に載らない。** 予約課金がなく、**読み書きした量に $0.07/GB** で
かかる。測定を短くしても下がらないので、読む総量を先に決める。

**EFS Provisioned は 1 パターンのために立て、そのパターンが終わったら即座に削除する。** 東京では
Elastic の 1/20 の読み取り上限しか持たないのに、この表で最も高い。`./runbook.sh drop-efs-provisioned`
がそのためのフェーズで、**一日の終わりではなくパターンの終わりに実行する。**

**消し忘れるとストレージ側とディレクトリだけで月 $24,288 になる。** 全パターンが終わったら
`./teardown.sh` を実行し、**最後の検証行が「nothing tagged for deletion remains」になることを
確認する。** 削除 API がエラーを返さなかったことは、消えた証拠ではない。

**Managed AD はタグを持てない。** `AWS::DirectoryService::MicrosoftAD` に `Tags` プロパティが無い
ので、「削除タグの付いたものが残っていないか」という確認では**見つからない。** 削除確認は
リージョン内のディレクトリを全件列挙して読む形にしてある。

## 既存の AD が使えない理由

**この環境は AD を新設する。** 既存 SVM 2 つは `MEAS.FSXN.LOCAL` に参加した記録を持つが、**その
記録の DNS アドレスに ENI が存在せず、アカウントに Managed AD も 1 つも無い。** ドメイン
コントローラが消えている。SVM が `CREATED` を返すのは参加時の設定が残っているだけで、いま
参加できることを意味しない。

## 必要なもの

| 項目 | 理由 |
|---|---|
| VPC とサブネット 1 つ | **全ターゲットと全クライアントを同じサブネットに置く。** 別 AZ にすると片側だけに AZ ホップが乗る |
| **2 つ目のサブネット（別 AZ）** | **Managed AD のサービス要件。** この環境で唯一の例外で、下の「AD が測定値に入る形」を読むこと |
| 既存の第一世代 FSx for ONTAP の ID | A と E1 で流用する。このディレクトリは作らない（作ると削除もできてしまう） |
| Secrets Manager のシークレット 2 つ（`password` キー） | 第二世代の `fsxadmin` と、AD の `Admin`。テンプレートのパラメータにしないため |
| VDBENCH と Java | auto_vdbench の前提。VDBENCH は Oracle のサイトでライセンス同意のうえ取得する。**Windows クライアントにも入れる** |
| [auto_vdbench](https://github.com/shuichi-taketani/auto_vdbench) | ファイルプロトコル側の測定器 |

Linux クライアントも Windows クライアントも鍵ペアを持たず、パブリックアドレスも持たない。
**接続は AWS Systems Manager（Session Manager）で行う。** 共有アカウントに鍵を残さないため。

**プライベートサブネットでは `ssm` / `ssmmessages` / `ec2messages` の 3 つのインターフェイス
エンドポイントが必要である。** 無いとインスタンスは EC2 では `running` に見えるのに Systems
Manager には現れず、**Windows のドメイン参加が「ディレクトリの問題」の形で失敗する。**
このテンプレート群はエンドポイントを作らない（サブネットは渡す側の資産なので）。
`./runbook.sh windows-status` が、来ているかどうかを読む。

## 手順

```bash
export AWS_REGION=ap-northeast-1
export VPC_ID=vpc-xxxxxxxxxxxxxxxxx        # 既存の FSx for ONTAP と同じ VPC
export SUBNET_ID=subnet-xxxxxxxxxxxxxxxxx  # 全ターゲットと全クライアントを同じサブネットに
export SUBNET_ID_2=subnet-yyyyyyyyyyyyyyyy # AD 用。別 AZ であること
export GEN1_FS_ID=fs-xxxxxxxxxxxxxxxxx     # 既存の第一世代
export FSXADMIN_SECRET_ARN=arn:aws:secretsmanager:...
export AD_SECRET_ARN=arn:aws:secretsmanager:...
export NAME_PREFIX=perfmatrix
export VOLUME_SIZE_GIB=900                 # 省略時 900。runbook がバイトへ換算する
```

### 1. ディレクトリ

```bash
./runbook.sh ad
```

**最初に実行する。** 作成に 15〜30 分かかり、CloudFormation はその間待つ。**あとに回すと、その
待ち時間を $53/時 の EFS と FSx for ONTAP を遊ばせながら過ごすことになる。**

### 2. クライアントと共有セキュリティグループ

```bash
./runbook.sh clients
```

各ターゲットの ingress は CIDR ではなくこのセキュリティグループを参照するので、これが無いと
ターゲットが作れない。

### 3. 第二世代のターゲット

```bash
./runbook.sh gen2
```

**ディレクトリが既にあれば、その事実を読み取って SMB の ingress と AD への egress を追加する。**
このテンプレートは既定で egress を一切持たないので、**この規則が無いと SVM の AD 参加は成立
しない。** 逆に、ディレクトリが無い状態で実行すれば NFS 専用の構成になる。

SSD は 2,048 GiB になる。900 GiB のボリュームを 2 つ（NFS 用と SMB 用）置き、**どちらの読み取りも
256 GB のインメモリキャッシュを超えられるようにするため。** 追加分は約 $0.21/時。

### 4. ディレクトリ側のポート

```bash
./runbook.sh ad-ports
```

**Managed AD が作ったセキュリティグループが、クライアントと SVM のネットワークインターフェイスを
既に許可しているかは、読んで確かめる。** このフェーズは現在の inbound を表示し、足りないものを
追加し、**追加後にもう一度読み直して結果を表示する。**

### 5. SMB 用の SVM と、その AD 参加

```bash
./runbook.sh smb-svm
./runbook.sh join-svm
```

**SMB は NFS 用の SVM とは別の SVM で測る。** CIFS を有効にした SVM では、ONTAP がファイルシステム
操作の一部で win から unix への name-mapping 参照を行い、この参照は到達可能なドメイン
コントローラを必要とする。NFS 用の SVM を参加させると、**この行程が NFS の測定値すべての経路に
入る。**

**ただし 2 つの SVM はファイルシステムのスループットキャパシティを共有する。** 同時に測ると
1 つの 6,144 MBps を分け合う。**片方ずつ測り、どちらを止めていたかを記録する。**

**参加はテンプレートではなく runbook で行う。** `MISCONFIGURED` になった場合、同じ SVM に対して
値を直して再実行すれば回復する。CloudFormation の中で失敗させると SVM ごとロールバックされ、
**次の試行はディレクトリに残った computer object の名前と衝突する。** 再試行するときは
`SVM_NETBIOS_NAME` を使っていない名前に変える。

`join-svm` はライフサイクルを最大 10 分ポーリングする。**呼び出しが返ったことは参加した証拠では
ない。**

### 6. Windows クライアント

```bash
./runbook.sh windows
./runbook.sh windows-status
```

Linux 側と同じ c5n.9xlarge にしてある。**SMB と NFS の比較は、クライアント側が同じでなければ
比較にならない。**

**ドメイン参加は静かに失敗する。** UserData が先に DNS をドメインコントローラへ向けるのは、
それをしないと参加が失敗し、**その理由が association の状態には出ずコマンド出力にしか出ない**
ためである。`windows-status` は Systems Manager にインスタンスが来ているか、参加が走ったかを読む。

**`Success` もまだ間接的な証拠である。** インスタンス自身で確認する。

```powershell
(Get-ComputerInfo).CsDomain      # WORKGROUP ではなくドメイン名が返ること
Get-DnsClientServerAddress       # コントローラのアドレスが出ること
```

### 7. 可否の確認と NVMe キャッシュのゲート

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

### 8. EFS — 2 つのモード

```bash
./runbook.sh efs elastic       # 主要パターン。予約課金なし、$0.07/GB
```

**主要なパターンは Elastic で測る。** 東京では読み取り 61,440 MiBps・書き込み 5,120 MiBps で、
Provisioned の 20 倍の上限を持つ。

予約レートのモードは 1 パターンだけ、別スタックで短時間だけ立てる。

```bash
./runbook.sh efs provisioned          # 確認プロンプトあり。$30.30/時
# ... 1 パターンだけ測る ...
./runbook.sh drop-efs-provisioned     # すぐ消す。削除後に状態を読み直して表示する
```

**別スタックにしてあるのは、Elastic 側に触らずにこれだけ消せるようにするためである。**

### 9. 第一世代の引き上げ

```bash
./runbook.sh raise-gen1   # 確認プロンプトあり
```

**24 分かかった実測がある。** 測定の合間に上げ下げする運用にはしない。

### 10. 測定

ファイルプロトコル側（Linux、NFS）:

```bash
python3 ../../scripts/protocol_matrix_harness.py \
  --target ontap --host <svm-nfs-dns> --export /<volume-junction> \
  --mount-root /mnt/bench --report-root report/ --summary summary-ontap.json
```

ハーネスは**プロトコルを 1 つずつマウントし、要求値ではなく実効のマウントオプションを記録して**
auto_vdbench を呼ぶ。非対応の組み合わせは理由つきでスキップし、失敗として記録しない。

**SMB は Windows 側で auto_vdbench を直接実行する。** ハーネスは SMB をマウントしない（Windows を
駆動しないため）。**結果は同じケース名のディレクトリに置き、Linux 側の結果と同じ表に載せるときは
クライアント OS が違うことを書く。**

**EFS はマウント方法を変える。** 素の `mount -t nfs` ではクライアント 1 台あたり 500 MiBps で
止まる。`amazon-efs-utils` 2.0 以降のヘルパーで 1,500 MiBps になる。**どちらを使ったかを記録する。**
ハーネスは素のマウントを使うので、EFS のヘルパー経路は別に測って両方を残す。

S3 API 側（A-1）は別の測定器を使う。

```bash
python3 ../../scripts/measure_s3_throughput.py --help
```

**auto_vdbench は S3 API のワークロードを生成しない。** VDBENCH はマウントパスに対して動く。
2 つの結果を同じ表に並べるときは、測定器が違うことを表に書く。

### 11. 台数を増やす試験

クライアントは 8 台すべて作られる。**1 / 2 / 4 / 6 / 8 台の測定は、起動する台数を変えて行う。**
同じホストが各段に参加するので、段ごとに別の集合を測ることにならない。

```bash
aws ec2 start-instances --instance-ids <ladder-1>            # 1 台
aws ec2 start-instances --instance-ids <ladder-2>            # 2 台
# ...
```

### 12. 費用の確認

```bash
./runbook.sh costs
```

**フェーズの合間に実行する。** いま何が課金されているかを一覧する。ディレクトリも一覧に入る。
「止めたつもりだった」を防ぐため。

### 13. 削除

```bash
./teardown.sh
```

**順序は費用と依存関係の両方で決まっていて、2 つは逆を向く。** 高い順に消すのが原則だが、SMB 用
SVM は載っているファイルシステムより先に、**そしてディレクトリよりも先に**消さなければならない。
AD 参加済みのリソースをディレクトリの後に消すと、FSx for ONTAP が既に応答しないドメインから
computer object
を削除しようとする。**ディレクトリは作ったものの中で最後に消す。**

最後に状態を読み直して検証し、削除タグの付いたものが残っていれば非ゼロで終了する。第一世代は
削除せず 128 MBps に戻す（他の測定が載っているため）。

## AD が測定値に入る形

**ドメインコントローラはデータ経路には乗らない。** バイトはそこを通らない。**認証と name-mapping の
経路には乗る。** Managed AD は 2 AZ を要求するので、**SMB の値には AZ を跨いでコントローラへ届く
分の遅延が含まれうる。** どちらの AZ のコントローラが応答したかは制御できないので、**この条件は
値に添える。**

## 記録に添える項目

**どれか 1 つ欠けると再現できない。** 一覧は
[性能検証の考慮点](../../docs/ja/reference/performance-testing-guide.md#記録に必ず添える項目)にある。
この環境に固有のものは次の 6 つ。

- **EFS のスループットモードと、マウントに使ったクライアント**（素の `mount` かヘルパーか）
- **NVMe リードキャッシュの状態**と、読んだ量とインメモリキャッシュ量の比
- **世代**（第一世代か第二世代か）と、指定したスループットキャパシティ
- **同じファイルシステム上のもう一方の SVM が動いていたかどうか**（キャパシティは共有される）
- **SMB のダイアレクト**（2.0 / 3.0 / 3.1.1 のどれで成立したか）と**マウントに使ったアカウント**
- **ボリュームのセキュリティスタイル**（NFS 用は UNIX、SMB 用は NTFS）

`Domain Admins` のメンバーは権限評価の一部を迂回する。**代表的な値が要るなら、ディレクトリに
非特権アカウントを作ってそれで測る。**

## テンプレートが意図的にやらないこと

- **VPC・サブネット・既存ファイルシステムを作らない。** すべて渡す。既存を再利用することが
  比較の前提で、サブネットを増やすと片側だけに AZ ホップが乗る。**AD が 2 サブネットを要求するのは
  この方針の例外で、サービス要件によるものである。**
- **SVM の AD 参加をテンプレートの中でやらない。** 失敗したときに同じ SVM に対して直せるように、
  runbook のフェーズにしてある。
- **ドメイン参加にカスタム SSM ドキュメントを使わない。** AWS 管理の
  `AWS-JoinDirectoryServiceDomain` を `AWS::SSM::Association` から呼ぶ。EC2 の `SsmAssociations`
  プロパティとカスタムドキュメントは、**どちらもテンプレート上は正しく見えてデプロイ時に落ちる。**
- **不可逆な保持機能を一切有効にしない。** SnapLock、保持期間、Object Lock、特権削除の無効化は
  どれも入っていない。**この環境は削除される前提で存在する。**
- **バックアップを取らない。** 中身は `/dev/urandom` から生成したテストデータで、その複製に
  課金する意味がない。
- **クライアントに鍵ペアを与えない。** Session Manager で入る。
- **AD にエイリアスを設定しない。** エイリアスは一度設定すると変更も再利用もできないので、
  使い捨てのディレクトリが消費するべきものではない。
