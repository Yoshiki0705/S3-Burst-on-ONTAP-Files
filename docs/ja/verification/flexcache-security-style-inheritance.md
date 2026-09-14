# 検証記録 — FlexCache の Cache ボリュームは Origin のセキュリティスタイルを継承するか

**このリポジトリが読者に「Origin ボリュームを作る前に決めてください」と言ってきた項目の、根拠を
差し替えた記録です。** それまでの根拠は Azure NetApp Files のキャッシュボリューム要件、つまり
**別プラットフォームの要件**でした。この構成で同じ規則が成り立つかは確かめていませんでした。

実測の結論は 3 つです。**継承は起きます。作成時に指定する手段はありません。作成後に変更できません。**
したがって「Origin を作る前に決める」は助言ではなく、**あとから直す経路が無いという事実**です。

## 検証環境

| 項目 | 値 |
|---|---|
| 計測日 | 2026-09-13（UTC） |
| リージョン | ap-northeast-1 |
| Origin クラスタ | FSx for ONTAP（`fs-0123456789abcdef0`）、SINGLE_AZ_1、128 MBps、SSD 1,024 GiB |
| Cache クラスタ | FSx for ONTAP（`fs-0abcdef1234567890`）、SINGLE_AZ_1、128 MBps、SSD 1,024 GiB |
| **ONTAP バージョン** | **NetApp Release 9.18.1P6**（両クラスタ同一） |
| 接続 | **同一 VPC・同一サブネット。VPC ピアリングは作っていない** |
| ピアリング | クラスタピア（インタークラスタ LIF 間、TCP 11104-11105）、SVM ピア（`applications: flexcache`） |
| Origin ボリューム | `origin_unix`（UNIX、10 GiB）と `origin_ntfs`（NTFS、10 GiB）、同一 SVM |
| Cache ボリューム | `fc_unix` / `fc_ntfs`、いずれも 50 GiB、`use_tiered_aggregate: true` |
| 操作経路 | ONTAP REST API（`curl` + Basic 認証）。SSM のポートフォワードで管理 LIF に到達 |

**同一サブネットに 2 台置いたのは、この問いに経路の距離が関係しないからです。** ピアリングの
有無で継承の挙動が変わるという想定は置いていませんが、**確かめてもいません。**

## 測定結果

**この測定の要点は対照です。** Cache SVM の既定のセキュリティスタイルが UNIX なので、
**UNIX の Origin だけを見ても「継承した」と「既定のままだった」を区別できません。**

| # | 何を作ったか | セキュリティスタイルの指定 | 結果 | UNIX パーミッション |
|---|---|---|---|---|
| 0 | **対照** — Cache SVM 上の通常ボリューム `ctl_default` | **指定なし** | `unix` | 755 |
| 1 | `origin_unix`（Origin） | UNIX を指定 | `unix` | 755 |
| 2 | `fc_unix` — 1 の FlexCache | **指定なし** | `unix` | 755 |
| 3 | `origin_ntfs`（Origin） | NTFS を指定 | `ntfs` | — |
| 4 | `fc_ntfs` — 3 の FlexCache | **指定なし** | **`ntfs`** | 0 |

**判別したのは 4 です。** Cache SVM の既定は 0 が示すとおり `unix` であり、それでも 4 は `ntfs` に
なりました。**値は Origin から来ています。** 2 だけを見ていれば、既定と一致した結果を継承の
証拠として読むところでした。

### 指定と変更の可否

| 試したこと | 結果 |
|---|---|
| FlexCache 作成時に `nas.security_style` を渡す | **REST が引数自体を拒否**（`Unexpected argument "nas".`, code 262179） |
| 作成後に Cache ボリュームのスタイルを `unix` へ変更 | **ONTAP が拒否**（`Modification of the following fields is not allowed for FlexCache volumes: security-style.`, code 66846758） |

**変更を拒否したときの応答は成功に見えます。** PATCH は job UUID を返し、HTTP の層では成功します。
拒否は job の `state` が `failure` になる形で出るので、**値を読み直すまでは効かなかったことが
分かりません。** 実際に PATCH 直後のボリュームは `ntfs` のままでした。

## 読み取れること

- **セキュリティスタイルは Origin から Cache へ継承される**（この構成、この版で）。
  UNIX パーミッションも 1 と 2 で一致しました
- **Cache 側で選び直す経路が無い。** 作成時に渡せず、作成後に変えられない
- したがって[最初に決めること](../design-first-decisions.md)の位置づけは変わりません。
  **根拠が別プラットフォームの要件から、この構成の実測に変わっただけです**

## 読み取れないこと

- **Cache がオンプレミス ONTAP の場合は未検証です。** この測定は両側 FSx for ONTAP です
- **NTFS の Cache に実際に SMB でアクセスできるかは測っていません。** CIFS サーバを作って
  いないため、確かめたのはボリュームの属性だけです。**なお CIFS サーバが無くても
  NTFS スタイルのボリューム自体は作成できました**
- **`mixed` は試していません**
- **セキュリティスタイルとファンアウト先プロトコルの対応**（UNIX なら NFS、NTFS なら SMB）は
  この測定の対象外です。継承の有無だけを見ています
