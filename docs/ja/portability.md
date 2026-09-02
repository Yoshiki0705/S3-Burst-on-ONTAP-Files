# 移植性 — 層ごとに置き換える

<!-- lang-switcher:start -->
🌐 [日本語](portability.md) | [English](../en/portability.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->

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

判定の語は 4 つに正規化してある。`documented`（一次資料に記載）、`locally verified`（このリポジトリで実測）、
`unverified`（記載はあるが実機で追っていない）、`unconfirmed`（公開ドキュメントに記載を見つけられていない）。
**`unconfirmed` は「できない」ではない。** 同時に「ONTAP ベースだから動く」とも書かない。どちらも根拠がない。

| プラットフォーム | Origin として | Cache として（Origin は FSx for ONTAP） | 最小バージョン | 対応プロトコル | 一次資料 | 制約 | 判定 |
|---|---|---|---|---|---|---|---|
| Amazon FSx for NetApp ONTAP | ✅ この構成の Origin | ✅ 対応構成に記載 | 収集層に ONTAP 9.17.1 以降 | NFS / SMB | [対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) | Cache は FlexGroup であること。Cache 側は階層化できない | **locally verified**（同一リージョン・VPC ピアリング、NFSv3 は 2026-08-09、SMB は 2026-08-10。条件と範囲は[検証状況](verification-status.md)） |
| オンプレミス ONTAP（AFF / FAS） | ✅ 逆方向として記載 | ✅ 対応構成に記載（**この構成の主経路**） | FlexCache は ONTAP 9.5 以降、write-back は 9.15.1 以降 | NFS / SMB | [対応構成](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) | クラスタ / SVM ピアリングの経路をこのリポジトリの外で用意する | **unverified**（記載はあるが実機で追っていない） |
| ONTAP Select | 収集層は ONTAP S3 で可（[サポート状況](support-matrix.md)） | 対応構成表に記載なし | — | NFS / SMB | — | — | **unconfirmed** |
| Cloud Volumes ONTAP | 収集層は ONTAP S3 で可 | 対応構成表に記載なし | — | NFS / SMB | — | — | **unconfirmed** |
| Azure NetApp Files | 収集層は object REST API で可 | 対応構成表に記載なし。ANF 側にキャッシュボリュームはあるが Origin に FSx for ONTAP を挙げていない | — | NFS / SMB | [cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes)（Origin は外部 ONTAP / Cloud Volumes ONTAP） | キャッシュボリュームでは object REST API 非対応 | **unconfirmed** |
| Google Cloud NetApp Volumes | 収集層は S3 multiprotocol で可（ONTAP モードのみ） | 対応構成表に記載なし | — | NFS / SMB | — | — | **unconfirmed** |

**`一次資料` 欄が空の行は、こちらが探して見つけられていないという意味である。**
存在しないという主張ではない。見つけたら埋める。

確かめる手順は [PoC チェックリスト](poc-checklist.md)のフェーズ 4 にある。
結果が出たらこの表を更新する。

### 逆方向 — 他クラウドのファイルストレージを Origin とする構成

上の表はいずれも **Origin が FSx for ONTAP** の場合である。他クラウドのファイルストレージを
Origin として FSx for ONTAP を Cache にする方向は、AWS の対応構成表に含まれていない。
**この方向は表の外にある。** 段階の付け方が 2 通りに分かれるため、区別して扱う。

| Origin 側 | 判定 | 理由 |
|---|---|---|
| Google Cloud NetApp Volumes | **unconfirmed** | ONTAP モードがあるが、対応構成表に記載がない |
| Azure NetApp Files | **unconfirmed** | ONTAP ベースだが、対応構成表に記載がない |
| Google Cloud Filestore、Azure Managed Lustre、Azure Blob NFS、OCI File Storage | **機構として対象外** | ONTAP ではない。FlexCache は ONTAP 間のクラスタ / SVM ピアリングを要求する |

**`unconfirmed` と「機構として対象外」を同じ語で書かない。** 前者は一次資料か実機で段階が
上がりうるもので、後者は前提が違う。ネットワークが到達しても後者は変わらない。

各クラウドとの接続経路そのものは[他クラウドとの接続経路](multi-cloud-connectivity.md)にまとめてある。

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
| 正本は Origin ボリュームで、書き込み経路は 1 本 | 最小 ONTAP バージョン |
| Cache は読み取り用途 | 管理インターフェース（AWS API か ONTAP REST API か） |
| 利用側のプロトコルを Origin 作成前に決める必要 | 対応構成として明記されている組み合わせ |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](architecture.md) | 2 層の全体像 |
| [サポート状況](support-matrix.md) | 制約の一覧 |
| [検証状況](verification-status.md) | 段階の定義 |
| [用語の整理](reference/glossary/object-access-on-ontap.md) | 収集層の機構の呼び名 |
| [他クラウドとの接続経路](multi-cloud-connectivity.md) | AWS と他クラウドを private につなぐ選択肢と対応リージョン |
| [PoC チェックリスト](poc-checklist.md) | 未確認を埋める手順 |

---

<!-- lang-switcher:start -->
🌐 [日本語](portability.md) | [English](../en/portability.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
