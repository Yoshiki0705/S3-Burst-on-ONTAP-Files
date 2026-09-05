# プロトコル別の可否と、性能比較が成立する組み合わせ

Amazon EFS と Amazon FSx for NetApp ONTAP を、**同じプロトコルで並べて測れるのはどこまでか**を
整理する。**FSx for ONTAP 側のマウント可否は実測した。性能値は未測定である。**

この区別を先に置く理由は、**可否を確認せずに測定計画を立てると、片方でマウントできない組み合わせに
時間を使う**ためだ。下の表で「非対応」の行は、測定の前に落ちる。

## 可否

| プロトコル | D: Amazon EFS | E: FSx for ONTAP | E の段階 |
|---|---|---|---|
| SMB (2.0 / 3.0 / 3.1.1) | **非対応** | **対応**（全世代） | ドキュメント記載。AD 参加済み SVM を作成し SMB エンドポイントの発行まで実測 |
| NFSv3 | **非対応** | **対応** | **実測**（`vers=3` でマウント成立） |
| NFSv4.0 | **対応**（NFSv4.1 が推奨） | **対応** | ドキュメント記載。SVM 側で `v4.0: enabled` を確認 |
| NFSv4.1 | **対応** | **対応** | **実測**（`vers=4.1`） |
| NFSv4.2 | **非対応** | **対応** | **実測**（`vers=4.2`） |
| `nconnect` マウントオプション | **非対応** | **対応**（最大 16 接続） | **実測**（`nconnect=16` が実効オプションに現れた） |

実測は ONTAP 9.18.1P5、SINGLE_AZ_2、Amazon Linux 2023（カーネル 6.18.44）で行った。

> **NFSv4.2 について 1 点補足。** `vserver nfs` に `v4.2` というフィールドは存在せず
> （`fields=v4.2` は無効と返る）、REST 側には `v42_features` がある。**有効化の切り替えが見えない
> まま `nfsvers=4.2` のマウントが `vers=4.2` で成立した。** この版では既定で有効と読めるが、
> 切り替え手段は確認できていない。

> **転送サイズの既定値に注意。** ONTAP の `tcp-max-xfer-size` は既定 65536 で、**`rsize=1048576` を
> 要求しても 65536 で成立する**（実測）。EFS は 1 MiB を許可するので、**双方を既定値のまま測ると
> 64 KiB と 1 MiB を比べることになる。** 引き上げ手順は
> [測定環境](../../../environments/perf-matrix/README.md#7-nfs-転送サイズの既定値)にある。

出どころ:

- EFS は NFSv4.0 と NFSv4.1 のみ対応し、**NFSv2 と NFSv3 は非対応**
  （[Amazon EFS quotas](https://docs.aws.amazon.com/efs/latest/ug/limits.html)）。
  NFSv4.2 は対応プロトコルとして挙げられていない
  （[Using NFS to mount EFS file systems](https://docs.aws.amazon.com/efs/latest/ug/mounting-fs-old.html)）。
- **Windows を実行する EC2 インスタンスからの EFS のマウントは非対応**なので、SMB の比較対象に
  ならない（同上）。EFS は `nconnect` にも非対応（同上）。
- FSx for ONTAP は **NFS v3 / v4.0 / v4.1 / v4.2 と SMB の全世代（2.0 / 3.0 / 3.1.1）**、および
  iSCSI に対応
  （[Accessing your FSx for ONTAP data](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/supported-fsx-clients.html)）。
  `nconnect` は最大 16 接続まで
  （[FSx for ONTAP のパフォーマンス](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)）。

## この表から決まること

**D と E を同じプロトコルで並べて測れるのは、NFSv4.0 と NFSv4.1 の 2 つだけである。**
SMB・NFSv3・NFSv4.2 は E だけの行になるので、D との比較にはならない。

比較の形にするなら、次の 2 種類を分けて書く必要がある。

| 比較の種類 | 対象 | 読み方 |
|---|---|---|
| 同一プロトコルでの D 対 E | NFSv4.0、NFSv4.1 | 2 つの数字を並べられる |
| E のみのプロトコル別 | SMB、NFSv3、NFSv4.2 | E の中での差。D の欠落は「遅い」ではなく**非対応** |

**「非対応」を「遅い」と並べて書かない。** 前者はマウントが成立しないという意味で、性能軸の値では
ない。表に載せるときは空欄ではなく「非対応」と書く。

## 選び方に効く差

可否の差は、性能の前に構成を決めてしまうことがある。

- **読み出し側に Windows がある**なら、D は候補から外れる。SMB が使えるのは E だけである。
  ただし **E で SMB を使うにはディレクトリが要る。** SVM を Active Directory に参加させることが
  前提で、参加した SVM ではドメインコントローラへの到達性がファイルアクセスの条件に入る。
  **「SMB に対応している」と「SMB を使うのに追加のコンポーネントが要らない」は別である。**
  D にディレクトリが不要なのは、D が SMB を提供しないためで、利点として並べられるものではない。
- **既存のアプリが NFSv3 を前提にしている**なら、同じく E だけになる。移行時に NFSv4 系へ
  上げられるかは、アプリ側の前提（ロック、`fcntl` の扱い、ID マッピング）に依存する。
- **単一マウントから帯域を積み上げたい**場合、`nconnect` が使えるのは E だけである。D では
  マウントを分けるか、クライアントを増やす。

## 未測定（性能値）

**この表に性能値は載せない。測っていないためである。** 測定計画と、測るために必要な環境は
[プロトコル別スループットの測定計画](throughput-protocol-matrix-plan.md)にある。

| 測ろうとしている値 | 状態 |
|---|---|
| NFSv4.0 / NFSv4.1 での D 対 E のスループットとレイテンシ | 未測定 |
| E の SMB / NFSv3 / NFSv4.2 のスループットとレイテンシ | 未測定。**SMB はディレクトリを新設したうえで測る**（[環境](../../../environments/perf-matrix/README.md#既存の-ad-が使えない理由)） |
| 同一データを S3 API で読んだ場合と NFS / SMB で読んだ場合の差 | 未測定（[理由](throughput-protocol-matrix-plan.md#既存の測定でこの比較が成立していない理由)） |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [プロトコル別スループットの測定計画](throughput-protocol-matrix-plan.md) | 測定手順、必要な環境、未測定の一覧 |
| [スループット・IOPS・並列度の実測](throughput-iops-concurrency.md) | S3 Access Point 経路と NFS 経路の実測 |
| [S3 Files とこの構成の比較](s3files-vs-flexcache.md) | 設計点の違い |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
| [性能の語の日英対訳](../reference/glossary/performance-terms-ja-en.md) | 上限の種別と測定条件の語 |
