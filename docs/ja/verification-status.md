# 検証状況 — 検証済みと未検証を分ける

<!-- lang-switcher:start -->
🌐 [日本語](verification-status.md) | [English](../en/verification-status.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->

このリポジトリは公開されている。未検証の項目が動作保証として読まれないように、
段階を明示し、未検証の事項に断定形を使わない。

| 段階 | 意味 |
|---|---|
| 検証済み | 実環境で再現した。環境（ONTAP バージョン、リージョン、構成）を併記する |
| ドキュメント記載 | AWS またはベンダーのドキュメントに記載がある。実機では確かめていない |
| 未検証 | 確かめていない。ドキュメントに記載はあるが実機で追っていない、または記載自体がない |
| 未確認 | 公開ドキュメントに記載を見つけられていない。「できない」ではない |

「ドキュメントに記載がある」と「実機で動く」は別である。前者を後者として引用しない。

## 中核の検証範囲

この構成の中核は「S3 Access Point で Origin に書いたオブジェクトが、FlexCache の Cache ボリューム上の
NFS / SMB からいつ読めるか」である。**検証済みの範囲と未検証の範囲を分けて述べる。**

| 範囲 | 段階 |
|---|---|
| Cache が **FSx for ONTAP**（同一リージョン、VPC ピアリング）、NFSv3、UNIX、64 B、`actimeo=0` | **検証済み**（2026-08-09、ap-northeast-1、ONTAP 9.18.1P3D1 両クラスタ、n=30）。p50 は 3 回の測定で 7〜14 ms に散り、代表値は 8 ms |
| 同条件で SMB（AWS Managed AD 参加、`cache=none`） | **検証済み**（2026-08-10、同環境、n=30） |
| Cache が **オンプレミス ONTAP**（この構成の主経路） | **未検証**。AWS の対応構成に記載はあるが実機で追っていない |
| 遠隔拠点・高レイテンシ経路 | 未検証。測定はサブミリ秒のネットワーク遅延下 |
| NTFS セキュリティスタイル、`actimeo=0` 以外のマウント、Cache 複数 | 未検証 |

**「中核は検証済み」と 1 語で述べない。** 検証したのは Cache 側も FSx for ONTAP という条件で、
主経路として掲げているオンプレミス ONTAP Cache は未検証である。この節が段階の唯一の出所であり、
他の文書はここへリンクする。

## 現在の状態

| 項目 | 段階 | 根拠 |
|---|---|---|
| FSx for ONTAP の S3 Access Point の対応オペレーションと実測サイズ上限 | 検証済み | 姉妹リポジトリ [FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns) での実測。単一 `PutObject` 5 GiB、オブジェクト全体 50 GiB、上限は `CompleteMultipartUpload` の時点で判定される |
| Active Directory 参加 SVM では S3 Access Point の全データ操作に AD ドメインコントローラー到達性が必要 | 検証済み | 同リポジトリ。`HeadBucket` は AD 到達不能でも成功するため偽陽性になる |
| S3 Access Point 経由の presigned URL（`PutObject` / `HeadObject` / `GetObject`） | 検証済み | [検証記録](verification/s3ap-operations.md)。2026-08-19、ap-northeast-1、SINGLE_AZ_1 / 128 MBps、UNIX、AWS 外のクライアントから、n=30 × 4 回。3 つとも成功し、SigV4 と SigV2 の両方で動作。**公式対応表は `Presign — Not supported` と記載しており、測定はそれと逆向き。** 本番ワークロードを依存させない判断は変えない。ONTAP バージョンは特定できず |
| 同一 Access Point 内をソースとした `UploadPartCopy` | 検証済み（失敗することを確認） | [検証記録](verification/s3ap-operations.md)。2026-08-19、同環境。**`NoSuchKey` を返す。** 同一の `CopySource` を与えた `CopyObject` は同一実行内で成功しており対照が取れている。**公式対応表は同一 AP 内・同一リージョンを対応としており、測定はそれと逆向き。** ただし別 AP 経由のコピーは `CopyObject` でも拒否されるため、**`UploadPartCopy` そのものの対応可否は未判定** |
| FSx for ONTAP を Origin、オンプレミス ONTAP を Cache とする FlexCache | ドキュメント記載 / 実機未検証 | AWS の[対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)に記載 |
| S3 Access Point 経由で書いたオブジェクトが **同一ボリューム**の NFS でどう見えるか | 検証済み | [検証記録](verification/s3ap-nfs-visibility.md)。2026-08-09、ap-northeast-1、SINGLE_AZ_1 / 128 MBps、UNIX、NFSv3、`actimeo=0`、n=30。S3 → NFS は p50 9 ms、NFS → S3 は p50 873 ms（64 B）。**ONTAP バージョンは特定できず**（同記録に理由） |
| マルチパートアップロード中の部分オブジェクトがファイル側に見えるか | 検証済み | 同記録。`CompleteMultipartUpload` まで NFS 側に現れない |
| NFS クライアントのマウントオプションが可視性に与える影響 | 検証済み | 同記録。削除の反映が `actimeo=0` で 7 ms、既定マウントで 2,171 ms。既定は `acdirmin=30` / `acdirmax=60` |
| NFS 書き込み（Origin）→ S3 AP 経由で読めるまで | 検証済み | [全方向比較](verification/cross-protocol-directions.md)。p50 44 ms（boto3 persistent session）。**初回の 873 ms は CLI 起動コストの誤計測であり撤回** |
| NFS 書き込み（Origin）→ FlexCache Cache NFS で読めるまで | 検証済み | 同記録。p50 6 ms。NFS は Origin に直接コミットされるため S3 経由より速い |
| S3 Access Point 経由の操作が **FPolicy** 通知を発火するか | 検証済み（発火しないことを確認） | [検証記録](https://github.com/Yoshiki0705/FSx-for-ONTAP-Observability-integrations/blob/main/docs/ja/verification-results-fpolicy-s3ap-and-session.md)。2026-08-26、ap-northeast-1、ONTAP 9.18.1P3D1。UNIX / WINDOWS identity の両方で、無操作 90 秒 0 件 / S3 AP データプレーン 9 回 0 件 / 同一ボリュームのファイルプロトコル対照は発火。FPolicy の event が受け付けるプロトコルは `cifs` / `nfsv3` / `nfsv4` のみで `s3` は HTTP 400 |
| S3 Access Point 経由の操作を **FPolicy `mandatory`** で遮断できるか | 検証済み（遮断できないことを確認） | 同記録。同期エンジン + `mandatory=true` の下で NFSv3 書き込みは `Permission denied` になる一方、同一ボリュームの S3 AP で PUT / GET / LIST / DELETE がすべて成功。policy を無効化すると同一の NFS 書き込みが通るため対照が取れている |
| S3 Access Point 経由の操作が **ONTAP ネイティブ監査ログ**に記録されるか | 検証済み（記録されることを確認） | 同記録。`Source=HTTP`（オブジェクト操作）と `Source=S3`（LIST）で記録される。ただし `SubjectUserName` / `SubjectDomainName` は `Not Present`、`SubjectIP` は AWS のサービス側アドレスで、**要求者は記録されない**。`HeadObject` は 6 回発行して 0 件。監査 ACE（SACL）が必要 |
| S3 Access Point 経由の書き込みを **ARP** が検知するか | 検証済み（検知することを確認） | 同記録。ARP 5.0（学習期間不要の世代）。AP 経由で書いた高エントロピーファイル 150 件が suspect として `High Entropy` で記録され `attack_probability` は `moderate`。**`attack_probability` は書き込みから 10 分以上遅れて変わる**ため、短時間の観測で `none` を見て未検知と判断すると偽陰性になる。ARP による**遮断は未測定** |
| **Cache 側**で FPolicy / 監査 / ARP が発火するか | 未検証 | 上記はすべて Origin 側での観測。この構成の書き込みは Origin に届くため、Cache 側の挙動は別の問いとして残っている |
| ONTAP S3 NAS バケット（FlexCache duality — S3 Access Point とは**別の機構**）の FSx for ONTAP での利用可否 | **通常ボリューム: 動作 / FlexCache: `-is-s3-enabled true` で動作** | [全方向比較](verification/cross-protocol-directions.md)。通常ボリュームでは NFS 書き込み → ONTAP S3 GetObject が成功（CLI 経由で S3 ユーザー作成可能）。FlexCache ボリュームは既定では `GetObject` / `ListObjectsV2` が AccessDenied だが、`flexcache config modify -is-s3-enabled true`（advanced 権限）で成功した（2026-08-10）。ONTAP 9.18.1P3D1、FSx for ONTAP。出典: [Enable S3 access to NAS FlexCache volumes](https://docs.netapp.com/us-en/ontap/flexcache/enable-flexcache-duality.html) |
| S3 Access Point 経由で書いたオブジェクトが **FlexCache の Cache ボリューム**でどう見えるか | **検証済み** | [FlexCache 検証記録](verification/flexcache-s3ap-visibility.md)。2026-08-09、ap-northeast-1、ONTAP 9.18.1P3D1 両クラスタ、VPC ピアリング経由、UNIX、NFSv3、`actimeo=0`、n=30。**S3 → FlexCache NFS は p50 8 ms**（boto3 の持続セッション。3 回の測定で 7〜14 ms に散り、差は S3 クライアント側の測定方法）。同一セッション内で FlexCache が加えるのは +5 ms。部分マルチパートは `CompleteMultipartUpload` まで見えない。削除の反映は 9 ms |
| セキュリティスタイルとファンアウト先プロトコルの対応、および Cache 作成時の継承 | 未検証 | 根拠は Azure NetApp Files のキャッシュボリューム要件。この構成の主経路で同じ規則が成り立つかは確かめていない（[最初に決めること](design-first-decisions.md)） |
| FSx for ONTAP を Origin としたときの Cloud Volumes ONTAP / ONTAP Select / Azure NetApp Files / Google Cloud NetApp Volumes の Cache 可否 | 未確認 | AWS の対応構成表に記載がない |
| **逆方向** — Google Cloud NetApp Volumes / Azure NetApp Files を Origin として FSx for ONTAP を Cache にできるか | 未確認 | AWS の対応構成表に記載がない。ONTAP ベースであることを根拠にしない（[移植性](portability.md)、[他クラウドとの接続経路](multi-cloud-connectivity.md)） |
| Google Cloud Filestore / Azure Managed Lustre / Azure Blob NFS / OCI File Storage を FlexCache の Origin または Cache にできるか | 機構として対象外 | ONTAP ではない。FlexCache は ONTAP 間のクラスタ / SVM ピアリングを要求する。**未確認とは区別する** |
| パートナー経由（Direct Connect と相手クラウドの専用線を相互接続プロバイダのファブリックで結ぶ）でのクラスタピアリング成立と、その経路での FlexCache 読み取り | 未確認 | 各サービスのドキュメント記載はあるが、この組み合わせを実機で追っていない（[他クラウドとの接続経路](multi-cloud-connectivity.md)） |
| ONTAP が intercluster LIF に MACsec を提供するか | 未確認 | 記載を見つけられていない。FlexCache のトラフィックの暗号化は cluster peering encryption（ONTAP 9.6 以降、TLS 1.2 AES-256 GCM）としてドキュメント記載がある |
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
| [他クラウドとの接続経路](multi-cloud-connectivity.md) | 他クラウドとの接続の選択肢、対応リージョン、暗号化の層 |
| [最初に決めること](design-first-decisions.md) | 未確認だが後戻りが高い判断 |

---

<!-- lang-switcher:start -->
🌐 [日本語](verification-status.md) | [English](../en/verification-status.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