- **ONTAP CLI で同じ制約になるかは確認していません。** 上の 2 つの拒否は REST での応答です

## この手順で踏んだ罠

**いずれも既存の手順書に書かれていなかったものです。**

| # | 症状 | 原因と回避 |
|---|---|---|
| 1 | FlexCache 作成が「5GB では小さすぎる」で失敗 | **この種類のボリュームは最低 50 GB**（`Volumes of this type must be at least 50GB`）。`patterns/collect/s3ap-flexcache-verify/` の手順は `-size 5g` と書いていた。**ただし 9.18.1P3D1 でも失敗したかは試していない** — 直したのは「動くと分かっている値」に揃えるためで、旧記述が必ず失敗すると確かめたわけではない |
| 2 | `Aggregates not matching FabricPool requirements: aggr1` | **FSx for ONTAP の aggregate は FabricPool 有効なので、`use_tiered_aggregate: true` が要る。** 既定は false |
| 3 | Cache ボリュームが `volume delete` で消えない | **FlexCache は専用エンドポイント**（`/storage/flexcache/flexcaches/{uuid}`）から削除する。しかも**先に unmount して offline にしておく必要がある** |
| 4 | Cache を消したのに Origin が「まだ Cache がある」と言って消えない | **Cache を解放する前に Origin を offline にしたため、Cache 削除時の Origin 側 cleanup が失敗した。** `flexcache_endpoint_type` が `origin` のまま残る。**Cache が既に無いので `cleanup-cache` も打てない**（`entry doesn't exist`）。Origin を online に戻し、Cache を作り直して正しい順序で解放すると `none` に戻った |
| 5 | スタック削除が `DELETE_FAILED`。`svmLifecycle should be DELETING, but get: MISCONFIGURED` | **SVM ピア関係が残っていると FSx for ONTAP は SVM を削除しない。** その理由文は ONTAP CLI の `vserver peer delete` を案内する。**つまり ONTAP に入れる足が要る** |
| 6 | その足が無い | **同じスタック削除が検証ホストを先に消す。** 管理 LIF はプライベートアドレスなので、ホストが無くなると REST にも CLI にも到達できない。**SVM ピアを消す前にホストが消える順序になっている** |
| 7 | ピアを消しても FSx for ONTAP の `Lifecycle` が `MISCONFIGURED` のまま | **CloudFormation は削除を呼ぶ前にこの値を見て断る。** 一方 **`aws fsx delete-storage-virtual-machine` は同じ状態でも受け付け、`DELETING` に入った。** API を直接呼んでからスタック削除を再試行すると通る |
| 8 | ホスト用セキュリティグループが「依存オブジェクトがある」で消えない | **こちらが手で足した ingress ルールが原因。** 相手のセキュリティグループを参照するルールを別スタック側に作ると、参照されている側が消せない。**手で足したルールは手で消す** |

**4 が撤去順序の実務的な意味です。** 「Origin より先に Cache を消す」だけでは足りず、
**Origin に触るのは Cache の解放が終わったあと**です。

**5〜7 は順序の問題で、`environments/aws-origin/` を 2 つ使う構成すべてに効きます。**
**スタックを消す前に、ホストが生きている状態で SVM ピアとクラスタピアを消してください。**
順序を間違えた場合の復旧は、ONTAP へ到達できるホストを立て直し、ピアを消し、
**FSx for ONTAP の API で SVM を直接削除してからスタック削除を再試行する**ことです。
この run では復旧のためだけに t3.micro を 1 台立て直しています。

> **FSx for ONTAP の API 経由で消したボリュームだけが最終バックアップを残しました。** ONTAP REST で消した
> 4 本（`fc_unix` / `fc_ntfs` / `ctl_default` / `origin_ntfs`）にはバックアップができておらず、
> CloudFormation が消した 2 本にはできていました。**撤去後は必ず
> `aws fsx describe-backups` で数えること** — この run では 2 件を削除しました。

## 再現手順

1. `environments/aws-origin/` を 2 回デプロイする（同一サブネットで足りる）。Cache 側は
   検証ホスト不要
2. 双方のファイルシステムのセキュリティグループに、相手のセキュリティグループからの
   TCP 11104-11105 を許可する
3. クラスタピアを両側から同じパスフレーズで作り、`status.state` が `available` になるまで待つ
4. SVM ピアを作り、相手側で `state` を `peered` にする
5. **セキュリティスタイルを指定せずに** FlexCache を作る（`use_tiered_aggregate: true`、50 GiB 以上）
6. **対照を取る** — Cache SVM 上に通常ボリュームをスタイル指定なしで作り、既定値を読む
7. NTFS の Origin ボリュームを足し、その FlexCache を作って読む
8. 撤去は上の罠 3 と 4 の順序で行い、**ボリューム削除で作られる最終バックアップを消す**

## 関連ドキュメント

- [最初に決めること](../design-first-decisions.md) — この結果が根拠になっている判断
- [検証状況](../verification-status.md) — 段階の一覧
- [S3 Access Point 経由の書き込みの可視化](flexcache-s3ap-visibility.md) — 同じ 2 クラスタ構成での別の測定
- [ブロック測定の実行手順](block-measurement-runbook.md) — 罠を先に読む形式の先例
