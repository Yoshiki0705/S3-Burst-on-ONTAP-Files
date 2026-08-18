# PoC チェックリスト
<!-- lang-switcher:start -->
🌐 [日本語](poc-checklist.md) | [English](../en/poc-checklist.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->

<!-- 出典と分岐の記録
     姉妹リポジトリ fsxn-s3ap-serverless-patterns の docs/flexcache-poc-checklist.md を
     出発点にしている。
     https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns/blob/main/docs/flexcache-poc-checklist.md

     分岐:
     1. 順序を「安い順」から「答えが出ないと設計が書けない順」に組み替えた。
     2. 収集層のみ / 配布層のみではなく、S3 Access Point で書いて NFS / SMB で読む
        end-to-end を第 1 フェーズに置いた。この構成の中核がそこにあるため。
     3. 元の版が未解決の問いとして挙げていた「Cache ボリュームに S3 Access Point を
        接続できるか」を落とした。この構成は Cache 側にオブジェクトアクセスを出さないため、
        確かめる必要がない。
     4. 成功基準を空欄のテンプレートではなく、各項目の「答えが出ないと書けないもの」として
        書いた。空欄の KPI 表は埋められないまま残るため。
-->

順序は費用ではなく、**答えが出ないと設計が書けない順**である。
1 を飛ばして 4 や 5 に進まない。

各項目の段階は[検証状況](verification-status.md)と対応している。

## 1. S3 Access Point で書いたものが Cache 側で読めるか

必要な環境: 既存の FSx for ONTAP 2 台、または FSx for ONTAP とオンプレミス ONTAP。
これが未解決だと、「収集した直後に現場で読めるのか」に答えられない。構成の中核である。

**FSx for ONTAP を 2 台使う形は検証済みで、下のチェック項目は済んでいる**
（[FlexCache 検証記録](verification/flexcache-s3ap-visibility.md)、NFSv3 / SMB、UNIX、64 B、
`actimeo=0`）。**自分の環境で、または Cache をオンプレミス ONTAP に置いて確かめる場合は
そのまま使える。** 残っている条件は[検証状況](verification-status.md)の「中核の検証範囲」にある。

- [ ] Origin ボリュームに S3 Access Point を接続する
- [ ] `PutObject` でオブジェクトを書く
- [ ] Cache 側の NFS / SMB マウントから同じファイルが見えることを確認する
- [ ] 書き込みから読めるようになるまでの所要時間を測る（計測日・リージョン・ONTAP バージョン・
      オブジェクトサイズ・キャッシュ設定を記録する）
- [ ] マルチパートアップロードの途中で Cache 側から見たときに何が見えるかを確認する
      （部分的なファイルが見えるか、`CompleteMultipartUpload` まで見えないか）
- [ ] Origin 側で削除したときに Cache 側での見え方がどうなるかを確認する
- [ ] 上書きしたときの反映を確認する
- [ ] `UploadPartCopy` を**同一アクセスポイント内のソース**で試す。公式は同一 AP 内・同一リージョンで
      対応としており、このリポジトリの観測（`404 NoSuchKey`）はソースが同一 AP 内にない条件のもの

記録先は[検証状況](verification-status.md)の表。数値を書くときは環境を必ず併記する。

## 2. FSx for ONTAP Origin からオンプレミス ONTAP Cache への FlexCache

必要な環境: オンプレミス ONTAP とのピアリング。
主経路であり、AWS は対応構成として明記しているが実機では確かめていない。

- [ ] クラスタピアと SVM ピアを確立する
- [ ] Cache ボリュームを作成する
- [ ] Origin のセキュリティスタイルが Cache に継承されるかを確認する
      （[最初に決めること](design-first-decisions.md)の未確認事項）
- [ ] UNIX + NFS、NTFS + SMB のそれぞれで確認する（mixed は非推奨のため検証対象外）
- [ ] 実際に読まれた範囲だけが転送されることを確認する
- [ ] 削除順序を確認する（Cache → SVM ピア → クラスタピアの順で解除できるか）

## 3. ファンアウト数を増やしたときの挙動

必要な環境: FSx for ONTAP 複数台。ファンアウト数の設計指針に関わる。

- [ ] Cache を段階的に増やす
- [ ] AWS ドキュメントが write-around を推奨する境界（Origin ボリュームが 10 を超える場合）の
      前後で挙動が変わるかを確認する
- [ ] Origin 側の負荷を記録する

## 4. 他プラットフォームを Cache にできるか

必要な環境: 別クラウドの費用が発生する。移植性の表の「未確認」を埋めるための項目。

- [ ] Cloud Volumes ONTAP を Cache にできるか
- [ ] ONTAP Select を Cache にできるか
- [ ] Azure NetApp Files のキャッシュボリュームが FSx for ONTAP を Origin にできるか
- [ ] Google Cloud NetApp Volumes を Cache にできるか

結果はいずれも[移植性](portability.md)の表に反映する。できなかった場合も記録する。

## 5. FlexCache duality

必要な環境: ONTAP 9.18.1。

この構成の前提ではない。S3 Access Point をボリュームに接続することとは**別の機構**なので、
これを検証しても収集層の根拠にはならない。後回しにする。

- [x] 何ができるかを確認する（この構成に取り込む前提ではなく、区別を保つための確認）。
      通常ボリュームの NAS バケットは動作し、FlexCache ボリュームでは
      `flexcache config modify -is-s3-enabled true`（advanced 権限）の設定後に
      `GetObject` / `ListObjectsV2` が成功した（[全方向比較](verification/cross-protocol-directions.md)）。
      **この結果は S3 Access Point の対応状況の根拠にはならない。別の機構である**

## 記録の作り方

- 環境情報（リージョン、ONTAP バージョン、ファイルシステムの世代と構成、スループット設定）を
  最初に書く
- 確認できたこと、確認できなかったこと、確認しなかったことを分けて書く
- 失敗した観察も残す。「動かなかった」は「未確認」より強い情報である
- 個人名・アカウント ID・内部 IP・サポートケース番号は書かない

## 不可逆操作について

PoC は不可逆操作を置く場所として最悪である。削除できない検証リソースは長期の請求になり、
同居する他のリソースも動かせなくする。

**SnapLock、改ざん防止 Snapshot、Object Lock のような「削除できなくする機能」は、
保持期間を明示した指示がない限り有効化しない。** 詳細は [AGENTS.md](../../AGENTS.md) の
不可逆操作の節にある。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [検証状況](verification-status.md) | 結果の記録先 |
| [最初に決めること](design-first-decisions.md) | フェーズ 2 で確かめる未確認事項 |
| [サポート状況](support-matrix.md) | 各項目の前提となる対応状況 |
| [移植性](portability.md) | フェーズ 4 の結果の反映先 |

---

<!-- lang-switcher:start -->
🌐 [日本語](poc-checklist.md) | [English](../en/poc-checklist.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
