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
| アクセスポイントを取り付けたボリュームで Qtree / Quota / FlexClone / FlexGroup / FlexGroup のクローンが使えるか | 検証済み（すべて使えることを確認） | [相互運用性](reference/limits/s3ap-interoperability.md)。2026-08-26、ap-northeast-1、ONTAP 9.18.1P3D1、SINGLE_AZ_1 / 128 MBps。FlexClone はボリューム単位・ファイル単位の両方。**NetApp が ONTAP S3 について非対応と記載している 4 項目は、この経路では制約として現れない。** 実際の落とし穴は NTFS ボリューム + UNIX identity + CIFS サーバ無し SVM で、取り付けが `AVAILABLE` になったうえで全データ操作が `AccessDenied` になる |
| ファイル単位 FlexClone（`POST /api/storage/file/clone`）の成否を API 応答から判定できるか | 検証済み（判定できないことを確認） | 同記録。202 とジョブ UUID を返すが UUID は `404 entry doesn't exist` で解決できず、ジョブ一覧 166 件にも現れない。**対照:** 同じ `fsxadmin` でボリューム作成とボリュームクローンのジョブは `state=success` として取得できる。存在しないディレクトリを宛先にした呼び出しも 202 を返し何も作られない。宛先ファイルを見て判定する |
| ONTAP API で作ったボリュームが AWS 側の API に現れるまでの時間 | 検証済み（範囲のみ。上限は未確定） | 同記録。20 秒間隔・ギャップ無しで FlexGroup 599 秒、FlexClone ボリューム 1,177 秒。別の回は 1,258 秒でまだ未出現（系列に穴あり）。**3 回一致しないため上限値ではない。** AWS の記載は「数分」 |
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
| Amazon S3 Files を**同一手法**で測った 4 方向の反映速度 | 検証済み | [実測記録](verification/s3files-measured.md)。2026-09-01、ap-northeast-1、NFSv4.2、アクセスポイント経由、`actimeo=0`、64 B、並列度 1、n=30、タイムアウト 0 件。S3 → ファイルは p50 1,533 ms、ファイル → S3 は p50 63,769 ms、マウント内は p50 10.7 ms |
| S3 Files のエクスポートが約 60 秒のバッチング窓を持つこと | 検証済み | 同記録。30 回すべてが 63.8〜66.3 秒。**対照:** CloudWatch `ExportAge` の peak 66.06 秒がクライアント側 max 66.33 秒と 0.27 秒差で一致 |
| S3 Files のインポート側の上限値 | 検証済み（範囲のみ。上限は未確定） | 同記録。クライアント側 p50 1,533 ms / max 14,357 ms に対し、CloudWatch `ImportAge` peak は 62,800 ms。**2 系統が一致しないため上限値ではない** |
| S3 Files でしきい値の両側の読み取り遅延が変わること | 検証済み（**経路差として分離済み**） | 同記録。**オブジェクトサイズを 64 KiB に固定し取り込みしきい値だけを動かした**測定で、高性能ストレージ上 p50 10.8 ms 対 バケット直読 p50 55.0 ms（n=30 ずつ）。経路だけで約 5.1 倍。混ざった状態で見えていた 3.8 倍（64 KiB 対 4 MiB）より大きい |
| S3 Files の削除の反映（両方向） | 検証済み | 同記録。S3 `DeleteObject` → マウントから消えるまで p50 1,524.9 ms、マウント上の `unlink` → `HeadObject` が 404 になるまで p50 64,941.5 ms（n=10、タイムアウト 0） |
| S3 Files の上書きの反映（両方向） | 検証済み | 同記録。S3 → ファイル p50 1,632.1 ms、ファイル → S3 p50 64,975.9 ms。**内容一致で判定**し、中途半端な内容が見えた試行は 0 件。2 回の書き込みは全 10 キーで 2 バージョンになった |
| S3 Files でマルチパートアップロード中の部分オブジェクトがファイル側に見えるか | 検証済み（見えないことを確認） | 同記録。パート 1 の 20 秒後で 3/3 見えず、`CompleteMultipartUpload` 後は 3/3 見える（対照）。**この構成と同じ挙動** |
| S3 Files で同一キーを両側から変更したときの挙動 | 検証済み | 同記録。**バケット側が正本になる**（3/3 が S3 の内容に収束）。ファイル側のバージョンは `.s3files-lost+found-<file-system-id>` へ移され、エントリが 0 → 3。**対照:** CloudWatch `LostAndFoundFiles` の peak 3.00 が一致 |
| `.s3files-lost+found-*` の可読性 | 検証済み | 同記録。ファイルシステムのルートにあり `0700 root:root`。**アクセスポイントでサブディレクトリを root にしている場合は見えず**、読むには `s3files:ClientRootAccess` が必要 |
| S3 Files のマウントヘルパーが `actimeo=0` を honoured するか | 検証済み | 同記録。効く。ただし実効値は `acregmin=0,acregmax=0,acdirmin=0,acdirmax=0` で、**文字列 `actimeo` は現れないため文字列一致では偽陰性になる** |
| **S3 API で書いたオブジェクトのファイルシステム上の所有者** | 検証済み | 同記録。**`root:root`**（ファイル 0644 / ディレクトリ 0755）。アクセスポイントで非 root にマップした利用側は S3 が作ったディレクトリに書き込めない。読み取りは通る。公開ドキュメントに記載を見つけられていない |
| S3 Files の同期ロールの信頼ポリシーのプリンシパル | 検証済み | 同記録。`elasticfilesystem.amazonaws.com`（公式記載どおり）。**対照:** サービスが EventBridge ルールを `ManagedBy: elasticfilesystem.amazonaws.com` で作成したことを確認。作成 API の成功は根拠にしない |
| S3 Files のリソース作成に要する時間 | 検証済み（1 回のみ） | 同記録。ファイルシステムは初回ポーリングで `available`、マウントターゲットは 77 秒。**公開記事の「数分〜十数分」と一致しない。1 回しか作っていないため代表値ではない** |
| S3 Files の実測コスト | 検証済み | 同記録。CloudWatch の課金バイトから算出し、この計測 1 回で **$0.001023**（S3 Files の 3 次元のみ）。`actimeo=0` のためメタデータ読み取りがデータ読み取りの約 10 倍 |
| S3 Files の整合性モデルが close-to-open と表現されるか | 未確認 | 参照したページの記載は「read-after-write の整合性、ファイルロック、POSIX 権限」で、close-to-open という語を見つけられていない。整合性モデルを引用するときこの語を使わない |
| S3 Files を Lambda / ECS / EKS からマウントしたときの挙動 | 未検証 | 対応コンピュートに含まれるが EC2 でのみ確かめた |
| S3 Files のインポート側の上限値 | 未確定 | クライアント側 max 14.36 秒と CloudWatch `ImportAge` peak 62.80 秒が一致しない。2 系統が一致しないため上限として使わない |
| S3 Files を KMS カスタマー管理キーで暗号化した場合 | 未検証 | SSE-S3 のみで確かめた |
| S3 Files の破棄順序の制約 | 検証済み | [実測記録](verification/s3files-measured.md)。エクスポート待ちがあると `delete-file-system` が `ConflictException` を返す（`--force-delete` で強制可、未エクスポートデータは失われる）。**`PendingExports` は 0 を報告していても拒否される。** ファイルシステムが付いているバケットは `BucketHasS3FileSystemAttached` で削除不可なので、バケットは最後ではない |
| `environments/s3files-compare/template.yaml` の CloudFormation デプロイ | 検証済み | 2026-09-01、`CREATE_COMPLETE` まで 375 秒、6 リソースすべて作成、`UPDATE_COMPLETE` も確認。**cfn-lint が通ったうえでデプロイ時に 2 件の欠陥が判明**（セキュリティグループ規則の説明文にアポストロフィ、および出力が「未デプロイ」と誤記） |
| S3 API 経路のスループット / IOPS / 並列度（S3 Access Point と Amazon S3） | 検証済み | [実測記録](verification/throughput-iops-concurrency.md)。2026-09-01、ap-northeast-1、c5n.9xlarge（50 Gbps 保証値）、同一ホスト・同一コード、1 MiB と 8 MiB、並列度 1/4/16/64、各点 30 秒、リトライ無効。**FSx for ONTAP 側の書き込みは購入した 128 MBps の段で止まる（8 MiB 並列 16 で 129.5 MB/s、503 は 0 件）。同じファイルシステムの読み取りは 579.3 MB/s で段の 4.5 倍。** Amazon S3 側は書き込み 757.9 MB/s（弾性、購入した段ではない） |
| 書き込みスループットに効く上限が 3 つあり、段はそのうち 1 つでしかないこと | 検証済み（公式表 + 実測で確認） | [実測記録](verification/throughput-iops-concurrency.md)。段を 128 → 2048 MBps に上げると書き込みは 129.5 → 497.1 MB/s。**128 の段では購入した段が上限として効き（101%）、2048 の段では効かなかった。** ap-northeast-1 の第一世代 Single-AZ では、**既定の SSD IOPS から来る 768 MBps/TiB** と HA ペアあたりの書き込み上限 750 MBps が先に効く（[性能仕様](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)）。**throughput capacity だけを上げても、SSD IOPS が既定のままならディスクスループットの上限は動かない。** 当初この 768 を「SSD 容量から来る固定の天井」と書いたのは誤りで、IOPS のプロビジョニング量で動く（下記の SSD IOPS の行） |
| FSx for ONTAP の S3 API 経路の 1 リクエスト固定費 | 検証済み | 同記録。並列度 1 の p50 は 1 MiB で 363.7 ms、8 MiB で 331.5 ms。**サイズではなくリクエストあたり約 330 ms が支配する**ため、直列に PUT する実装は購入した段を使い切れない |
| ファイル経路のスループット（NFS、逐次、O_DIRECT） | 検証済み | 同記録。FSx for ONTAP は書き込み 129.6 MB/s（段の上限）、読み取り 1130.8 MB/s。S3 Files は書き込み 248.2 MB/s、読み取り 369.6 MB/s（8 ストリーム、頭打ちではなくそこで止めた値）。**マウントは揃わない**（FSx for ONTAP は NFS 4.1 直接、S3 Files は `efs-proxy --tls` 経由の NFS 4.2）。**読み取りの 1130.8 はゼロ埋めデータでの測定で、2026-09-02 に非圧縮で測り直すと同じ段で 297〜317 MB/s だった。書き込みの 129.6（段の上限）は非圧縮でも 133.4 で変わらない。** 書き込みが段に追随するという結論は残るが、**この行の読み取り側の数値は撤回する** |
| FSx for ONTAP NFS の rsize/wsize の上限 | 検証済み | 同記録。1048576 を明示しても NFSv4.1 / NFSv3 の両方で 65536 になる。**要求は黙って引き下げられ、マウントは成功する** |
| コールドリード（128 MBps 段） | 検証済み（ただしペイロードに限定あり） | [実測記録](verification/throughput-iops-concurrency.md)。2026-09-01、128 MBps、16 GB のインメモリキャッシュに対して 24 GiB を介在させて分離。**warm 1164.1 MB/s、cold 751.0 MB/s（比 1.55x）。** **当初 1130 MB/s をファイル経路の読み取り性能として書いたのは誤りで、キャッシュを測っていた**（この結論は動かない）。一方 **cold 751.0 を「768 MBps/TiB の 97.8%」と読んだ解釈は取り下げた。** `/dev/zero` を書いたファイルの読み取りであり、ONTAP はゼロブロックをディスクに行かずに返すため、751.0 と 768 が近いのは偶然。**2026-09-02 に同じ段・同じ介在量でデータだけを非圧縮に変えて測り直すと warm 297.8 対 cold 297.2、比 1.00。warm と cold の差は存在しない。** 1164.1 が出たのはキャッシュから返っていたからではなく、**ゼロブロックがストレージに行かないから**。この行の 2 つの数値は撤回する（[詳細](verification/throughput-iops-concurrency.md#b--128-mbps-段の-warm-と-cold-は非圧縮では同じでした)） |
| コールドリード（2048 MBps 段、非圧縮ペイロード） | 検証済み | [実測記録](verification/throughput-iops-concurrency.md#2048-mbps-段でのコールドリード4-回測って-3-回捨てた)。2026-09-01。400 GiB のボリュームに 256 GB のキャッシュを超える 280 GiB を置き、`nconnect=16`・AES-CTR の非圧縮データ・インライン効率化オフで測定。**SSD IOPS 3,072（`AUTOMATIC`）で 286.1 MB/s、40,000（`USER_PROVISIONED`）で 2042.1 MB/s（7.14 倍）。** 後者は段のディスクスループット 2,048 MBps の **99.7%**。NVMe 読み取りキャッシュを有効に戻すと 2232.0（1.09 倍）。**4 回測って 3 回捨てており、捨てた理由（クライアントの単一フロー上限・ゼロブロック検出・IOPS 律速）が本体より重要** |
| SSD IOPS のプロビジョニングがディスクスループットの上限を動かすこと | 検証済み | 同記録。`AUTOMATIC` 3,072 → `USER_PROVISIONED` 40,000 だけを変え、他は一切変えずに同じ 280 GiB を測定。**286.1 → 2042.1 MB/s。** 公式ドキュメントの「達成できるディスクスループットと IOPS は、throughput capacity から決まる水準と**プロビジョニングした SSD IOPS から決まる水準**の小さい方」という記述と整合。オンライン更新で `UPDATED_OPTIMIZING` が **18 分**。**2026-09-02 に再測すると 286.1 → 2667.2 で、「2,048 MBps の 99.7%」という一致は再現しなかった。** さらに CloudWatch を見ると速い側の読み取りは**バイトの 98.5〜99.9% がディスクに行っていない**。280 GiB はこの段のキャッシュ 238 GiB を 18% 超えただけなので、**7.14 倍という観測は残るが機構は未特定** |
| 既定の NFS マウントが単一 TCP 接続で約 590 MB/s に張り付くこと | 検証済み | 同記録。同じマウントでストリーム数 1 / 4 / 8 の読み取りが 588.1 / 589.9 / 589.7 MB/s と**動かない。** 590 MB/s は 4.7 Gbps で VPC 内の単一フロー上限に相当。`nconnect=16` を付けると同じ測定が 2000 MB/s 級になる。**クライアント側の無料のレバー**。**2026-09-02 に別のファイルシステムで再現。613.1 / 618.7 / 618.7 に対し `nconnect=16` で 1140.6 / 2904.6 / 3062.8。この所見は 2 回独立に再現した唯一のもの** |
| 圧縮可能ペイロードでの測定がストレージ側の上限として使えないこと | 検証済み | 同記録。`/dev/zero` で書いた 280 GiB の読み取りが **3067.3 MB/s**、段のディスクスループット 2,048 MBps の 1.5 倍・既定の 768 MBps の 4 倍で返った。ボリュームの `space_savings.dedupe_percent` は **67%**。測定スクリプトの既定ペイロード（1 バイトの繰り返し）も同じ性質を持つため `--body random` を追加した |
| 段を上げると読み取りが半分になる現象 | 検証済み（再現しないことを確認） | 同記録。新しいファイルシステムで同じ段変更（128 → 2048 MBps）をしても warm は 1164.1 → 1154.8 MB/s でほぼ不変。最初に観測した 589.7 MB/s は再現しない。**ただし 1164.1 / 1154.8 はいずれもゼロ埋めデータ。非圧縮では 128 MBps 段の読み取りは 297〜317 MB/s、2048 MBps 段では 613〜619（`nconnect=16` で 3062.8）で、段を上げると上がる。「半分になる現象は再現しない」という結論は残る** |
| 2048 MBps の段で NVMe 読み取りキャッシュが存在するか | 検証済み | 同記録。**存在し有効**（`system node external-cache` が両ノードで `is_enabled: true`）。128 MBps の段では 0 件。**リージョン別の性能仕様表には NVMe の列がなく、デプロイタイプの節の記述が正しい** |
| NVMe 読み取りキャッシュが大きい逐次 IO で不利に働くか | 検証済み（影響しないことを確認） | 同記録。無効化して再測定し、書き込み 763.1 → 768.0、読み取り 1154.8 → 1152.9 MB/s。差は 1% 未満。**AWS の当該注記が第二世代限定であることと整合。** これらはゼロ埋めデータの測定なので**絶対値をディスク側の上限と比べてはいけない**が、同じ潰れ方をした 2 つの相対比なので「差が 1% 未満」という結論は成立する。非圧縮データでの寄与は別に測っており、キャッシュに入らない 280 GiB の読み取りで **1.09 倍**（2042.1 → 2232.0） 非圧縮での寄与 1.09 倍は 2026-09-02 に **1.095 倍**として再現した |
| 小さいオブジェクトの IOPS 上限 | 検証済み | 同記録。4 KiB / 64 KiB、並列度 1/16/64/256。**書き込みは約 420 req/s、読み取りは約 600 req/s で頭打ちになり、SSD IOPS 3,072 に到達しない**（公称値の 14〜20%）。サイズをほぼ問わない（4 KiB と 64 KiB で書き込み 415.3 対 415.9）。並列度 256 は 64 より改善しない。**律速は S3 Access Point のリクエスト経路で、ストレージの IOPS ではない** |
| 同一ファイルシステム・同一段での NFS と S3 Access Point の書き込み差 | 検証済み（数値を差し替え） | [実測記録](verification/throughput-iops-concurrency.md#差の-41-がどこへ行くか同じカウンタで両経路を測る)。**当初の 768.0 対 497.1（35% 差）は取り下げた。** 両者は別種に潰れた圧縮可能ペイロードの測定で、比を取る前提が成立していなかった。両経路とも非圧縮ペイロード・インライン効率化オフ・SSD IOPS 40,000 で、**同じ ONTAP ボリュームカウンタ**で測り直すと **S3 Access Point 414.0 MB/s 対 NFS 702.1 MB/s（59.0%、差 41%）。** 差はボリュームに届く IO の形にあり、S3 経路は **8 MiB の単一 IO をサービス時間約 1.01 秒で毎秒 49.3 回**（同時 50 本程度）、NFS 経路は **64 KiB の IO を 5.2 ms で毎秒 10,700 回** |
| その 41% が ONTAP の内側にあるのか AWS 側の S3 変換層にあるのか | 未確認（観測不能） | 同記録。`fsxadmin` の資格情報では ONTAP のノードレベル統計に到達できない。`/api/cluster/nodes?fields=statistics` は 0 件、`/api/private/cli/system/node/utilization` と `statistics/show-periodic` は `API not found`。**ボリューム単位のカウンタは取れるが、ノードの CPU は取れない。** これは根本原因ではなく観測の境界 |
| FlexCache 経由の読み取りスループット（FSx for ONTAP → FSx for ONTAP） | 検証済み | 同記録。2026-09-01、両ファイルシステム 128 MBps、同一 AZ・同一 VPC、cluster peering と SVM peering 実施。**初回（充填しながら）558.7、常駐 616.0、origin 直読み（warm 対照）1158.9 MB/s。** 初回と常駐の差は 10%。**WAN ホップのない測定なので上限側の目安**。**2026-09-02 に両側を非圧縮で測り直すと逆になった。常駐 882.7〜907.1 対 origin 直読み 383.3 で FlexCache が 2.31 倍速く、初回充填の代価は 10% ではなく 2.88 倍。** 理由は cache が別のファイルシステムで自分の段と自分のメモリを持つこと。**この行のゼロ埋め由来の数値と「origin の 53%」は撤回する**（[詳細](verification/throughput-iops-concurrency.md#c--flexcache-は-origin-より速い前回の53は逆でした)） |
| S3 Access Point で origin に書いたオブジェクトが FlexCache 側のマウントに出ること | 検証済み（FSx for ONTAP どうし） | 同記録。5 秒後に両マウントで確認。反映の速さそのものはこの測定の対象外 |
| リージョンを跨いだ FlexCache（読み手が遠い場合） | 検証済み | [実測記録](verification/throughput-iops-concurrency.md#リージョンを跨いだ-flexcache読み手が遠い場合)。2026-09-01。origin は ap-northeast-1、cache は **ap-northeast-3**、リージョン間 VPC ピアリング、測定した往復は **connect 9.7 ms**（同一リージョン内は 0.2 ms）。大阪から読んで **1 ストリームでは 602.0 対 101.5 MB/s（5.9 倍）、8 ストリームでは 612.5 対 450.3（1.36 倍）。** 対照は東京の origin をピアリング越しに直接読む形。**並列度が遅延を隠すので、FlexCache が効くのは並列度が低いとき。** オンプレミスではなく、9.7 ms は都市間接続の代役 |
| クライアント台数 1〜4 での集約挙動 | 検証済み | 同記録。同一種別（c5n.2xlarge）で 1/2/3/4 台。**FSx for ONTAP 側の書き込みは 129.4 → 130.9 → 131.5 → 131.0 MB/s（4 台/1 台で 1.01 倍、完全に平ら）**、1 台あたりは台数で割った値。**Amazon S3 側は 583.4 → 1208.0 → 1799.0 → 2464.5（4.22 倍、ほぼ線形）**、1 台あたり不変。読み取りの FSx for ONTAP 側は 1 台（480.9）では上限に届かず、2 台で 600.7 に達してそこから平ら（上限は約 600 MB/s、8 vCPU 1 台では TLS 処理が先に頭打ち） |
| 10 分間の持続（バースト機構の枯渇） | 検証済み（枯渇しないことを確認） | 同記録。書き込み 8 MiB 並列 16 を 10 分、30 秒ごとに区切って報告。**20 区間すべてが 127.8〜130.6 MB/s**、全体 129.6。読み取りも別の 10 分で 481.5〜494.6。**この構成の書き込みにバースト機構は関与せず、購入した段が最初から最後まで上限** |
| S3 Access Point と FlexCache の origin 側読み取りが同じ容量を共有すること | 検証済み（対照付き） | 同記録。10 分の書き込み測定を 2 回行い、片方だけ途中で別リージョンの FlexCache 充填とぶつかった。**510 秒以降で 130 → 66 MB/s に半減**し、清浄な側は同区間で 129〜130 を維持。2 回の差は同時実行された FlexCache 充填だけ |
| 複数クライアントでの集約挙動 | 検証済み | 同記録。8 MiB、並列度 16。**FSx for ONTAP 側は共有された上限**（1 台 585.3 → 2 台合計 592.5、1 台あたり半減）。**Amazon S3 側は 1 台あたりの上限**（649.3 → 合計 1308.9、2.02 倍、1 台あたり不変）。**単一ホストで見えた 649 MB/s は S3 の上限ではなくクライアント側の上限** |
| `aws-origin` テンプレートが生成した fsxadmin パスワードが実効パスワードになること | **検証済み（ならないことを確認、修正済み）** | 2026-09-01。`ExcludeCharacters` が一部の記号しか除外しておらず、記号を含むパスワード（`!` `#` `<` `>` `]` `^` `}` と縦棒）が生成された結果、**シークレットの値と実際のパスワードが一致しなかった。** スタックは `CREATE_COMPLETE`、ファイルシステムは `AVAILABLE` で、ONTAP REST が HTTP 401 と `User is not authorized.` を返すだけ（認証の不一致なのに権限の問題に見えるメッセージ）。FlexCache と peering は ONTAP 専用 API なので、**この状態では配布層を作れない。** `ExcludePunctuation: true` + `RequireEachIncludedType: true` に変更し、テストで固定。原因文字は未特定 |
| ランダム IO とブロックサイズの掃引 | 未計測（このリポジトリでは測らない方針） | 公開実測がある（[e-dash による fio 実測](https://zenn.dev/edash_tech_blog/articles/4ece2a554ecb27)、2026-04、東京）。再測定のコストに見合う独自性がないため参照する |
| 各プラットフォームでの性能特性 | 未計測 | 計測する場合は環境・オブジェクトサイズ・並列度・スループット設定を併記する |
| コスト | 未計測 | サンプル実行の結果と本番見積りを区別して記載する |

## 性能値・コスト値の扱い

実測していない数値は書かない。実測した数値は、次をそろえて書く。

- 計測日
- リージョン
- ONTAP のバージョン
- ファイルシステムの世代・構成・スループット設定
- オブジェクトサイズと並列度
- **ペイロードの種別**（非圧縮か、圧縮可能か）と、ボリュームのインライン効率化の設定
- **SSD IOPS の設定**（`AUTOMATIC` か `USER_PROVISIONED` か、その値）
- **クライアント側のマウント設定**（NFS なら `nconnect` の有無）
- 何を測ったか（クライアント側か、サービスのメトリクスか、ONTAP のカウンタか）

これらを欠いた数値は再現できないので、比較にも見積りにも使えない。
姉妹リポジトリに数値がある場合も、環境が併記されていないものは引き写さない。

> **数値に関する補足**: 姉妹リポジトリの一部のドキュメントには、S3 Access Point への書き込みが
> Cache 側の NFS から読めるまでの所要時間として測定値が記載されている。このリポジトリでは
> 上表のとおり未検証として扱う。測定条件（クラスタ構成、キャッシュの設定、オブジェクトサイズ）が
> この構成の主経路と一致するかを確かめていないためで、数値の正しさを否定するものではない。

### ペイロードの記載が必須である理由

上の一覧に **ペイロードの種別**を足した。これは後から必須にした項目で、理由が実例にある。

**圧縮可能なペイロードで測った数値は、ストレージ側の上限と比較できない。** ボリュームの
インライン圧縮・重複排除・コンパクションが有効なとき、`/dev/zero` や 1 バイトの繰り返しは
ディスクに到達せず、読み出しも再構成で済みます。実測では **280 GiB の読み取りが、段の
ディスクスループットの 1.5 倍・既定水準の 4 倍で返りました。**

そのため、この一覧の数値は次のどちらかである。

| 種別 | 何と比較してよいか |
|---|---|
| 非圧縮（`--body random`、AES-CTR ブロック） | ストレージ側の上限と比較してよい |
| 圧縮可能（`--body fill`、`/dev/zero`） | **同じ潰れ方をした数値どうしの相対比だけ。** 上限に対する割合として読んではいけない |

**現状、2048 MBps 段の一部だけが非圧縮で測り直されています。** 128 MBps 段と FlexCache 側は
圧縮可能ペイロードのままです。該当行にその限定を書いてあります。

## 残っている測定（優先順）

**この一覧は 2026-09-02 に A〜I を実施して洗い替えました。** 結果は
[実測記録](verification/throughput-iops-concurrency.md#残していた-9-件を測ったこの記録の数値を-5-つ訂正します)。
**9 件のうち 5 件が、この一覧より上に書いてあった数値を訂正しました。**

| # | 項目 | 結果 |
|---|---|---|
| A | ペイロードだけを 1 変数にした対照 | **完了。** 書き込みでは **S3 で 0.5%、NFS で 4.7%** しか変わらない。**「17% 以上」は誤りだったので撤回。** 読み取りでは 4 倍変わるという非対称は、書き込みはクライアントが実際にバイトを送るのに対し読み取りは再構成できることで説明がつく |
| B | 128 MBps 段を非圧縮で再測 | **完了。** warm 297.8 対 cold 297.2、**比 1.00。** 「warm 1164.1 対 cold 751.0、比 1.55」は撤回 |
| C | FlexCache 側を非圧縮で再測 | **完了。** 常駐 882.7〜907.1 対 origin 直読み 383.3 で **FlexCache が 2.31 倍速い。** 「origin の 53%」は逆だった |
| D | 小さいオブジェクトの IOPS を 40,000 IOPS で再測 | **完了。** 段を 16 倍・IOPS を 13 倍にして **6 点すべて増えず、書き込みは 25% 低下。** 判定を追認 |
| E | インライン圧縮を戻す手順 | **完了。戻せる。** documented endpoint に `{"efficiency":{"compression":"inline"}}` → `{"efficiency":{"dedupe":"both"}}`。**条件は `efficiency.op_state` が `idle` であること。** private CLI では表現できない |
| F | S3 Files 側が単一フローの上限に当たっているか | **完了。当たっていない。** 読み取りは 8 ストリームで **451.3 MB/s** に達し 16 でも伸びない。450 MB/s は 3.6 Gbps で単一フロー上限の下。止めているのはローカルの `efs-proxy`（16 ストリーム時 CPU 67.3%）。マウントの相手が **127.0.0.1** なので `nconnect` は構造上届かず、指定すると**マウントがハングする** |
| G | 台数ラダーを 4 台より先へ | **完了。8 台まで折れない。** 書き込み 8.23 倍、読み取り 8.04 倍、1 台あたり不変、8 台合計 4783.2 MB/s = 38.3 Gbps。**プレフィックスはホストごとに分けたので、プレフィックスあたりの上限は未試験** |
| H | 41% のうち ONTAP より内側 | **完了。観測可能だった。** ONTAP REST では届かないが **CloudWatch の `CPUUtilization`** で分かる。S3 Access Point 経由 417 MB/s のとき CPU 21〜24%、NFS 800 MB/s のときも 18〜23%。**同じ CPU で 2 倍出ているので、代価は ONTAP の外側** |
| I | 時間帯差と日次の再現性 | **完了。ただし結果は警告寄り。** 同一環境・同一条件は **0.2% 以内**で再現（4 組の複製）。単一フローの天井も別日・別ファイルシステムで再現。一方 **280 GiB の読み取りは 2042.1 → 2667.2（+30.6%）で再現せず、「段の 99.7%」という一致は偶然だった** |

**新しく開いた項目**

| 項目 | なぜ要るか | 規模 |
|---|---|---|
| キャッシュの 2 倍以上を一度に読む | 280 GiB はこの段のキャッシュ 238 GiB を 18% 超えただけで、実測ではバイトの **98.5〜99.9% がディスクに行っていない。** ディスク経路を測るにはボリュームを 700 GiB 以上にして 480 GiB 以上を読む必要がある。**SSD IOPS の 7.14 倍は観測としては残るが機構が未特定** | ファイルシステム 1 つ、ボリューム 700 GiB 以上 |
| 測定時間だけを振る | 497.1（30 秒）と 415（60〜90 秒）の差 16% の出どころ。ペイロードではないことは分かった | ファイルシステム 1 つ、約 15 分 |
| 2048 MBps 段で FlexCache を非圧縮で | C は両側 128 MBps 段。origin を上げると origin 直読みが 2000 MB/s 級になるので、**「FlexCache が 2.31 倍速い」が段によって逆転しうる** | ファイルシステム 2 つ |
| 128 MBps 段のバースト残量 | 非圧縮で warm も cold も 297〜317 に揃うのは、この段のディスクスループットのバースト範囲（128〜600 MBps）と整合する。**バースト残量を直接見ていない** | 既存環境 |

**J. 不可逆操作の系統は、意図的に測っていません。** SnapLock、スナップショットロック、
S3 Object Lock。**保持期間を名指しした指示がない限り有効化しません。** 姉妹リポジトリで
128 MiB の SnapLock 監査ログボリュームがファイルシステム全体を 6 か月削除不能にし、しかも
検証としての成果は出ませんでした。**検証環境は不可逆操作を置いてよい場所ではなく、置いては
いけない場所です。**

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
