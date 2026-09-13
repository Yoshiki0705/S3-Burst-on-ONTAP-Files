# ブロック測定の実行手順

<!-- LANG-SWITCHER-START -->
<!-- LANG-SWITCHER-END -->

iSCSI と NVMe/TCP を FSx for ONTAP の raw device に対して測るときの、**実行順序と、9 回失敗して
分かった罠**を置く。何を測るかは[ブロックプロトコルの測定計画](block-protocol-matrix-plan.md)、
出た数値は[プロトコル別測定の結果](perf-matrix-results.md#f-1-iscsi-の実測)にある。

**この文書はファイルプロトコル側の手順とは別にしてある。** 環境の作り方は
[測定環境](../../../environments/perf-matrix/README.md)と共通で、そこに足すと 1,000 行を超える。

## 先に読む — 止まらない課金

**ブロックだけを立てた状態で時間あたり約 $25.48。** ap-northeast-1 の On-Demand 単価から積んだ
見積りで、実際の請求ではない。内訳は[計画の費用節](block-protocol-matrix-plan.md#時間あたりの課金)にある。

> **この額の範囲を間違えないこと。** このリポジトリには時間あたりの数字が 3 つあり、**立てている
> ものが違う。**
>
> | 額 | 何を立てた状態か | 出典 |
> |---|---|---|
> | 約 **$25.48** | **ブロックのみ** — ファイルシステム 1 台 + Linux クライアント 1 台 | [計画](block-protocol-matrix-plan.md#時間あたりの課金) |
> | 約 **$37** | ファイル + EFS + AD + Windows + クライアント 9 台を全部立てた状態 | [測定環境](../../../environments/perf-matrix/README.md) |
> | 約 **$67** | 上に EFS Provisioned 1,024 MiBps を足した状態 | 同上 |

要点は 3 つである。

| 項目 | 既定値 | 止まるか |
|---|---|---|
| スループット容量 6,144 MBps | `GEN2_THROUGHPUT=6144` | **止まらない。** 削除するまで課金される |
| SSD 4,096 GiB | `GEN2_STORAGE_GIB=4096` | **止まらない。** プロビジョンした量で課金される |
| プロビジョンド SSD IOPS 200,000 | `GEN2_SSD_IOPS=200000` | **止まらない** |
| クライアント c5n.9xlarge 1 台 + c5n.2xlarge 8 台 | — | **停止すれば止まる** |

**ボリュームを削除するたびに最終バックアップが 1 つ作られる。** `SkipFinalBackup` は
`AWS::FSx::Volume` のプロパティではなく DeleteVolume API のパラメータなので、テンプレートから
止められない。**撤去後に `aws fsx describe-backups` で確認して消す。**

## 環境変数

`runbook.sh` はパラメータファイルではなく環境変数で駆動する。**ブロックに必要な最小集合はこれである。**

```bash
export AWS_REGION=ap-northeast-1
export VPC_ID=vpc-0123456789abcdef0
export SUBNET_ID=subnet-0123456789abcdef0     # クライアントとターゲットで同じサブネット
export NAME_PREFIX=perfmatrix                 # ^[a-z0-9-]{3,20}$
export STAGING_BUCKET=example-staging-bucket   # VDBENCH を置く場所。下の理由で必須
export FSXADMIN_SECRET_ARN=arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:fsxadmin-xxxxxx

export GEN2_BLOCK=true                        # 3260 / 4420 / 8009 とブロック用ボリュームを開ける
export GEN2_THROUGHPUT=6144                   # 1536 | 3072 | 6144（SINGLE_AZ_2 が受ける値だけ）
export GEN2_STORAGE_GIB=4096
export GEN2_SSD_IOPS=200000
export VOLUME_SIZE_GIB=900                    # LUN 600 GiB + 5% 以上
```

**`STAGING_BUCKET` は任意ではない。** クライアントは NAT も公開アドレスも持たないので
**PyPI と GitHub に到達できない**（タイムアウトで確認済み）。VDBENCH は S3 経由でしか入らない。

### 値を変えるときに壊れる組み合わせ

| 変えるもの | 一緒に見る値 | 間違えたときに起きること |
|---|---|---|
| `GEN2_SSD_IOPS` | `GEN2_STORAGE_GIB` | **SSD 1 GB あたり 50 IOPS を超えると作成が拒否される。** 200,000 IOPS には 4,000 GiB 以上が必要。runbook が事前に検査して必要量を表示する |
| `GEN2_THROUGHPUT` | — | **1536 / 3072 / 6144 以外は SINGLE_AZ_2 が受けない。** runbook が事前に落とす |
| `VOLUME_SIZE_GIB` | `BLOCK_LUN_GIB`（既定 600） | AWS はボリュームを LUN より 5% 以上大きくすることを推奨している。600 GiB の LUN に 900 GiB を渡している |
| `GEN2_THROUGHPUT` を下げる | NVMe リードキャッシュ | **6,144 未満では NVMe リードキャッシュがそもそも付かない。** 6,144 では既定で 1,900 GB 付くので、ディスク経路を測るなら明示的に切る |

**スループット容量を下げれば安くなるが、比較可能性は失われる。** F-1 から F-3 は 6,144 MBps で
測っているので、別の値で測った数値を同じ表に並べられない。

## 実行順序

**順序に制約がある。** alias と fill はログインの後にしか成立しない — multipath がデバイスを
作るのはセッションが張られてからで、LUN を作った直後には `/dev/mapper/<alias>` が無い。

```bash
cd environments/perf-matrix

./runbook.sh tooling                 # VDBENCH が staging にあるか。ここで落ちるなら先に進めない
./runbook.sh clients                 # クライアント 9 台
./runbook.sh gen2                    # ファイルシステム。約 25〜35 分
./runbook.sh nvme-cache off          # 両ノードで is_enabled: false を確認する
./runbook.sh block-packages          # IQN と NQN、カーネル版、AMI ID を表示する

# --- iSCSI（F-1）---
./runbook.sh block-provision iscsi <IQN>      # LUN、igroup、mapping。serial-hex を返す
./runbook.sh block-sessions multi 8           # ここで初めて multipath がデバイスを作る
#   multipath.conf に alias を書き、wwid を **デバイスから読んで** 検算する（下）
./runbook.sh block-preflight                  # 検査 1 がクライアントのルートボリュームを守る
./runbook.sh block-fill /dev/mapper/<alias>   # 8 並列の dd。600 GiB で約 6 分
for mode in single default multi; do
  ./runbook.sh block-sessions "$mode" 8
  # VDBENCH を vdbench-linux-iscsi.txt で回す
done

# --- NVMe/TCP（F-2）---
./runbook.sh block-provision nvme <NQN>
./runbook.sh block-nvme-sessions default
./runbook.sh block-fill /dev/nvmeXn1
# モードごとに block-nvme-sessions → 測定
```

**LUN と namespace を同じボリュームに両方置いて充填することはできない。** 900 GiB に 600 GiB を
2 つは入らないので、**F-1 と F-2 は別の run になる。** 条件はテンプレートで揃えるが、
同一ファイルシステム上の実測にはならない。

### 各段の開始と終了の記録

**前回は記録しなかったので、見積り 5.9 h に対する実績が書けない。**
[計画の所要時間](block-protocol-matrix-plan.md#所要時間の内訳)は環境 1 つで通す前提で積んであり、
実際は 3 つの環境になった。**回数が増えたことは所見（デプロイ間の散らばり）につながったので
損失ではないが、見積りを次に直せる材料が残らなかった。**

各段の前後でこれを実行し、出力を run のメモに残す。

```bash
date -u +'%Y-%m-%dT%H:%M:%SZ'   # 段の開始と終了で 1 回ずつ
```

**記録するのは段の名前と UTC の時刻だけでよい。** 秒まで要らないが、**日付をまたぐので
時刻だけでは足りない** — 前回の F-1 と F-2 は暦日が違う。

## 9 回で踏んだ罠

**どれも「成功したように見えて何も測れていない」形で現れた。** 各行の右列が、次に同じ環境を
作る人が確認すべきことである。

| 症状 | 原因 | 確認の仕方 |
|---|---|---|
| スタック作成が 25 分後に失敗 | **`JunctionPath` が必須。** リファレンスは本文と `Required:` 欄が矛盾している | テンプレートに入っている。触らない |
| subsystem に host を追加できない | private CLI の passthrough は POST を `create` に写すが、`subsystem map add` と `host add` は **`add` コマンド**で、`invalid operation` が返る | public REST API を使う。修正済み |
| `nvme discover` が subnqn を返さない | 上の失敗が無言なので、**namespace も host も無い subsystem** は discovery に出てこない。症状は 2 フェーズ後に出る | `block-provision nvme` が mapping を読み返して表示する |
| host NQN が空 | **AL2023 は `/etc/nvme/hostnqn` を作らない。** AWS の手順は RHEL 9.3 前提でこのファイルを読む | `nvme gen-hostnqn` で生成する。修正済み |
| ログイン直後に確立済み TCP が 0 本 | **iSCSI のログインは非同期。** `--login` が返った後に iscsid が繋ぐ。この環境では約 100 秒かかった | セッション数が期待値に達するまで待ってから数える |
| 単一ポータルを指定したのに 2 セッション | discovery が `node.startup` を `automatic` のまま残すので **iscsid が全ポータルに繋ぐ** | ログイン前に `node.startup` を `manual` にする |
| `--login` が `No records found` | ポータルを `iscsiadm -m node -T <target>` の出力から取っていたが、**先頭行はコメント**（`# BEGIN RECORD 2.1.4`） | ポータルは FSx for ONTAP の API の `Endpoints.Iscsi.IpAddresses` から取る |
| `/dev/mapper/<alias>` が現れない | **`find_multipaths yes` は 1 パスのデバイスにマップを作らない。** single モードは意図して 1 パス | `multipath -a <wwid>` で明示登録する。wwid は `scsi_id` で**デバイスから読む**（`3600a0980`+serial の組み立ては検算に使うだけ） |
| fill が何も書かずに終わる | vdbench は `include=` を **-f のパスではなくカレントディレクトリ基準**で解決する | `/opt/bench/parm` から起動する |
| fill が `Unused parameter substitution` で落ちる | vdbench のコマンドラインの `key=value` は**ワークロード定義の上書きではなく、パラメータファイル内のプレースホルダへの代入** | fill は dd で行う。測定器が違うので**その値を VDBENCH の数値と並べない** |
| fill が「失敗」と報告される | SSM の待ちが 30 回 × 15 秒 = 7.5 分で、600 GiB の書き込みが収まらない。**`status: InProgress` を失敗として報告していた** | フェーズごとに待ち予算を渡す。**待ちの上限は失敗ではない** |
| F-2 がスキップされる | `grep -q 'MISSING'` が**フェーズ自身の説明文**（「A MISSING line means…」）に当たっていた | センチネルは行頭で固定する。**自分の説明文で満たされるセンチネルはセンチネルではない** |
| モードごとの接続数が合わない | AL2023 の autoconnect ユニットが**自分でコントローラを増やす**（`host_traddr` を持たない対が現れる） | 接続前に無効化する。それでも増えることがあるので、**ポートの合計ではなく、測定対象のデバイスを持つコントローラの `queue_count` を見る** |
| 撤去が `DELETE_FAILED` で止まったまま | ENI の切り離しが終わる前にセキュリティグループを消そうとする。**再試行すれば通る**のに、再試行していなかった | 両スタックを再試行する。**撤去はスタックの状態で確認し、delete 呼び出しの戻り値で判断しない** |
| 撤去したのに課金が残る | **ボリューム削除ごとに最終バックアップが 1 つ作られる** | `aws fsx describe-backups` を `Volume.Name` で絞って消す。**タグでは絞れない** |

### 撤去を自動化するときの前提

**trap の中で `set -e` を効かせてはいけない。** 削除の後に続く観測（`describe-stacks`）は、
**消え終わったスタックに対しては必ず失敗する。** その失敗が trap 自身を殺すので、
削除は走ったのに再試行が動かない、という形になる（2 回起きた）。

- 削除呼び出しを trap の**最初**に置く
- その直後で `set +e` と `set +o pipefail`
- 撤去の完了は状態で確認する

## この手順で測れないこと

- **ANA マルチパスを使った NVMe/TCP。** 測定に使ったカーネルは `# CONFIG_NVME_MULTIPATH is not set`
  だった。**「AL2023 では」と一般化しない** — 観測は SSM パラメータが 2 日間に返した AMI に限る
- **ファイルシステムを載せた場合の値。** raw device の値である
- **ベースライン。** 窓は 300 秒でバーストを含む
- **同一ファイルシステム上での iSCSI と NVMe/TCP の比較**（上の理由で別 run になる）

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [ブロックプロトコルの測定計画](block-protocol-matrix-plan.md) | 何を測るか、「1 セッション」の定義と出典 |
| [プロトコル別測定の結果](perf-matrix-results.md#f-1-iscsi-の実測) | F-1 / F-2 / F-3 の数値と条件 |
| [測定環境](../../../environments/perf-matrix/README.md) | ファイルプロトコル側の手順と環境の作り方 |
| [検証パターンごとの費用構造](../reference/comparison/finops-performance-test-patterns.md) | パターン別の費用と、消し忘れたときの額 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
