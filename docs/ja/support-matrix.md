# サポート状況 — 収集層と配布層

<!-- lang-switcher:start -->
🌐 [日本語](support-matrix.md) | [English](../en/support-matrix.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->

<!-- 出典と分岐の記録
     この表は姉妹リポジトリ FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns の
     docs/support-matrix-fsx-ontap-flexcache-s3ap.md を出発点にしている。
     https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/support-matrix-fsx-ontap-flexcache-s3ap.md

     コピーではなく、次の点で分岐させた。分岐の理由も残す。

     1. プラットフォーム 4 列（FSx for ONTAP / オンプレミス ONTAP / Cloud Volumes ONTAP /
        Lab-Simulator）の形をやめ、収集層と配布層に分けた。この構成では両層を別に検討でき、
        層をまたいだ 1 枚の表は「どちらの層の話か」を読者に推測させる。
     2. 「Cache ボリュームへの S3 Access Point 接続」の行を落とした。元リポジトリの新しい
        記述はこれを可とし、その根拠として FlexCache duality の FAQ を挙げているが、両者は
        別の機構であり、一方の対応状況を他方の根拠にはできない。この構成はどちらも使わないため、
        行そのものが不要になる。
     3. ONTAP バージョン別の機能表（9.8〜9.15.1）を持ち込まなかった。軸が 9.15.1 で止まって
        おり、更新されない表は読者に古い前提を渡す。必要なバージョンは各行に併記する形にした。
     4. presigned URL の行を落とした。この構成の経路に関係せず、元リポジトリ内でも記述が
        揺れているため、引き写すと揺れだけが伝播する。
     5. 未確認の扱いを [検証状況](verification-status.md) に集約した。
-->

対応状況は AWS のサービス仕様と ONTAP のバージョンの両方に依存し、ONTAP のバージョンだけでは
判断できない。表の記載は設計の出発点であり、PoC では必ず実環境で確かめる。

何が検証済みで何が未検証かは[検証状況](verification-status.md)に分けてある。
この表は「公開ドキュメントに何が書かれているか」を示すもので、実機確認の記録ではない。

## 収集層 — S3 API で書き込みを受ける

| プラットフォーム | 機構 | 最小要件 |
|---|---|---|
| Amazon FSx for NetApp ONTAP | S3 Access Point | ONTAP 9.17.1 以降。アクセスポイントとボリュームが同一リージョン・同一アカウント（[制限事項](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html)） |
| オンプレミス ONTAP（AFF / FAS）、ONTAP Select | ONTAP S3 native bucket / S3 NAS bucket | native は ONTAP 9.8 以降、NAS bucket は 9.12.1 以降 |
| Cloud Volumes ONTAP | ONTAP S3 | [対応クライアントプロトコルに S3 を掲載](https://docs.netapp.com/us-en/bluexp-cloud-volumes-ontap/concept-client-protocols.html) <!-- allow:vendor-ref 出典 URL のパス。製品の提案ではない --> |
| Azure NetApp Files | object REST API | 既存データのあるボリュームが必要（空ボリューム不可） |
| Google Cloud NetApp Volumes | S3 multiprotocol | ONTAP モードのみ |

呼び名と実装元の違いは[用語の整理](reference/glossary/object-access-on-ontap.md)にまとめてある。
この構成が使うのは 1 行目だけである。

## 配布層 — FlexCache でファンアウトする

AWS が明記している FSx for ONTAP の FlexCache 対応構成は次の 3 つである
（[対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)）。

| Origin | Cache | この構成での位置 |
|---|---|---|
| オンプレミス ONTAP | FSx for ONTAP | 逆方向。この構成の対象外 |
| FSx for ONTAP | オンプレミス ONTAP | **この構成の主経路** |
| FSx for ONTAP | FSx for ONTAP | リージョン内 / リージョン間の複製に使える |

FSx for ONTAP を Origin としたときに、Cloud Volumes ONTAP / ONTAP Select /
Azure NetApp Files / Google Cloud NetApp Volumes を Cache にできるかは、この表に含まれていない。
**現時点では未確認として扱う。** 「ONTAP ベースだから動く」とまとめない。

逆方向、つまり他クラウドのファイルストレージを Origin として FSx for ONTAP を Cache にする構成も
この表の外にある。判定の分かれ方は[移植性](portability.md)、接続経路そのものは
[他クラウドとの接続経路](multi-cloud-connectivity.md)にある。

参考として、Azure NetApp Files には外部 ONTAP / Cloud Volumes ONTAP の Origin を対象とする
キャッシュボリュームがある（[cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes)）。
FSx for ONTAP を Origin として使えるかは
[要件](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-requirements)の
文面に明示がないため、検証対象としている。

## 収集層に対する制約

| 制約 | 内容 |
|---|---|
| 対応オペレーション | S3 API の一部のみ。イベント通知・ライフサイクル・バージョニング・Object Lock・Requester Pays・条件付き書き込みなどは対象外で、ストレージクラスは `FSX_ONTAP`、暗号化は `SSE-FSX` のみ。Block Public Access は常に有効で変更できない。全項目は[上限値](reference/limits/s3-access-point.md#対象外の機能)（[対応表](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)） |
| 認可 | AWS 側（IAM とアクセスポイントポリシー）と ONTAP 側（ファイルシステム識別情報）の両方が許可する必要がある（[二層認可](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/s3-ap-manage-access-fsxn.html)） |
| `NetworkOrigin` | 作成後は変更できない（変更するには削除して作り直す）。**到達性は origin の種別ではなく、呼び出し元の位置とルーティングで決まる。** Gateway エンドポイントは VPC 内で発生したトラフィックだけをルーティングするため、VPN / Direct Connect / ピア VPC / Transit Gateway 経由で VPC に入る呼び出しには Interface エンドポイントが必要になる（[ネットワークアクセス](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)） |
| オブジェクト名 | S3 名は 1024 バイト、ファイル / ディレクトリ名は 255 文字まで。`part1/part2` と `part1/part2/part3` は NAS 上で同時に存在できない（[NAS データ要件](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html)） |
| サイズ上限 | 単一 `PutObject` と `UploadPart` あたり 5 GiB、オブジェクト全体で 50 GiB。ドキュメントの「GB」表記に対して実測は 2 進接頭辞だった。全体の上限は `CompleteMultipartUpload` の時点で判定されるため、全ペイロードの転送後に失敗する（[検証状況](verification-status.md)） |
| Windows 識別情報 | AD 参加は必須ではない。ドメインが利用できない場合は workgroup モードの CIFS サーバー（[公式手順](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html)。NTLM のみ、Kerberos 非対応）。**AD 参加を選んだ場合は**、すべてのデータ操作に AD ドメインコントローラーへの到達性が必要になり、`HeadBucket` は AD 到達不能でも成功するため疎通確認に使えない |
| ボリューム名 | 英数字とアンダースコアのみ |
| 監査 | ONTAP のファイルアクセス監査に記録されるのはアクセスポイントに固定した識別情報で、呼び出し元の IAM プリンシパルではない。**用途ごとにアクセスポイントを分けることが、監査の粒度を決める。**呼び出し元の特定には AWS CloudTrail 側との突き合わせが必要。追えないものの一覧は[上限値](reference/limits/s3-access-point.md#監査で追えるものと追えないもの)（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#監査ログには誰が記録されるか)） |

## 配布層に対する制約

| 制約 | 内容 |
|---|---|
| セキュリティスタイル | Cache 作成時に Origin から継承される項目として扱われ、Cache 側では設定できない。出典と未確認範囲は[最初に決めること](design-first-decisions.md)を参照 |
| Origin あたりの Cache 数 | AWS ドキュメントは Origin ボリュームが 10 を超える場合に write-around を推奨している。ファンアウト数を増やしたときの挙動は未検証 |
| 削除順序 | Cache を残したまま Origin 側を削除しない。ピアリングの削除は Cache と SVM ピアの解除が先 |
| Cache 側の書き込み | この構成では扱わない。書き込みは Origin 側の S3 Access Point に集約する |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](architecture.md) | 収集層と配布層の全体像 |
| [検証状況](verification-status.md) | 検証済みと未検証の区別 |
| [最初に決めること](design-first-decisions.md) | セキュリティスタイルとプロトコルの関係 |
| [移植性](portability.md) | 層ごとの置き換えを検討する場合 |
| [他クラウドとの接続経路](multi-cloud-connectivity.md) | 他クラウドとの接続の選択肢と対応リージョン |
| [用語の整理](reference/glossary/object-access-on-ontap.md) | 機構の呼び名と実装元 |

---

<!-- lang-switcher:start -->
🌐 [日本語](support-matrix.md) | [English](../en/support-matrix.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
