# AWS 上のファイルストレージとオブジェクトストレージの性能を測るときの考慮点

Amazon EFS、Amazon S3、Amazon S3 Files、Amazon FSx for NetApp ONTAP を測る前に確認することを
1 か所に集める。**過去の測定で数値を取り下げた原因は、ほぼすべてここに列挙した項目のどれかだった。**

この文書は測定の前に読むもので、測定結果は含まない。結果は
[検証状況](../verification-status.md)から辿る。

## 先に読む 3 つの表

### 1. 上限は 1 つではない

**「速い / 遅い」の前に、どの上限に当たっているかを確定させる。** サービスごとに上限の種類が
違い、同じ MB/s でも意味が違う。

| サービス | 上限の性質 | 増やし方 |
|---|---|---|
| FSx for ONTAP | **指定した**スループットキャパシティ、SSD から出るディスクスループット、HA ペアあたりの上限の**最小値** | 指定値を上げる、SSD IOPS を上げる、世代を変える |
| Amazon EFS | ファイルシステム単位の上限（スループットモードで決まる）と、**クライアント 1 台あたりの上限** | モードを変える、クライアントを増やす、マウント方法を変える |
| Amazon S3 | サービス側は弾性。実質**クライアント側の帯域**とプレフィックスあたりのリクエストレート | クライアントを増やす、プレフィックスを分ける |
| Amazon S3 Files | クライアント上のプロキシプロセスの CPU | クライアントを大きくする |

### 2. クライアント 1 台で測れる上限には別の天井がある

**サービス側の上限に届く前に、クライアント側で止まることがある。** ここを外すと、測ったものが
サービスの性能ではなくなる。

