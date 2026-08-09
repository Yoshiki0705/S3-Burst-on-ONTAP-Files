# 移植性 — 層ごとに置き換える

この構成は 2 つの層に分かれており、それぞれ別に移植を検討できる。
収集層を差し替えても配布層の設計は変わらず、逆も同じである。

層をまたいだ 1 枚の表を作らないのは、そのためである。「どちらの層の話か」を読者に
推測させると、対応バージョンの議論が噛み合わなくなる。

## 収集層 — S3 API で書き込みを受ける側

呼び名と実装元が異なるので、[用語の整理](reference/glossary/object-access-on-ontap.md)を
先に読むと対応が付けやすい。

| プラットフォーム | 機構 | 最小要件 | 段階 |
|---|---|---|---|
| Amazon FSx for NetApp ONTAP | S3 Access Point | ONTAP 9.17.1 以降。アクセスポイントとボリュームが同一リージョン・同一アカウント | 検証済み（姉妹リポジトリ） |
| オンプレミス ONTAP（AFF / FAS）、ONTAP Select | ONTAP S3 native bucket / S3 NAS bucket | native は ONTAP 9.8 以降、NAS bucket は 9.12.1 以降 | ドキュメント記載 |
| Cloud Volumes ONTAP | ONTAP S3 | [対応クライアントプロトコルに S3 を掲載](https://docs.netapp.com/us-en/bluexp-cloud-volumes-ontap/concept-client-protocols.html) <!-- allow:vendor-ref 出典 URL のパス。製品の提案ではない --> | ドキュメント記載 |
| Azure NetApp Files | object REST API | 既存データのあるボリュームが必要（空ボリューム不可） | ドキュメント記載 |
| Google Cloud NetApp Volumes | S3 multiprotocol | ONTAP モードのみ | ドキュメント記載 |

収集層を AWS の外に置く場合、S3 Access Point ではなく ONTAP 自身の S3 機能を使うことになる。
最小バージョンも有効化の手順も別なので、そのまま移植できるわけではない。
配布層の設計はこの差に影響されない。

## 配布層 — FlexCache でファンアウトする側

AWS が明記している FSx for ONTAP の FlexCache 対応構成は 3 つだけである
（[対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)）。

| Origin | Cache | 段階 |
|---|---|---|
| オンプレミス ONTAP | FSx for ONTAP | ドキュメント記載（この構成の対象外。逆方向） |
| FSx for ONTAP | オンプレミス ONTAP | ドキュメント記載 / 実機未検証（**この構成の主経路**） |
| FSx for ONTAP | FSx for ONTAP | ドキュメント記載 |

### 表に含まれていない組み合わせ

FSx for ONTAP を Origin としたときに、次を Cache にできるかは AWS の対応構成表に含まれていない。

| Cache 候補 | 段階 |
|---|---|
| Cloud Volumes ONTAP | 未確認 |
| ONTAP Select | 未確認 |
| Azure NetApp Files | 未確認 |
| Google Cloud NetApp Volumes | 未確認 |

**未確認は「できない」ではなく、「公開ドキュメントに記載を見つけられていない」である。**
同時に「ONTAP ベースだから動く」とも書かない。どちらも根拠がない。

確かめる手順は [PoC チェックリスト](poc-checklist.md)のフェーズ 4 にある。
結果が出たらこの表を更新する。

### 参考 — Azure NetApp Files のキャッシュボリューム

Azure NetApp Files には外部 ONTAP / Cloud Volumes ONTAP の Origin を対象とする
キャッシュボリュームがある（[cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes)）。
FSx for ONTAP を Origin として使えるかは
[要件](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-requirements)の文面に
明示がないため、上表では未確認としている。

同じ要件文が挙げている前提は[最初に決めること](design-first-decisions.md)に引いてある。
セキュリティスタイルの継承に関する記述もそこにある。この構成の主経路で同じ条件が課されるかは
未確認であり、確かめる対象としている。

## 移植で変わらないもの / 変わるもの

| 変わらない | 変わる |
|---|---|
| 収集は S3 API、利用は NFS / SMB という役割分担 | 収集層の機構の名前と有効化手順 |
| 正典は Origin ボリュームで、書き込み経路は 1 本 | 最小 ONTAP バージョン |
| Cache は読み取り用途 | 管理インターフェース（AWS API か ONTAP REST API か） |
| 利用側のプロトコルを Origin 作成前に決める必要 | 対応構成として明記されている組み合わせ |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](architecture.md) | 2 層の全体像 |
| [サポート状況](support-matrix.md) | 制約の一覧 |
| [検証状況](verification-status.md) | 段階の定義 |
| [用語の整理](reference/glossary/object-access-on-ontap.md) | 収集層の機構の呼び名 |
| [PoC チェックリスト](poc-checklist.md) | 未確認を埋める手順 |
