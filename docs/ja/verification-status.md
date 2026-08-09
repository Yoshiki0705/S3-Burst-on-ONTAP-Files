# 検証状況 — 検証済みと未検証を分ける

このリポジトリは公開されている。未検証の項目が動作保証として読まれないように、
段階を明示し、未検証の事項に断定形を使わない。

| 段階 | 意味 |
|---|---|
| 検証済み | 実環境で再現した。環境（ONTAP バージョン、リージョン、構成）を併記する |
| ドキュメント記載 | AWS またはベンダーのドキュメントに記載がある。実機では確かめていない |
| 未検証 | 確かめていない。ドキュメントに記載はあるが実機で追っていない、または記載自体がない |
| 未確認 | 公開ドキュメントに記載を見つけられていない。「できない」ではない |

「ドキュメントに記載がある」と「実機で動く」は別である。前者を後者として引用しない。

## 現在の状態

| 項目 | 段階 | 根拠 |
|---|---|---|
| FSx for ONTAP の S3 Access Point の対応オペレーションと実測サイズ上限 | 検証済み | 姉妹リポジトリ [fsxn-s3ap-serverless-patterns](https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns) での実測。単一 `PutObject` 5 GiB、オブジェクト全体 50 GiB、上限は `CompleteMultipartUpload` の時点で判定される |
| Active Directory 参加 SVM では S3 Access Point の全データ操作に AD ドメインコントローラー到達性が必要 | 検証済み | 同リポジトリ。`HeadBucket` は AD 到達不能でも成功するため偽陽性になる |
| FSx for ONTAP を Origin、オンプレミス ONTAP を Cache とする FlexCache | ドキュメント記載 / 実機未検証 | AWS の[対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)に記載 |
| S3 Access Point 経由で書いたオブジェクトが **同一ボリューム**の NFS でどう見えるか | 検証済み | [検証記録](verification/s3ap-nfs-visibility.md)。2026-08-09、ap-northeast-1、SINGLE_AZ_1 / 128 MBps、UNIX、NFSv3、`actimeo=0`、n=30。S3 → NFS は p50 9 ms、NFS → S3 は p50 873 ms（64 B）。**ONTAP バージョンは特定できず**（同記録に理由） |
| マルチパートアップロード中の部分オブジェクトがファイル側に見えるか | 検証済み | 同記録。`CompleteMultipartUpload` まで NFS 側に現れない |
| NFS クライアントのマウントオプションが可視性に与える影響 | 検証済み | 同記録。削除の反映が `actimeo=0` で 7 ms、既定マウントで 2,171 ms。既定は `acdirmin=30` / `acdirmax=60` |
| NFS 書き込み（Origin）→ S3 AP 経由で読めるまで | 検証済み | [全方向比較](verification/cross-protocol-directions.md)。p50 44 ms（boto3 persistent session）。**初回の 873 ms は CLI 起動コストの誤計測であり撤回** |
| NFS 書き込み（Origin）→ FlexCache Cache NFS で読めるまで | 検証済み | 同記録。p50 6 ms。NFS は Origin に直接コミットされるため S3 経由より速い |
| ONTAP S3 NAS バケット（FlexCache duality）の FSx for ONTAP での利用可否 | **利用不可（プラットフォーム制約）** | 同記録。FSx for ONTAP では ONTAP ネイティブの S3 サービスは `fsxadmin` から操作できず、内部で使用しているサービスが存在するため新規作成も不可。ベアメタル ONTAP / ONTAP Select / CVO でのみ利用可能 |
| S3 Access Point 経由で書いたオブジェクトが **FlexCache の Cache ボリューム**でどう見えるか | **検証済み** | [FlexCache 検証記録](verification/flexcache-s3ap-visibility.md)。2026-08-09、ap-northeast-1、ONTAP 9.18.1P3D1 両クラスタ、VPC ピアリング経由、UNIX、NFSv3、`actimeo=0`、n=30。**S3 → FlexCache NFS は p50 14 ms**。部分マルチパートは `CompleteMultipartUpload` まで見えない。削除の反映は 9 ms |
| セキュリティスタイルとファンアウト先プロトコルの対応、および Cache 作成時の継承 | 未検証 | 根拠は Azure NetApp Files のキャッシュボリューム要件。この構成の主経路で同じ規則が成り立つかは確かめていない（[最初に決めること](design-first-decisions.md)） |
| FSx for ONTAP を Origin としたときの Cloud Volumes ONTAP / ONTAP Select / Azure NetApp Files / Google Cloud NetApp Volumes の Cache 可否 | 未確認 | AWS の対応構成表に記載がない |
| Origin あたりの Cache 数を増やしたときの挙動 | 未検証 | AWS ドキュメントは Origin ボリュームが 10 を超える場合に write-around を推奨しており、ファンアウト数の設計に影響する可能性がある |
| ONTAP 9.18.1 の FlexCache duality と、S3 Access Point をボリュームに接続することの関係 | 別の機構として扱う | 実装元も有効化方法も異なる。一方の対応状況を他方の根拠にしない。この構成はどちらも使わないため設計上の影響はない |
| 各プラットフォームでの性能特性 | 未計測 | 計測する場合は環境・オブジェクトサイズ・並列度・スループット設定を併記する |
| コスト | 未計測 | サンプル実行の結果と本番見積りを区別して記載する |

