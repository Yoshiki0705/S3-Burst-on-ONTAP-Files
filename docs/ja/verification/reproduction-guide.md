# 自分の環境で再現するときの手引き

**問いから入って、環境・パラメータ・合格条件・費用・撤去までを 1 つの表で辿れる形にしたページです。**

**先に読んでいただきたいこと。** このリポジトリの数値をそのまま使えるなら、測る必要はありません。
[測る前に読む性能の期待値](../performance-expectations.md)に、条件付きで全部置いてあります。
**測る価値があるのは、条件が自分の環境と違うときだけです。**

そして測るなら、**環境を作る前に決めることが 3 つあります。**

| 決めること | 決めないと起きること |
|---|---|
| **何を問いにするか** | 環境の大きさが決まらない。下の表は問いごとに最小構成を示している |
| **合格条件を測定前に** | 測ってから基準を決めると、都合のよい点だけが残る。各パターンに条件を書いてある |
| **撤去を同じ作業単位に入れるか** | **これが最大の費用要因。** 第二世代 6,144 は保持だけで月 $1,855、2.6 TiB のボリューム削除に 60〜90 分かかり、その間も満額課金される |

## 問い → 環境の対応表

| 問い | 環境 | 主な資材 | 時間 | 費用 |
|---|---|---|---|---|
| S3 API で書いた分がファイルから読めるか（意味論） | **V-1** 収集側だけ | `environments/aws-origin/` + `patterns/collect/s3-access-point-attachment/` | 40 分 | 約 $0.4/時 |
| S3 API 経路のスループット・IOPS | **V-2** 収集側 + 大きいクライアント | 同上 + `HostInstanceType=c5n.9xlarge` | 2 時間 | 約 $3/時 |
| ファイル経路（NFS）のディスク経路の上限 | **V-3** 第一世代 2048 + SSD | `aws-origin`（`ThroughputCapacityMBps=2048`） | 4 時間 | 約 $6/時 |
| 第二世代の指定値・バースト・ベースライン | **V-4** 第二世代 | `environments/perf-matrix/`（`GEN2_THROUGHPUT`） | 3 時間 | $11〜26/時 |
| SMB（台数・持続・キャッシュ制御） | **V-5** 第二世代 + AD + Windows | `perf-matrix` の `ad` → `smb-svm` → `windows` | 5 時間 | 約 $26/時 |
| iSCSI / NVMe/TCP | **V-6** 第二世代 + ブロック | `perf-matrix`（`GEN2_BLOCK=true`） | 4 時間 | $6〜26/時 |
| FlexCache の読み取り容量 | **V-7** 2 ファイルシステム + ピアリング | `aws-origin` ×2 + ONTAP REST | 3 時間 | 約 $6.5/時 |
| 他クラウド・オンプレミスを Cache に | **V-8** 収集側 + 拠点側 | `environments/onprem-cache/`（Terraform） | — | 環境依存 |

**費用の単価と内訳は[検証パターンごとの費用構造](../reference/comparison/finops-performance-test-patterns.md)にあります。**
上の額は ap-northeast-1 のリスト価格（2026-09-04 取得）から計算した概算です。

> **並列に測るときは、費用より先にアカウントの上限に当たります。**
> **1 リージョンあたりの合計スループットキャパシティは 10,240 MB/s** で、超えると
> ファイルシステムの作成が `ServiceLimitExceeded` で失敗します（2026-09-18 に実測。
> 既存 256 + 2,048 + 2,048 + 128 の上に 6,144 を作ろうとして拒否された）。
>
> ```text
> Account <id> can have at most 10240 MB/s of throughput capacity total
> across file systems in this region.
> ```
>
> **これは作成時に返るので、25 分待ってから分かります。** 複数の環境を同時に立てるなら、
> **先に合計を数えてください。** 他人の測定や別プロジェクトのファイルシステムも同じ枠を使います。
>
> ```bash
> aws fsx describe-file-systems \
>   --query 'sum(FileSystems[].OntapConfiguration.ThroughputCapacity)' --output text
> ```
>
> 引き上げは Service Quotas で申請できますが即時ではありません。**当日中に終わらせるなら、
> 6,144 を要求する環境は 1 つに絞り、安い環境と順番に回すほうが速いです。**
> 削除で枠が戻るまでにも数分かかります（実測で 4 分）。

## 環境ごとの作り方

### 共通の前提