| 項目 | 値 | 出どころ |
|---|---|---|
| EC2 のネットワークフローあたり | 全二重 **5 Gbps** | [EC2 インスタンスのネットワーク帯域](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-network-bandwidth.html) |
| Linux NFS の TCP 接続 | 既定で**サーバーあたり 1 本**。`nconnect` で最大 16 | [FSx for ONTAP のパフォーマンス](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html) |
| EFS のクライアント 1 台あたり | **1,500 MiBps**（Elastic かつ `amazon-efs-utils` 2.0 以降または EFS CSI ドライバ）。**それ以外は 500 MiBps** | [Amazon EFS quotas](https://docs.aws.amazon.com/efs/latest/ug/limits.html) |
| EFS の `nconnect` | **非対応** | [Using NFS to mount EFS](https://docs.aws.amazon.com/efs/latest/ug/mounting-fs-old.html) |

> **EFS を素の `mount -t nfs` で測ると 500 MiBps で止まる。** マウントヘルパーを使うかどうかが
> クライアント 1 台あたりの上限を 3 倍変える。**測定前にどちらでマウントしたかを記録する。**

**インスタンスは帯域が「Up to」ではないものを選ぶ。** 「Up to 25 Gbps」の表記だと、頭打ちに
当たったときにサービス側なのかクライアント側なのか切り分けられない。

### 3. 測る前に既定値から変える項目

**どれも既定のまま測れて、返る数値は不自然に見えない。**

| 項目 | 既定のまま測ると | 対処 |
|---|---|---|
| Linux NFS の TCP 接続 | 約 590 MB/s で頭打ち。ストリーム数に反応しない | `nconnect=16`（EFS では使えない） |
| `dd if=/dev/zero` のデータ | ゼロブロックがディスクに行かず、公称上限の 4 倍で返る | 非圧縮データ（`/dev/urandom` 由来） |
| ボリュームのインライン効率化 | 圧縮可能データが潰れる | **データを書く前に**オフにする |
| `DiskIopsConfiguration: AUTOMATIC` | 3 IOPS/GiB で IOPS 律速 | `USER_PROVISIONED` |
| リードキャッシュを少しだけ超える読み取り | キャッシュから返る割合が支配し、ディスク経路を測っていない | 下の節を参照 |
| `rsize` / `wsize` の指定値 | 1048576 を要求して 65536 で成立することがある | **実効値**を `/proc/mounts` で確認する |

## FSx for ONTAP — リードキャッシュが 2 層ある

**ファイルサーバーにはインメモリと NVMe の 2 層のリードキャッシュがある**
（[パフォーマンス](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)）。
そして **SSD IOPS が使われるのは、どちらのキャッシュにも入っていないデータを読むときだけ**と
明記されている。ここを踏まなければ、SSD IOPS を上げた効果は測れない。

ap-northeast-1（第一世代 Single-AZ）で公表されているのは層によって違う。

| 層 | 2048 MBps 指定時 | 出どころ |
|---|---|---|
| インメモリ | **256 GB** | 性能仕様の「その他のリージョン」の表 |
| NVMe リードキャッシュ | **記載なし** | 同じ表に列が無い。列がある 4 リージョンでは同じ 2048 MBps で 1,900 GB |

NVMe 側は別の節に条件だけがある。**2022-11-28 以降に作成され、2 GBps 以上のスループット
キャパシティを持つ Single-AZ 1 には付く。** 実機では `system node external-cache` で確認できる。

**ディスク経路を測るには 2 つの道がある。**

| 方法 | 必要なこと | 代償 |
|---|---|---|
| 2 層の合計を超える量を一度に読む | NVMe が 1,900 GB 相当なら 4 TB 規模の読み取り。SSD 容量もそれ以上 | SSD 容量の費用が伸びる |
| NVMe キャッシュを無効化して測る | `external-cache modify -is-enabled false` | インメモリ 256 GB は残るので、その 2 倍以上は読む |

## FSx for ONTAP — 世代による上限の違い

**第一世代の Single-AZ は HA ペアが 1 つで、書き込みの上限はそこで決まる。** 指定値を上げても
動かない。

| 項目 | 第一世代 Single-AZ（ap-northeast-1） | 第二世代 Single-AZ |
|---|---|---|
| HA ペア数 | 1 | **最大 12** |
| 読み取り上限（HA ペアあたり） | 2,048 MBps | **6,144 MBps** |
| 書き込み上限（HA ペアあたり） | **750 MBps** | **1,024 MBps** |
| 書き込みの考え方 | 上表の固定値 | 指定値の読み取り全量、書き込みは概ね 1/3 |

出どころは[性能仕様](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)。

> **この検証は第一世代で行う。** 一般的なコスト見合いで選んでいる。
> **ただし第一世代では書き込み 750 MBps が上限で、これは指定値をいくら上げても動かない。**
> それ以上の書き込みスループットが要件になるワークロード、あるいは 1 ファイルシステムで
> 数 GB/s 規模の集約が要件になるワークロードでは、**第二世代が到達できる範囲は第一世代の
> 到達範囲を超える。** HA ペアを最大 12 まで並べられるため、必要な性能が高くなるほど
> **性能あたりの費用でも第二世代が有利になりうる**（第一世代では到達できない領域があり、
> そこでは比較の対象にならない）。要件が 750 MBps の書き込みを超えるなら、世代の選択を
> 性能要件の側から決める。

## Amazon EFS — モードで上限が変わり、東京は上位の枠にいる

**Elastic / Provisioned / Bursting の 3 モードがあり、上限はモードとリージョンで決まる**
（[Amazon EFS quotas](https://docs.aws.amazon.com/efs/latest/ug/limits.html)）。
**ap-northeast-1 は Elastic の上位グループに入っている。**

| モード | ap-northeast-1 の読み取り | 同 書き込み |
|---|---|---|
| **Elastic** | **60 GiBps** | **5 GiBps** |
| Provisioned | 3 GiBps | 1 GiBps |
| Bursting | 3 GiBps | 1 GiBps |

> **最大性能を狙うなら Elastic である。** Provisioned は「指定できる」だけで、東京での上限は
> Elastic の 1/20 になる。**モード名から性能の高低を推測すると外す。**

2 つの読み替えが必要になる。

- **読み取りは 1:3 で計量される。** 上の「60 GiBps」は計量後の値で、読み取りは他の操作より
  安く数えられる。**読み取りと書き込みの合計で 100% に達する**設計なので、読み取りで 33% 使うと
  書き込みは 67% までになる。
- **ファイルシステム単位の上限とクライアント単位の上限は別**である。60 GiBps に届かせるには
  クライアントを並べる。1 台では前述の 1,500 MiBps（または 500 MiBps）で止まる。

避けるべきマウントオプションが明記されている。**`noac` / `actimeo=0` / `lookupcache=none` は
性能への影響が大きい**（[EFS performance tips](https://docs.aws.amazon.com/efs/latest/ug/performance-tips.html)）。
反映の速さを測る目的で `actimeo=0` を使った測定結果を、スループットの測定結果と同じ表に
並べない。

## Amazon S3 — プレフィックスとクライアント台数

**サービス側は弾性で、単一ホストで見える値はクライアント側の上限である。**

| 項目 | 値 | 出どころ |
|---|---|---|
| リクエストレート | プレフィックスあたり **3,500 PUT/COPY/POST/DELETE**、**5,500 GET/HEAD** / 秒 | [Performance design patterns for Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-design-patterns.html) |
| プレフィックス数 | 上限なし | 同上 |
| スケールの仕方 | 自動だが**段階的**。その間 **HTTP 503 (Slow Down)** が返る | 同上 |

測定設計に効くこと。

- **プレフィックスを分けたかどうかを記録する。** ホストごとに別プレフィックスを使うと
  プレフィックスあたりの上限を試していないことになる。**「折れなかった」の意味が変わる。**
- **503 の件数を必ず記録する。** 0 件でないなら、スケール途中の値を測っている。
- **リトライを有効にしたまま測らない。** 503 が透過的に再試行されると、スループットは下がるが
  エラーとしては見えない。

## Amazon S3 Files — 経路にクライアント上のプロセスが入る

**マウント先は `127.0.0.1` で、クライアント上の転送プロセス（`efs-proxy`）に接続する。**
だから頭打ちの位置がクライアント上の CPU になりうる。

| 項目 | 値 | 出どころ |
|---|---|---|
| `nconnect` | **非対応** | [Unsupported features, limits, and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |
| NFS のバージョン | NFSv4.1 / 4.2（一部の 4.2 機能は非対応） | 同上 |
| バケット → ファイルの反映 | 通常数秒。毎秒 2,400 オブジェクト、700 MB/s まで | [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) |
| ファイル → バケットの反映 | 約 60 秒まとめてから。毎秒 800 ファイル、2,700 MB/s まで | 同上 |

**`nconnect` が増やすのはクライアントとプロキシの間の接続数**である。頭打ちがプロキシ自身の
CPU なら、対応していても届かない。**未対応のマウントオプションを試すときは `timeout` を
付ける。** ハングして測定が失われる。

## プロトコル別に測れる組み合わせ

**可否を先に確認する。** 非対応の組み合わせは測定の前に落ちる。詳細は
[プロトコル別の可否](../verification/protocol-matrix-efs-vs-ontap.md)。

| プロトコル | Amazon EFS | FSx for ONTAP |
|---|---|---|
| SMB | 非対応 | 対応（2.0 / 3.0 / 3.1.1） |
| NFSv3 | 非対応 | 対応 |
| NFSv4.0 / NFSv4.1 | **対応** | **対応** |
| NFSv4.2 | 非対応 | 対応 |

**同じ列に並べられるのは NFSv4.0 と NFSv4.1 だけ**である。

## 測定器の選び方と、混ぜてはいけない境界

| 測る対象 | ツール | 出る単位 |
|---|---|---|
| NFS / SMB | [auto_vdbench](https://github.com/shuichi-taketani/auto_vdbench)（Oracle VDBENCH を駆動） | IOPS、レイテンシ、スループット |
| S3 API | `scripts/measure_s3_throughput.py` | スループット、req/s、p50 |
| ストレージ側の実際の IO | ONTAP のボリュームカウンタ | ops/s、1 IO の平均サイズとサービス時間 |
| ノードの CPU、ディスク到達率 | Amazon CloudWatch（`AWS/FSx`） <!-- allow:naming CloudWatch の名前空間名そのもの --> | 使用率、`DiskReadBytes` ÷ `DataReadBytes` |

**auto_vdbench は S3 API のワークロードを生成しない。** VDBENCH はマウントパスに対して動く。
2 つの値を並べるときは、**測定器が違うことを表に書く。** VDBENCH の IOPS と S3 の req/s は
同じものを数えていない。

**クライアント側の計測とストレージ側のカウンタは別のものを見ている。** プロトコルごとに
数え方が違うので、経路の比較はストレージ側の同じカウンタで行う。

## 記録に必ず添える項目

**どれか 1 つ欠けると再現できない。**

- 測定日、リージョン、AZ
- ファイルシステムの世代・デプロイタイプ・指定したスループットキャパシティ・SSD 容量・SSD IOPS 設定
- EFS のスループットモードと、マウントに使ったクライアント（素の `mount` かヘルパーか）
- プロトコルとバージョン、**マウントの実効オプション**（指定値ではない）
- テストデータの性質（非圧縮か、圧縮可能か）
- ブロックサイズ / オブジェクトサイズ、並列度、測定時間
- 繰り返し回数と、同一条件での再現性
- 503 / エラーの件数
- キャッシュの状態（NVMe の有効・無効、読んだ量とキャッシュ量の比）

## 過去の測定でここを踏んで取り下げた項目

**同じ轍を踏まないための一覧。** 詳細は[スループット実測記録](../verification/throughput-iops-concurrency.md)。

| 踏んだ項目 | 何が起きたか |
|---|---|
| ゼロ埋めデータ | 読み取りが公称上限の 4 倍で返り、warm と cold の差、FlexCache の比較がすべて崩れた |
| キャッシュ量の見積り | 280 GiB でインメモリ 256 GB を 18% 超えただけで、98.5〜99.9% がディスクに行っていなかった |
| 上限への一致 | 「段の 99.7%」と読んだ値が別日に 30% 動き、一致は偶然だった |
| 圧縮可能データでの経路比較 | 別種に潰れた 2 つの数値を比べていた。同じボリュームカウンタで測り直して差が 35% → 41% に変わった |
| 単一ホストでの上限 | 約 500 MB/s を S3 の上限と読んだが、クライアント側の上限だった |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [プロトコル別の可否](../verification/protocol-matrix-efs-vs-ontap.md) | どの組み合わせがマウントできるか |
| [プロトコル別スループットの測定計画](../verification/throughput-protocol-matrix-plan.md) | 測定パターンと必要な環境 |
| [スループット・IOPS・並列度の実測](../verification/throughput-iops-concurrency.md) | 既存の実測と、その限界 |
| [S3 Files とこの構成の比較](../verification/s3files-vs-flexcache.md) | 設計点の違い |
| [性能の語の日英対訳](glossary/performance-terms-ja-en.md) | 上限の種別と測定条件の語 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
