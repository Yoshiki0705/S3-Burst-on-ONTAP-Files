# 訳語と、訳さないもの

日本語が正典で、英語は Tier 1 のみです（[i18n-manifest.txt](i18n-manifest.txt)）。
`make en-lang` が英語ドキュメントに残った日本語を検出します。

## 訳さないもの

翻訳すると別物になるか、検索・コピーの妨げになるものです。

| 分類 | 例 |
|---|---|
| 製品名・サービス名 | Amazon FSx for NetApp ONTAP、FSx for ONTAP、Amazon S3、AWS DataSync、Azure NetApp Files、Google Cloud NetApp Volumes |
| ONTAP の機能名 | FlexCache、FlexClone、FlexVol、SnapMirror、Snapshot、SnapLock、FabricPool、FPolicy、duality |
| 概念名 | S3 Access Point、Origin ボリューム、Cache ボリューム、SVM、LIF、IPspace |
| API・パラメータ名 | `PutObject`、`CompleteMultipartUpload`、`FileSystemIdentity`、`NetworkOrigin`、`SnaplockType` |
| ファイルパス・コマンド | `docs/ja/architecture.md`、`make all`、`aws fsx create-and-attach-s3-access-point` |
| アンカー ID・バッジ URL | `#はじめる`、`https://img.shields.io/...` |
| プロトコル名 | NFS、SMB、S3 API、POSIX |

`Origin` と `Cache` は、FlexCache の役割を指す語として英語のまま使います。
「元ボリューム」「キャッシュボリューム」と訳し分けると、同じものを指す語が増えます。

## 訳語の対応

| 日本語 | English | 補足 |
|---|---|---|
| 収集層 | collect layer | S3 API で書き込みを受ける側 |
| 配布層 | serve layer | FlexCache でファンアウトする側 |
| 正本データ | source of truth | データ側。書き込み先として管理するボリューム。保証の含意を持たせない |
| 正典 | authoritative version | 文書の版。データ側には使わない（かつて両方に使っていて混同を招いた） |
| ファンアウト | fan-out | 1 つの Origin から複数の Cache へ配ること |
| 利用拠点 | consuming site | 読み取り側の物理的な場所 |
| 検証済み | verified | 実環境で再現した |
| ドキュメント記載 | documented | 記載はあるが実機では確かめていない |
| 未検証 | unverified | 確かめていない |
| 未確認 | unconfirmed | 公開ドキュメントに記載を見つけられていない。「できない」ではない |
| 実測 | measured | 環境の併記が必須 |
| 未計測 | not measured | 数値を書かない |
| 適用外条件 | exclusion conditions | 向かない条件 |
| 出典 | source | URL または文書名 |
| 分岐 | divergence | コピー元から変えた点 |
| 不可逆操作 | irreversible operation | 取り消せない操作 |
| 二層認可 | dual-layer authorization | AWS 側と ONTAP 側の両方 |
| セキュリティスタイル | security style | UNIX / NTFS（mixed は非推奨） |
| 削除順序 | teardown order | Cache → SVM ピア → クラスタピア |

## 段階の語を弱めない

`unverified` を `not yet supported` と訳したり、`unconfirmed` を `unsupported` と訳したりすると、
主張の強さが変わります。段階の語は上の表のまま 1 対 1 で対応させてください。

同じ理由で、未検証の事項に `will`、`does`、`supports` のような断定形を使いません。
`is documented as`、`has not been verified in this repository` のように、
何を確かめていないかが読み取れる形にします。

## 英語版に日本語が残る場合

意図的に残す日本語（法令名の原文併記、言語スイッチャー、日本語版への明示的なリンク）は
`tools/check_en_doc_language.py` の許可リストに理由付きで登録します。

日本語ドキュメントへのアンカーは `ALLOWED_ANCHORS` に個別に列挙します。
これは負債であって例外ではありません。1 件ずつ列挙してあるので、新しく増やすと検査が落ちます。
落ちたときの正しい対応は、リストを伸ばすことではなく英語版を書くことです。

## 権威の宣言

Tier 1 の各文書は、どちらの版が正典かを対称に述べます。

- 日本語版は、技術的な正確さについて自分が正典であると述べる
- 他言語版は、日本語版が正典であり、食い違いは報告してほしいと述べる

これは見出しではなく本文の段落にします。節構成のパリティ（`make i18n-check`）に影響しないためです。

この記載があるのは、翻訳が機械支援で作られ、公開前にネイティブレビューを経ていないからです。
その記述に基づいて行動するかを決める読者には、知る権利があります。
運用は「公開して、報告を受けて直す」です。ネイティブレビューを待つと日本語以外が何も出ないため、
制約を明示し、報告経路を 1 クリックに置き、翻訳の誤りを通常の修正として扱います。