```bash
git clone https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files
cd S3-Burst-on-ONTAP-Files
pip install -r requirements-dev.txt      # cfn-lint など。測定には不要だが、テンプレートを直すなら要る
```

**VPC とサブネットは自分で用意します。** テンプレートは作りません。要件は 2 つだけです。

- **ファイルシステムとクライアントが同じサブネット**にあること（管理エンドポイントへ到達でき、
  AZ をまたぐ遅延が測定に入らない）
- クライアントが **Session Manager のエンドポイントに到達**できること。NAT も VPC エンドポイントも
  無いサブネットなら `AssociatePublicIp=true` を指定します。**到達できないとインスタンスは正常に
  起動して Session Manager に現れず、原因が分かりにくい形で 20 分失います**

### V-1 / V-2 / V-3 — 収集側とファイル経路（`environments/aws-origin/`）

**1 スタックで、ファイルシステム・SVM・ボリューム・検証ホストが揃います。**

```bash
aws cloudformation create-stack \
  --stack-name my-verify --region ap-northeast-1 \
  --template-body file://environments/aws-origin/template.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-xxxxxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-xxxxxxxx \
    ParameterKey=ThroughputCapacityMBps,ParameterValue=2048 \
    ParameterKey=StorageCapacityGiB,ParameterValue=1024 \
    ParameterKey=OriginVolumeSizeMB,ParameterValue=819200 \
    ParameterKey=DeployVerificationHost,ParameterValue=true \
    ParameterKey=HostInstanceType,ParameterValue=c5n.9xlarge \
    ParameterKey=AssociatePublicIp,ParameterValue=true
```

**作成には 25〜35 分かかります。** 出力に管理エンドポイント・NFS の読み方・`fsxadmin` の
シークレット ARN が入ります。

**そのままでは測定に使えません。作成後に 4 つ変えます。** どれも既定のままだと、
意図したものとは別のものを測ります。

| 変えるもの | 方法 | 変えない場合に起きること |
|---|---|---|
| **自動バックアップ** | `aws fsx update-file-system --ontap-configuration '{"AutomaticBackupRetentionDays":0}'` | バックアップのスナップショットが上書き前のブロックを保持し、**容量が 100% になって書き込みが 8 分の 1 に落ちる。`rm` しても戻らない** |
| **スナップショットポリシー** | `aws fsx update-volume --ontap-configuration '{"SnapshotPolicy":"none"}'` | 同上。削除したデータもスナップショットが参照している限り解放されない |
| **インライン効率化** | 同じ `update-volume` で `"StorageEfficiencyEnabled":false`。**データを書く前に** | 圧縮・重複排除がペイロードを吸収し、上限を超えた値が返る |
| **NVMe リードキャッシュ** | ONTAP REST の `system/node/external-cache` を `is_enabled:false` に | 第一世代 Single-AZ の 2 GBps 以上には**既定で付く**。ディスク経路を測るつもりの読みがキャッシュから返る |

> **`update-volume` は成功レスポンスを返した直後には反映されていません。** 実測で約 60 秒かかりました。
> **読み返して確認してください** — このリポジトリで繰り返し踏んでいる形です。

**測定器の持ち込み。** VDBENCH は Oracle のサインインとライセンス同意が必要で、**その場では
再取得できません。** 手元でダウンロードして S3 に置き、クライアントから引きます。

```bash
aws s3 cp vdbench50407.zip s3://<your-bucket>/tooling/
# クライアント側（Session Manager 経由）
dnf install -y java-17-amazon-corretto-headless unzip nfs-utils
aws s3 cp s3://<your-bucket>/tooling/vdbench50407.zip /tmp/
unzip -q -o -d /opt/bench /tmp/vdbench50407.zip
printf '#!/bin/sh\nexec /opt/bench/vdbench50407/vdbench "$@"\n' > /usr/local/bin/vdbench
chmod +x /usr/local/bin/vdbench
vdbench -t     # 自己テスト。"completed successfully" を確認する
```

**`/usr/local/bin` にシンボリックリンクを置くと動きません。** 起動スクリプトが `dirname $0` から
クラスパスを組むので、`Vdb.Vdbmain` が見つからないという Java 側のエラーになります。
**`exec` するラッパーにしてください。**

**マウントは `nconnect` を付けます。** 付けないと約 590 MB/s で止まり、
**ストリーム数を 8 倍にしても動きません。**