## 性能値・コスト値の扱い

実測していない数値は書かない。実測した数値は、次をそろえて書く。

- 計測日
- リージョン
- ONTAP のバージョン
- ファイルシステムの世代・構成・スループット設定
- オブジェクトサイズと並列度
- 何を測ったか（クライアント側か、サービスのメトリクスか）

これらを欠いた数値は再現できないので、比較にも見積りにも使えない。
姉妹リポジトリに数値がある場合も、環境が併記されていないものは引き写さない。

> **数値に関する補足**: 姉妹リポジトリの一部のドキュメントには、S3 Access Point への書き込みが
> Cache 側の NFS から読めるまでの所要時間として測定値が記載されている。このリポジトリでは
> 上表のとおり未検証として扱う。測定条件（クラスタ構成、キャッシュの設定、オブジェクトサイズ）が
> この構成の主経路と一致するかを確かめていないためで、数値の正しさを否定するものではない。

> **同一ボリュームの測定を FlexCache の答えとして読まないこと**: [検証記録](verification/s3ap-nfs-visibility.md)
> の数値は、1 つのボリュームに S3 Access Point と NFS の両方からアクセスした場合のものである。
> FlexCache を経由していない。前者は後者の前提条件だが、前者の数値を後者の答えとして
> 引用することはできない。この 2 つを区別することが、この表がある理由の半分である。

### ONTAP バージョンを併記できなかった件

上の測定では ONTAP のバージョンを特定できなかった。FSx for ONTAP の `DescribeFileSystems` が対象の
既存ファイルシステムに対して `FileSystemTypeVersion` を返さず、ONTAP の REST API は
資格情報なしにバージョンを返さないためである。

**この穴は環境を新しく作れば塞がる。**
[収集側のテンプレート](../../environments/aws-origin/template.yaml)は `fsxadmin` の資格情報を
ファイルシステムと同時に作り、検証ホストからそれを読めるようにし、ONTAP の 443 番ポートへの
経路を用意している。既存環境を借りて測ると、この種の情報が後から手に入らないことがある。

## 段階を上げるとき

- 未確認 → ドキュメント記載: 出典 URL を添える
- ドキュメント記載 → 検証済み: 上記の環境情報と、確認手順を添える
- 段階を下げるのはいつでもよい。上げるときだけ根拠を要求する

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [PoC チェックリスト](poc-checklist.md) | 未検証項目を確かめる順序 |
| [サポート状況](support-matrix.md) | 公開ドキュメントに何が書かれているか |
| [最初に決めること](design-first-decisions.md) | 未確認だが後戻りが高い判断 |
