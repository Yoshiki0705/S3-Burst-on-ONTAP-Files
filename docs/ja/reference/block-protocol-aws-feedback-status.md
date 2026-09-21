# ブロックプロトコル関連記事の AWS フィードバック状況

<!-- lang-switcher:start -->
🌐 [日本語](block-protocol-aws-feedback-status.md) | [English](../../en/reference/block-protocol-aws-feedback-status.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->

ブロックプロトコルの実測 3 本と S3 Burst Part 2 で、公開ドキュメントの記述に触れた箇所を
1 か所にまとめる。**各記事の「AWS へのフィードバックの状況」節が個別の記事に対する状態を
持ち、この文書はそれを記事横断で見るための索引である。** 個別の経緯・逐語引用・再現手順は
各記事側にあり、ここでは重複させない。

**ケース番号は書かない。** 内部台帳（gitignore 配下）にのみ記録する。ここに書くのは
内容・種別・状態の 3 つ。

## 提出済み（7 件）

| 記事 | 指摘 | 種別 | 状態（2026-09-21 確認） |
|---|---|---|---|
| A | `JunctionPath` の本文と `Required:` 欄が食い違う（[API リファレンス](https://docs.aws.amazon.com/fsx/latest/APIReference/API_CreateOntapVolumeConfiguration.html)、CloudFormation・CDK に伝播） | 記述の自己矛盾 | 調査中。AWS から一次回答のみ |
| B | 「パッケージの導入以外は他の EC2 Linux AMI でも有効」に対し `cat /etc/nvme/hostnqn` が AL2023 でファイル不在 | 記述の範囲外の反例 | AWS が観測を確認し、ドキュメントフィードバックとして提出したとの回答。修正時期は未定 |
| B | 同じ記述に対し `cat /sys/module/nvme_core/parameters/multipath` が AL2023 でファイル不在（`CONFIG_NVME_MULTIPATH` 未設定） | 記述の範囲外の反例 | AWS が観測を確認し提出。付随する確認質問（対象ディストリビューションの確認）は解消済み |
| B | 手順の `iopolicy` 確認値（`round-robin`）と実測（`queue-depth`）の不一致。版の境界は `nvme-cli` 2.11→2.12 | 版のずれ（記述の誤りではない） | AWS が版差が原因という理解に同意。社内担当部署へ確認の上で状況連絡の約束 |
| Part 2 | 第二世代の持続書き込みが、指定値に当てるべき公表値を 2 点とも超える | 公表値と実測の乖離 | 返信なし |
| Part 2 | ap-northeast-1 の NVMe リードキャッシュ容量が表に無く、管理ページも second-generation 限定で書かれている | 記載の欠落（2 か所） | 返信なし |

## 提出しない（3 件）

| 記事 | 指摘 | 提出しない理由 |
|---|---|---|
| A | 5 Gbps（約 625 MBps）を除数にしたセッション数の見積りが実測と合わない | AWS は式を示していない。割り算は記事の筆者が立てた見積り方であり、ドキュメントへの指摘ではない |
| Part 2 | SSD IOPS を上げて読み取りが 7.14 倍になった観測が「SSD IOPS はキャッシュに無いデータを読むときだけ使う」と噛み合わない | 測り直して決着した。作業セットをキャッシュの 2.15 倍にすると記述と噛み合う（倍率は 4.86 倍。7.14 倍は再現しない）。ドキュメントの誤りではなく測定不備だった |
| C | `nvmf_lif` カウンタテーブルが 600 GiB 書いた後も 0 行を返す | ONTAP 側の挙動で AWS ドキュメントの話ではない。ベンダー（NetApp）確認事項 |

**C にはこれ以外の指摘は無い。** 自分の測り方の誤りと、公開仕様の範囲では説明できない実測が
書いてあるだけで、いずれもドキュメントが誤っているという主張ではない。

## 記事ごとの内訳

| 記事 | 提出済み | 提出しない | 指摘なし |
|---|---|---|---|
| A: セッション数とキュー数 | 1 件 | 1 件 | — |
| B: ANA が使えるかの確認 | 3 件 | — | — |
| C: 数値は何で動くか | — | 1 件 | ○ |
| S3 Burst Part 2 | 2 件 | 1 件 | — |

## 反映の規律

**提出は公開ではない。** ドキュメントが直ったことを自分で確認するまで、記事側に「反映済み」
とは書かない。反映を確認したら記事側に日付を添えて追記する。**この索引は各記事の状態を
写すだけで、状態の一次情報は記事側にある。** 索引だけを更新して記事側を古いままにしない。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [ブロックプロトコルを測るときの考慮点](block-protocol-testing-guide.md) | 測る前に踏む落とし穴 |
| [プロトコル別測定の結果](../verification/perf-matrix-results.md) | 実測記録 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |

<!-- lang-switcher:start -->
🌐 [日本語](block-protocol-aws-feedback-status.md) | [English](../../en/reference/block-protocol-aws-feedback-status.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