```bash
mount -t nfs -o nfsvers=4.1,nconnect=16 <svm-nfs-ip>:/origin_vol /mnt/bench/target
ss -tn state established "dst <svm-nfs-ip>" | grep -c 2049   # 1 なら効いていない
```

**パラメータファイルは `environments/perf-matrix/vdbench/` にあります。** ディスク経路を測るなら、
作業セットを**インメモリキャッシュの 2 倍以上**にしてください。第一世代 2048 のキャッシュは
256 GB（= 238 GiB）なので、512 GiB を 1 回通します。

```text
sd=default,openflag=o_direct,size=512g
sd=sd1,lun=/mnt/bench/target/file1
wd=wd_fill,sd=sd1,seekpct=eof,xfersize=1024k,rdpct=0
wd=wd_seq,sd=sd1,seekpct=eof,xfersize=1024k,rdpct=100
rd=fill,wd=wd_fill,iorate=max,warmup=0,elapsed=7200,interval=60,threads=8
rd=seqread,wd=wd_seq,iorate=max,warmup=0,elapsed=7200,interval=60,threads=8
```

**合格条件（測定前に決める）**: CloudWatch の `DiskReadBytes ÷ DataReadBytes` が **80% 以上**。
下回った点は「ディスク経路を測れていない」として捨てます。**測ったあとに基準を決めないこと。**

```bash
aws cloudwatch get-metric-statistics --namespace AWS/FSx `# allow:naming CloudWatch の名前空間名` \
  --metric-name DiskReadBytes --dimensions Name=FileSystemId,Value=fs-xxxx \
  --start-time <ISO> --end-time <ISO> --period 300 --statistics Sum
