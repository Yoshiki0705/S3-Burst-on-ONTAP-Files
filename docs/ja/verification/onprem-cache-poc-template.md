# 主経路 PoC テンプレート — Origin を FSx for ONTAP、Cache をオンプレミス ONTAP にした場合

このリポジトリの中核で唯一まだ実機検証していない経路（[検証状況](../verification-status.md)の
「中核の検証範囲」）を、自分の環境で確かめるための手順と合否条件のテンプレートである。
**実測値はここに書かない。結果欄は空のまま置き、自分で埋める。**

対象読者は、[PoC チェックリスト](../poc-checklist.md)の「2. FSx for ONTAP Origin からオンプレミス
ONTAP Cache への FlexCache」に着手する人。このページはその項目の**測定手順の詳細**であり、
チェックリスト自体を置き換えない。

## 使う計測スクリプト

**新規のスクリプトは書かない。** [`scripts/measure_visibility.py`](../../../scripts/measure_visibility.py)
は Cache 側の NFS LIF とジャンクションパスを引数で受け取るだけで、Cache が FSx for ONTAP か
オンプレミス ONTAP かを区別しない。**この経路の計測は、既存スクリプトに拠点側の値を渡すだけで足りる。**

```bash
python3 scripts/measure_visibility.py \
  --s3ap-alias <S3_AP_ALIAS_OR_ARN> \
  --nfs-lif <拠点側 SVM の data LIF IP> \
  --fc-path <拠点側 Cache ボリュームのジャンクションパス> \
  --origin-path <Origin ボリュームのジャンクションパス> \
  --iterations 30 \
  --region ap-northeast-1 \
  --output docs/ja/verification/onprem-cache-poc-result.json
```

SMB も測る場合は `--smb-share` / `--smb-user` / `--smb-cred-secret` を足す
（パスワードはコマンドライン引数に取らない。スクリプトの docstring 参照）。

**環境条件は JSON 出力に残らないので、別途記録する。**
[`onprem-cache-poc-environment.example.yaml`](onprem-cache-poc-environment.example.yaml) を
コピーし、計測前に埋めてから計測する。**この雛形は今回の PoC 記録から新規に使う形式で、
既存の実測記録（本文インライン記述）を置き換えるものではない。**

## 環境の前提

計測前に [poc-checklist.md フェーズ 2 の前提](../poc-checklist.md#2-fsx-for-ontap-origin-からオンプレミス-ontap-cache-への-flexcache)
をすべて満たす。特に次の 3 点は計測を無効にする既定値になりうる。

| 前提 | 未確認のまま進めた場合の失敗の見え方 |
|---|---|
| クラスタ / SVM ピアリングが確立済み | FlexCache 作成が `Unable to communicate` で失敗する |
| Cache ボリュームが FlexGroup として作成可能 | ボリューム作成そのものが失敗する |
| 経路の往復遅延を事前に測定済み | 結果を解釈する基準（サブミリ秒の測定との比較）が無い |

## 合否条件テンプレート（測定前に埋める）

**[poc-checklist.md の「測定前の合否基準の決定」](../poc-checklist.md#測定前の合否基準の決定)に
従い、計測を始める前に次の表を埋める。** 埋まらない欄があれば計測に進まない。

| 決めること | この経路での書き方（例） | 自分の記入 |
|---|---|---|
| 何を測るか | `PutObject` の応答から Cache 側の NFS で `open` が成功するまでの p50（Dir 1: `s3ap_to_fc_nfs`） | |
| 合格の線 | ワークロードから引いた閾値と根拠 | |
| 不合格のときの次の手 | 打つ手、打てないなら誰が判断するか | |
| 比較の基準 | 代役測定（東京 origin・大阪 cache、往復 9.7 ms、[実測](throughput-iops-concurrency.md#リージョンを跨いだ-flexcache読み手が遠い場合)）とこの経路の往復遅延の差 | |

## 結果欄（未実施）

| 方向 | p50 | p90 | p99 | n | 計測日 | 環境 |
|---|---|---|---|---|---|---|
| Dir 1: S3 AP → Cache NFS | 未実施 | 未実施 | 未実施 | — | — | — |
| Dir 3: Origin NFS 書き → Cache NFS 読み | 未実施 | 未実施 | 未実施 | — | — | — |
| Dir 5: S3 AP → Cache SMB（測る場合） | 未実施 | 未実施 | 未実施 | — | — | — |

**環境**列には、計測日・リージョン・拠点側 ONTAP バージョン・経路の往復遅延・オブジェクトサイズ・
`actimeo` の設定を記録する（[数値を書くとき](../../../CONTRIBUTING.md#数値を書くとき)）。

結果が出たら、[検証状況](../verification-status.md)の「中核の検証範囲」表と
[PoC チェックリスト](../poc-checklist.md)のチェック項目を同じコミットで更新する。
段階が動く（未検証 → 検証済み）場合は [CHANGELOG.md](../../../CHANGELOG.md) にも記録する
（[段階を書くとき](../../../CONTRIBUTING.md#段階を書くとき)）。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [PoC チェックリスト](../poc-checklist.md) | この計測が属するフェーズ全体の手順 |
| [自分の環境で再現するときの手引き](reproduction-guide.md) | 環境の作り方（V-7 / V-8） |
| [検証状況](../verification-status.md) | 現在の段階と、この経路の未検証範囲 |
