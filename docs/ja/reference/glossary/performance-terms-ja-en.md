# 性能の話で使う語の日英対訳

性能の記録は日本語と英語の両方で書く。**同じものを指す語が言語をまたいでずれると、数値だけが
コピーされて前提が落ちる。** この表はその防止のためにある。

対象は「上限の種別」と「測定条件」に関わる語に絞ってある。ここがずれると比較が成立しない。

## 上限の種別

**この 3 つは性質が違う。訳語を混ぜない。**

| 日本語 | English | 指しているもの |
|---|---|---|
| 購入した指定値 / 購入した上限 | purchased tier / purchased ceiling | ファイルシステム作成時に選ぶ throughput capacity。共有され、読み手を増やしても増えない |
| throughput capacity | throughput capacity（訳さない） | AWS の設定項目名。日本語でもそのまま使う |
| 弾性の上限 | elastic limit | 購入しない上限。クライアントを増やした分だけ伸びる |
| ローカルプロキシの CPU 上限 | local proxy CPU limit | 同一ホストのプロセス（`efs-proxy` など）が先に飽和する形 |
| ディスクスループット | disk throughput | SSD 側から来る上限。SSD IOPS のプロビジョニング量で動く |
| HA ペアあたりの上限 | per-HA-pair limit | 書き込みと読み取りで別の値を持つ |
| 既定水準 | default level | 既定でその水準が提供されるという意味。**天井ではない** |
| 天井 | ceiling / hard limit | それ以上動かない値。既定水準と区別する |

> **「既定水準」と「天井」を訳し分ける理由。** 768 MBps/TiB を ceiling と訳すと、SSD IOPS を
> プロビジョニングすれば動くという事実が消える。default level と訳す。

## 測定条件

**数値に併記する項目。欠けると再現できない。**

| 日本語 | English | 備考 |
|---|---|---|
| 実測 / 実測値 | measured | 「ドキュメント記載」と区別する |
| ドキュメント記載 | documented | 実機で確かめていない |
| 未測定 | unmeasured | 測っていない。**cannot と訳さない** |
| 未検証 | unverified | 記載はあるが実機で追っていない |
| 未確認 | unconfirmed | 公開ドキュメントに記載を見つけられていない |
| 該当なし（機構が無い） | not applicable (no such mechanism) | **unmeasured と区別する** |
| 指定値 | tier | ファイルシステムに指定した throughput capacity の値。**「段」と書かない**（この文書での造語だった。一般的な日本語の技術用語ではない） |
| 並列度 | concurrency | ストリーム数と区別する場合は stream count |
| マウント実効オプション | effective mount options | 指定値ではなく実際に効いている値 |
| 非圧縮データ | incompressible data | `/dev/urandom` 由来 |
| ゼロ埋め | zero-fill | `/dev/zero` 由来。ディスクに行かない |
| インライン効率化 | inline efficiency | 圧縮と重複排除 |
| 再現性 | repeatability | 同一条件を繰り返したときのばらつき |
| 基準線 | baseline | 再現性の基準。バーストの baseline と紛れるので文脈を添える |

> **「未測定」を cannot と訳さない。** 段階の定義は[検証状況](../../verification-status.md)にある。
> unmeasured / unverified / unconfirmed / not applicable は別の意味を持つ。

## 機構の名前

| 日本語 | English | 備考 |
|---|---|---|
| Amazon S3 Files | Amazon S3 Files | 初出のみフルネーム、以降 S3 Files |
| FSx for ONTAP S3 Access Point | FSx for ONTAP S3 Access Point | 略すときは S3 AP。単独の製品名略記は使わない <!-- allow:naming - 禁止形そのものを説明している行 --> |
| FlexCache | FlexCache | 訳さない |
| Origin ボリューム | origin volume | 正本側 |
| Cache ボリューム | cache volume | 読み取り側 |
| バッチング窓 | batching window | ファイルからバケットへの反映をまとめる時間窓 |
| 高性能ストレージ | high-performance storage | S3 Files 側の低遅延層 |
| 正本 | source of truth | 「マスター」とは書かない |
| 反映 | visibility / propagation | 片方に書いたものが他方から見えること |
| プロビジョンド IOPS | provisioned IOPS | `USER_PROVISIONED` の設定値 |
| 観測の境界 | observability boundary | どのツールでどこまで見えるか |
| セキュリティスタイル | security style | UNIX / NTFS |

## 表記の統一

- **本構成** → this architecture。「弊社の」「我々の」に相当する語を英語側でも使わない
- 「どちらが速いか」に相当する見出し・結論を両言語で置かない
- 数値を横に並べるときは、両言語で**上限の種別を同じ視界に置く**
- 大きなミリ秒値は、両言語で概算を併記する（`63,769 ms`／about 64 seconds）

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [検証状況](../../verification-status.md) | 段階の定義（検証済み / ドキュメント記載 / 未検証 / 未確認） |
| [用語の整理](object-access-on-ontap.md) | 「ファイルを S3 で見せる」機能の呼び名 |
| [スループット実測](../../verification/throughput-iops-concurrency.md) | 上限の種別が実測でどう出たか |
| [S3 Files との比較](../../verification/s3files-vs-flexcache.md) | 設計点の違いと選び方 |