```

> **`list-metrics` は直近 14 日しか列挙しません。5 分値は 63 日保持されているので、
> ディメンションを直接指定すれば `get-metric-statistics` で返ります。**
> 撤去済みの環境の測定を後から読み直せます。
>
> **AWS CLI v2 はタイムスタンプをローカル時刻で表示します。** UTC の窓と突き合わせるときは
> 変換してください。

### V-4 / V-5 / V-6 — 第二世代・SMB・ブロック（`environments/perf-matrix/`）

**14 手順の順序と、その順序の理由は[測定環境の README](../../../environments/perf-matrix/README.md)に
あります。** ここに書くのは、どの手順がどの問いに要るかです。

| 手順 | 何を作るか | V-4 | V-5（SMB） | V-6（ブロック） |
|---|---|---|---|---|
| `tooling` | ステージングの確認（作らない） | 要 | 要 | 要 |
| `ad` | AWS Managed Microsoft AD（15〜30 分、$0.146/時） | — | **要** | — |
| `clients` | Linux クライアントと共有セキュリティグループ | 要 | 要 | 要 |
| `gen2` | 第二世代ファイルシステム | 要 | 要 | 要（`GEN2_BLOCK=true`） |
| `ad-ports` | ディレクトリの SG にクライアントと SVM を通す | — | 要 | — |
| `smb-svm` → `join-svm` | SMB 専用 SVM と AD 参加 | — | 要 | — |
| `windows` | Windows クライアントとドメイン参加 | — | 要 | — |
| `block-provision` ほか | LUN / namespace / subsystem | — | — | 要 |
| `preflight` | **版と NVMe キャッシュのゲート** | 要 | 要 | 要 |
| `teardown.sh` | 全削除と検証 | 要 | 要 | 要 |

**環境変数で構成を変えます。**

```bash
export REGION=ap-northeast-1 VPC_ID=vpc-xxxx SUBNET_ID=subnet-xxxx SUBNET_ID_2=subnet-yyyy
export STAGING_BUCKET=<vdbench を置いたバケット>
export FSXADMIN_SECRET_ARN=<'password' キーを持つシークレット>
export GEN2_THROUGHPUT=1536        # 1536 / 3072 / 6144 のみ
export GEN2_STORAGE_GIB=1024       # プロビジョンド IOPS は SSD 1 GB あたり 50 まで
export GEN2_SSD_IOPS=50000
./runbook.sh clients && ./runbook.sh gen2 && ./runbook.sh preflight
```

**費用が桁で変わる 3 箇所です。**

| 選択 | 時間あたり | 効く問い |
|---|---|---|
| `GEN2_THROUGHPUT=1536` + SSD 1,024 + 50,000 IOPS | **約 $5.8** | クライアント間の比較、プロトコルの比較 |
| `GEN2_THROUGHPUT=6144` + SSD 4,096 + 200,000 IOPS | **約 $23** | 公表値との突き合わせ、8 台までの台数試験 |
| + Windows + AD | **+ 約 $2.6** | SMB のみ |

**指定値を再現しないと答えが出ない問いだけ 6,144 にしてください。** クライアント間の差や
プロトコルの差は、両者が同じ天井に張り付かない限り安い構成で読めます。**ただし
プロビジョンド IOPS は削らないこと** — 既定の 3 IOPS/GiB だと両者が同じ IOPS 天井で揃い、
測りたい差が消えます（実測で確認）。

**`preflight` は 2 つをゲートします。** ONTAP の版がクラスタから読めること、
NVMe リードキャッシュが無効であること。**版は AWS API では取れません**
（`FileSystemTypeVersion` は FSx for ONTAP では `null`）。**撤去後は復元できないので、
測定より先に読みます。**

**関門は、それが置かれた経路にしか効きません。** 上の 14 手順を通さずに CloudFormation を
直接叩いて作ると、`preflight` も `smb-preflight` も走りません。**急ぐときに手で作るのが、
版を落とし、Multichannel を落とす経路です**（2026-09-17 と 09-18 に 1 回ずつ踏んでいます）。

#### SMB を測る前に必ず確認する 2 つ

1. **サーバー側の `is_multichannel_enabled` が `true` であること。** 既定は `false` です。
2. **有効化の後にセッションを張り直したこと。** 既存セッションはチャネルが増えません
   （`Remove-SmbMapping` → `New-SmbMapping`）。

**確認は負荷をかけながら `(Get-SmbMultichannelConnection).CurrentChannels` を読みます。**
チャネル数はアイドル時に減るので、測定していない時に読んだ値は測定条件ではありません。

> **単一チャネルは値で見分けられます。** 1 MiB 逐次で **574 MB/s・応答 891 ms** に張り付いたら、
> それは単一チャネルです。**この値は別環境・別の日に 0.05% 以内で再現しました**
> （測定窓を 300〜900 秒に振っても 0.07% しか動きません）。
> 4 チャネルなら同じ測定が読み 2,227.61 / 書き 1,698.42 MB/s の水準になります。

**充填のパラメータも確認してください。** `format=yes` は実行ブロックの `xfersize` と `threads` を
無視し、キュー深度 2 で書きます。**`formatxfersize` を設定しないと 600 GiB の充填に 63 分**
かかり（実測 162.73 MB/s）、その時間はそのまま費用です。

### V-7 — FlexCache（2 ファイルシステム + ピアリング）

**CloudFormation では書けません。** クラスタピアリング・SVM ピアリング・FlexCache はいずれも
ONTAP 側の機能で、AWS API がありません。**このリポジトリのテンプレートが作らない部分です。**

```bash
# origin と cache を別スタックで作る（cache 側は検証ホスト不要）
aws cloudformation create-stack --stack-name my-origin ... ThroughputCapacityMBps=2048
aws cloudformation create-stack --stack-name my-cache  ... ThroughputCapacityMBps=128
# ピアリングと FlexCache は ONTAP REST で（順序が固定）
#   1. cluster peer（両方向、同じパスフレーズ）
#   2. vserver peer（applications=flexcache）
#   3. volume create -junction-active false -aggr-list ... （FlexCache ボリューム）
```

**インターコネクトの IP を SG で通しておく必要があります。** 通っていないとピアリングは
`Unable to communicate` で止まります。ポートと手順は
[FlexCache の検証記録](flexcache-security-style-inheritance.md)にあります。
**別スタックで 2 つ作ると、cache 側の SG は origin 側のホストもファイルシステムも知りません。**
cache の FS SG に、origin のホスト SG と origin の FS SG からの 443 / 111 / 2049 / 4045 / 4046 /
11104 / 11105 を足してください。**443 が抜けていると ONTAP REST に届かず、
「FlexCache が存在しない」に見えます。**

**FlexCache の作成で止まる 3 点は
[オンプレミス側の手順](../deployment/onprem-terraform.md#ピアリングと-flexcache-作成で実際に踏んだ-5-点)に
表でまとめてあります。** 要点だけ再掲すると、`use_tiered_aggregate` を `true` にすること、
`return_timeout` の上限が 120 であること、FlexCache ボリュームの最小が 50 GB であること。

> **この 3 点は 2026-09-01 に記録した後、2026-09-18 に 2 つ踏み直しました。**
> ドキュメントには入っていましたが、**実行していたスクリプト側に入っていなかった**ためです。
> **手順を直したら、その手順を実行する側にも同じ変更を入れてください。**
> 症状は `Aggregates not matching FabricPool requirements: aggr1` で、
> **フラグの名前はメッセージに出ません。**

**ジョブの終状態まで見てください。** 作成は非同期で、POST は job を返して成功します。
`use_tiered_aggregate` が無い状態でも POST は 200 を返し、**失敗は 30 秒後のジョブ状態にしか
現れません。** 応答が返ったことを作成できたことの証拠にしないでください。

**撤去の順序も固定です。** cache を先に解放し、SVM ピア、クラスタピアの順に外してから
ファイルシステムを消します。**逆にすると origin 側のファイルシステムが消えず、課金が続きます。**

### V-8 — 拠点側を自分で持つ場合（`environments/onprem-cache/`）

Terraform で ONTAP に対して FlexCache を作ります。**AWS 側とは別の管理面**なので、
クラスタ / SVM ピアリングは**このリポジトリの範囲外**です（ネットワーク構成が利用者側にある）。
FlexCache 作成が失敗する最も多い理由がこのピアリング未設定です。

## 撤去

**課金が止まるのは削除が終わったときで、削除を始めたときではありません。**

| 資源 | 停止で止まるか | 実測の削除時間 |
|---|---|---|
| EC2 | **止まる**（停止で十分） | — |
| FSx for ONTAP | 止まらない（削除、または指定値の引き下げ） | 800 GiB / 516 GiB 保持で **53 分**、2,200 GiB / 1.8 TiB で **63 分** |
| Managed AD | 止まらない（削除のみ。停止という状態が無い） | — |
| EFS Provisioned | 止まらない（引き下げは 24 時間不可） | — |

**削除しても残るものが 2 つあります。**

1. **最終バックアップ。** CloudFormation はボリューム削除時にバックアップを取り、
   **これはファイルシステムより長生きしてストレージ課金されます**（$0.05/GB-月）。
   516 GiB 分で月約 $26 でした。`SkipFinalBackup` は `AWS::FSx::Volume` が受け付けないので、
   **削除後に `describe-backups` を読んで消します。タグでは見つかりません。**
2. **未アタッチ EBS。** 実測で io2 4 本の消し忘れが月 $361 でした（IOPS 課金が本体）。

```bash
# 撤去後に必ず読む。タグを条件にしない
aws fsx describe-backups --query 'Backups[].[BackupId,CreationTime,Volume.Name]' --output text
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].[VolumeId,Size]' --output text
```

> **`environments/perf-matrix/teardown.sh` は `STAGING_BUCKET` を中身ごと削除します**（手順 7）。
> **VDBENCH はそこにあります。** 次の測定でも使うなら、撤去前に環境変数を外してください。

## 測定を無効にする既定値（再掲）

**どれも既定のまま測ると、返ってくる数値は不自然に見えません。** 気づけないのが問題です。
一覧と気づき方は[性能検証の考慮点](../reference/performance-testing-guide.md)にあります。

1. NFS マウントの TCP 接続 1 本（約 590 MB/s で頭打ち）
2. `dd if=/dev/zero` のペイロード（ゼロブロックはディスクに行かない）
3. ボリュームのインライン効率化
4. `DiskIopsConfiguration` が `AUTOMATIC`
5. リードキャッシュを少しだけ超える読み取り
6. SMB Multichannel が既定で無効（`dialect=3.1.1` でもチャネルは 1 本）

## 記録の様式

**引用に耐える記録には、数値と同じ数の条件が付きます。** 落とすと後から復元できません。
項目は[期待値のページ](../performance-expectations.md#引用のときに落とさないこと)に 9 つ挙げてあります。
**ONTAP の版だけは撤去後に取り戻せないので、測定より先に読んでください。**

## 関連ドキュメント

- [測る前に読む性能の期待値](../performance-expectations.md) — 測らずに済ませるための数値と条件
- [性能検証の考慮点](../reference/performance-testing-guide.md) — 既定値・測定器・記録項目
- [検証パターンごとの費用構造](../reference/comparison/finops-performance-test-patterns.md) — 単価と消し忘れ
- [測定環境](../../../environments/perf-matrix/README.md) — 14 手順とその順序の理由
- [ブロック測定の実行手順](block-measurement-runbook.md) — iSCSI / NVMe/TCP で踏んだ 9 件
- [検証状況](../verification-status.md) — 主張の段階
