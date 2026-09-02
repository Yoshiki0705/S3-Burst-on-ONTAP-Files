# PoC チェックリスト
<!-- lang-switcher:start -->
🌐 [日本語](poc-checklist.md) | [English](../en/poc-checklist.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->

<!-- 出典と分岐の記録
     姉妹リポジトリ FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns の docs/flexcache-poc-checklist.md を
     出発点にしている。
     https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/flexcache-poc-checklist.md

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

## 測定前の合否基準の決定

**測ったあとに合否を決めると、出た数値が合格になる。** 各フェーズを始める前に次の 3 つを書き、
測定結果と一緒に残す。埋まらない欄があるなら、そのフェーズはまだ始められない。

| 決めること | 書き方 | 空欄のままだとどうなるか |
|---|---|---|
| 何を測るか | 1 つの数値または真偽。「速いか」ではなく「`PutObject` の応答から Cache 側の NFS で `open` が成功するまでの p50」 | 測定のたびに定義が動き、比較できない |
| 合格の線 | ワークロードから引いた閾値と、その根拠。「1 回の再生に 200 ファイル読むので、1 ファイルあたり 50 ms を超えると準備が 10 秒を超えて許容できない」 | 出た数値を合格と読む |
| 不合格のときの次の手 | 打つ手と、打てないなら誰が判断するか | 不合格が「もう一度測る」に化ける |

**このリポジトリの数値を自分の合格線にしない。** フェーズ 1 の p50 8 ms は同一リージョン・
VPC ピアリング・サブミリ秒のネットワーク遅延で測ったもので、拠点までの経路が入る構成では
別の値になる（[検証状況](verification-status.md)）。参照値として使うなら、
自分の環境で同じ手順を踏んで自分の数値を出したうえで比べる。

**測れなかったことも結果である。** ピアリングが張れずフェーズ 2 に入れなかった、
という記録は「未検証」より強い情報で、次に同じ経路を試す人の時間を節約する。

## 1. S3 Access Point で書いたものの Cache 側での読み取り可否

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
- [x] `UploadPartCopy` を**同一アクセスポイント内のソース**で試す →
      **`NoSuchKey`**（[検証記録](verification/s3ap-operations.md)、2026-08-19）。同一の `CopySource` を
      与えた `CopyObject` は同一実行内で成功しており対照が取れている。公式は同一 AP 内で対応と記載
- [ ] 標準 S3 バケットをソースにした `UploadPartCopy` を試す。**このエンドポイントでコピーが成立する
      別のソース名前空間が無いため、`UploadPartCopy` そのものの対応可否は未判定のまま**

記録先は[検証状況](verification-status.md)の表。数値を書くときは環境を必ず併記する。

## 2. FSx for ONTAP Origin からオンプレミス ONTAP Cache への FlexCache

必要な環境: オンプレミス ONTAP とのピアリング。
主経路であり、AWS は対応構成として明記しているが実機では確かめていない。

**ピアリングの経路はこのリポジトリの範囲外である。** Terraform も CloudFormation も
クラスタ / SVM ピアを作らない。FlexCache の作成が失敗する最も多い原因がこれなので、
下の前提を先に潰す（[オンプレミス側のデプロイ](deployment/onprem-terraform.md)）。

前提（ピアを張る前に確認する）

- [ ] オンプレミス ONTAP のバージョンを確認する（FlexCache は ONTAP 9.5 以降、
      write-back は 9.15.1 以降。[サポート状況](support-matrix.md)）
- [ ] 両クラスタにインタークラスタ LIF があり、相互に到達できることを確認する
- [ ] 経路上で必要なポートが開いていることを確認する（ONTAP のクラスタピアリングが使うポート。
      AWS 側のセキュリティグループと、拠点側のファイアウォールの両方）
- [ ] 経路の MTU を確認する。Direct Connect / VPN の経路で MTU が揃っていないと
      大きい読み取りで詰まる
- [ ] 経路が別クラウドを経由する場合、その区間が private につながることを先に確認する。
      **可否の決まり方が 2 通りある**（管理サービスなら対応リージョンのペア、パートナー経由なら
      ロケーションの重なり。[他クラウドとの接続経路](multi-cloud-connectivity.md)）
- [ ] 管理サービス（AWS Interconnect – multicloud など）を使う場合、**そのペアのライフサイクルを
      確認する。** ペアが表にあることと GA であることは別で、Preview のペアは対応リージョンも機能も
      変更されうる。PoC で Preview を使うのは構わないが、**本番の設計根拠に持ち越さない**
- [ ] 経路の往復遅延を先に測る（`ping` などで 1 度。**フェーズ 1 の数値と比べる基準になる**。
      サブミリ秒で測った値との差はここで説明できる）
- [ ] Cache 側のボリュームを FlexGroup として作れることを確認する（Cache は FlexGroup である）

手順

- [ ] クラスタピアと SVM ピアを確立する
- [ ] Cache ボリュームを作成する
- [ ] Origin のセキュリティスタイルが Cache に継承されるかを確認する
      （[最初に決めること](design-first-decisions.md)の未確認事項）
- [ ] UNIX + NFS、NTFS + SMB のそれぞれで確認する（mixed は非推奨のため検証対象外）
- [ ] 実際に読まれた範囲だけが転送されることを確認する
- [ ] **フェーズ 1 と同じ測定を、この経路で繰り返す。** 同じスクリプト・同じオブジェクトサイズ・
      同じ `actimeo` で測る。条件を変えると、差が経路によるものか設定によるものか分からない
- [ ] 2 回目の読み取りが速くなること（Cache に載ったこと）と、その差を記録する
- [ ] 削除順序を確認する（Cache → SVM ピア → クラスタピアの順で解除できるか）。
      **Cache が残っている状態で Origin 側を消さない**

> **この節は FSx for ONTAP → FSx for ONTAP で一度通してあります。** 経路が
> オンプレミスかどうかで変わらない部分は、そこで判明した点をそのまま使ってください
> （[実測記録](verification/throughput-iops-concurrency.md#flexcache-経由の読み取り)、
> [手順上の罠](deployment/onprem-terraform.md#ピアリングと-flexcache-作成で実際に踏んだ-5-点)）。
> リージョンを跨いだ場合に追加で踏む 3 点も同じページにあります。
>
> **削除順序については、上のチェック項目より前に 1 段あります。** FlexCache ボリュームは汎用の
> volume 削除では拒否され（`Use the volume flexcache delete command`）、それが済むまで SVM ピア
> 削除が無言でブロックされ、結果としてクラスタピア削除も進みません。**「SVM ピアが消えない」と
> いう症状で現れるので、原因が FlexCache 側にあると気づきにくい**ところです。

## 3. ファンアウト数を増やしたときの挙動

必要な環境: FSx for ONTAP 複数台。ファンアウト数の設計指針に関わる。

- [ ] Cache を段階的に増やす
- [ ] AWS ドキュメントが write-around を推奨する境界（Origin ボリュームが 10 を超える場合）の
      前後で挙動が変わるかを確認する
- [ ] Origin 側の負荷を記録する

## 4. 他プラットフォームの Cache としての利用可否

必要な環境: 別クラウドの費用が発生する。移植性の表の「未確認」を埋めるための項目。

- [ ] Cloud Volumes ONTAP を Cache にできるか
- [ ] ONTAP Select を Cache にできるか
- [ ] Azure NetApp Files のキャッシュボリュームが FSx for ONTAP を Origin にできるか
- [ ] Google Cloud NetApp Volumes を Cache にできるか

**逆方向は別の項目である。** 上の 4 つはいずれも Origin が FSx for ONTAP の場合で、他クラウドの
ファイルストレージを Origin にする方向は対応構成表の外にある（[移植性](portability.md)）。

- [ ] 相手側がクラスタピアリングを外部に提供しているかを先に確認する。**提供していなければ
      FlexCache の可否を測る前に止まる**ので、ここが最初の分岐になる
- [ ] Google Cloud NetApp Volumes を Origin として FSx for ONTAP を Cache にできるか
- [ ] Azure NetApp Files を Origin として FSx for ONTAP を Cache にできるか

**ONTAP でないファイルストレージはこのフェーズの対象外である。** Google Cloud Filestore、
Azure Managed Lustre、Azure Blob NFS、OCI File Storage は機構として成り立たないため、測っても
埋まる「未確認」がない（[他クラウドとの接続経路](multi-cloud-connectivity.md)）。

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
| [他クラウドとの接続経路](multi-cloud-connectivity.md) | 別クラウドを経由する経路の前提 |

---

<!-- lang-switcher:start -->
🌐 [日本語](poc-checklist.md) | [English](../en/poc-checklist.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
