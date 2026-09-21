# FSx for ONTAP のブロックプロトコルを測るときの考慮点

<!-- lang-switcher:start -->
🌐 [日本語](block-protocol-testing-guide.md) | [English](../../en/reference/block-protocol-testing-guide.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->

iSCSI / NVMe-TCP で FSx for ONTAP をマウント・測定するときに踏んだ落とし穴を 1 か所に集める。
**ファイル / S3 プロトコルの考慮点は[こちら](performance-testing-guide.md)。** この文書はブロック
プロトコル固有の項目だけを持つ。

この文書は測定の前に読むもので、測定結果は含まない。結果は
[検証状況](../verification-status.md)から辿る。出どころは
[プロトコル別測定の結果](../verification/perf-matrix-results.md)と
[ブロック測定の実行手順](../verification/block-measurement-runbook.md)。

## マウントに到達する前の 4 つ

**どれも「成功したように見えて何も測れていない」形で現れる。**

| 症状 | 原因 | 確認方法 |
|---|---|---|
| ファイルシステム作成の 25 分後に失敗する | `JunctionPath` は API リファレンス本文で `This parameter is required.` としながら `Required:` 欄が `No`。**実挙動は必須** | `RW` ボリュームでは必ず指定する |
| `cat /etc/nvme/hostnqn` が `No such file or directory` | AL2023 はこのファイルを作らない（RHEL は作る） | `nvme gen-hostnqn` で生成する |
| ログイン直後に `ss` で数えて 0 本 | `iscsiadm --login` は接続完了より先に返る。この環境では**約 100 秒**かかった | 「コマンドが返った」を「繋がった」の証拠にしない。数えて確認する |
| `/dev/mapper/<alias>` が現れない | 単一フローを測るときは意図して 1 パスだが、`find_multipaths yes` は 1 パスのデバイスにマップを作らない | `multipath -a <wwid>` で明示登録する。wwid は `scsi_id` でデバイスから読む方が、組み立てるより確実 |

詳細な症状・原因・確認方法の表は[ブロック測定の実行手順](../verification/block-measurement-runbook.md)。

## セッション数・キュー数を見積もる前に

**「1 クライアント 5 Gbps（約 625 MBps）」を除数にしてセッション数を見積もる形は、
両方向に外れる。** 1 本で 1.82 倍、16 本で 0.20 倍。**1 本から 2 本に増やしても逐次スループット
が動かない**こともあり、1 本のときに当たっている上限は 1 フローの容量ではない。

NVMe/TCP には `nr_sessions` に相当するものが無く、対応する量はキュー数である。
**キュー数は要求しても通らない** — `--nr-io-queues` で 36 を要求して 4 になった例がある。

- **実効値は `nvme get-feature --feature-id 7` で読む。** サブシステムに設定した値ではなく、
  ホスト・トランスポート・優先度の組ごとに ONTAP 側が決める
- **`queue_count` は admin queue を含み `NCQA + 1` に一致する**（1 → 2、4 → 5）
- 掲載例の値を自分の環境の値として使わない。同じ条件でも環境によって異なる

## ANA（マルチパス）が使えるかの課金前の確認

**確認は 1 コマンドで済み、ファイルシステムを作る前に判定できる。**

```bash
grep -i NVME_MULTIPATH /boot/config-$(uname -r)
```

`# CONFIG_NVME_MULTIPATH is not set` なら、AWS の手順にある
`cat /sys/module/nvme_core/parameters/multipath` は成立しない（ファイルが存在しない）。
これはカーネルのビルド設定であり、パッケージの追加では変えられない。

**この確認結果を、一般化して書かない。** 「AL2023 では ANA が使えない」ではなく、確認した
カーネル版でどうだったかを書く。AL2023 の既定カーネルは変わりうる。

### 経路が 2 本あることと、2 本使っていることは別

**`nvme list-subsys` の `optimized` / `non-optimized` は「経路が 2 本ある」の表示で、
「2 本使っている」の表示ではない。** 使っているかどうかは別に数える必要がある。

| テーブル | 罠 |
|---|---|
| `nvmf_lif` | **行が 0 件になりうる。** テーブル自体が存在しないことと区別できない |
| `lif` | 該当 LIF を 0 バイトと報告する。**NVMe-oF を数えていない** |
| `nvmf_tcp_port` | 実データを持つ。LIF ごとに `read_data` / `write_data` / `total_ops` |

**「テーブルはあるが行が無い」と「このバージョンにそのテーブルは無い」は、0 を返す点で同じ
見た目になる。** 0 を返して先へ進むと、正しい結論を間違った理由で得ることがある。

クライアント側でも独立に数えられる。NVMe/TCP のコントローラは宛先アドレスが別なので、
確立済みソケットを宛先ごとに集計すれば経路が分かれる。

```bash
ss -tin state established | awk '/:4420/{...}'   # 宛先ごとに bytes_sent / bytes_received を合計
```

**ONTAP 側のカウンタとクライアント側の集計、両方が一致してから結論を書く。**

### `iopolicy` の確認手順自体の版依存

AWS の手順は `iopolicy` が `round-robin` であることを確認するよう書いているが、`nvme-cli` の
バージョンによって udev 規則が設定する値が変わる（upstream の `71-nvmf-netapp.rules.in` で
v2.11 は `round-robin`、v2.12 以降は `queue-depth`）。**手順どおりに確認すると、バージョンに
よって期待と違う値が返ることがある。** 性能への影響は無視できる範囲（実測で 0.5%）で、これは
性能の問題ではなく確認手順が返す値の版差である。

## 測定器（VDBENCH）とブロックデバイスを扱うときの落とし穴

**auto_vdbench はマウントパスにテストファイルを作る作りで、raw device / NVMe namespace を
駆動できない。** ブロックを測るときは VDBENCH を直接使う。

| 症状 | 原因 | 対処 |
|---|---|---|
| fill が「何も書かずに正常終了」する | vdbench は `include=` を `-f` のパスではなくカレントディレクトリ基準で解決する | 実行時のカレントディレクトリを確認する。未書き込みブロック（ゼロ）を読む測定になっていないか、事前に検証する |
| `xfersize=1024k` を渡すと `Unused parameter substitution` で落ちる | コマンドラインの `key=value` はワークロード定義の上書きではなく、パラメータファイル内のプレースホルダへの代入である | パラメータファイル側にプレースホルダを用意する |
| 600 GiB の書き込みが待ちの上限に収まらず失敗と判断してしまう | SSM の `status: InProgress` を失敗と誤判定した | 待ちの上限は失敗ではない。完了までポーリングを続ける |
| モジュールがあるのに検出ステップがスキップされる | 「モジュールが無ければ MISSING と出す」実装に対し `grep -q 'MISSING'` で判定していたが、同じ出力内の説明文（`A MISSING line means…`）にヒットした | 自分の説明文で満たされるセンチネル文字列を使わない |
| 撤去後に `DELETE_FAILED` のスタックが残る | `set -euo pipefail` の下で、削除後の `describe-stacks` は消え終わったスタックに対して必ず失敗し、その失敗が trap 自身を殺す | 削除呼び出しを trap の最初に置き、その直後で `set +e` する |
| ソケット集計に存在しない経路が生える | `:4420` で終わるフィールドを宛先と見なしたところ、`bytes_acked:4420` という**値**が偶然 4420 と一致し、`bytes_acked` という名前の偽の経路が生まれた | 集計対象のフィールド名を、値の内容ではなく明示的なキー名で選ぶ |
| CI だけ赤くなる | 追跡対象を走査する検査があり、新規ファイルが未追跡のうちは走査に入らない | 「最後の編集のあと」だけでなく「最後の `git add` のあと」に検査する |

## プロビジョンド IOPS を下げたときの 6 時間のクールダウン

**プロビジョンド IOPS の変更はストレージ容量更新として扱われ、下げた直後は前回の更新から
6 時間経つまで次の更新を受け付けない。** 下げてすぐ元に戻そうとすると
「cannot start until at least 6 hours have passed since the last storage capacity update」で
拒否される。待っている間も課金は続く。

**上げる方向には同じ制約がない。** 1 回の更新で済み、クールダウンに当たらない。複数の指定値を
測る計画では、ファイルシステムを下げる方向ではなく上げる方向の 1 系列で作るほうが安い。

**更新自体の完了も即時ではない。** `UPDATED_OPTIMIZING` の状態に約 18 分（下げる場合は約 17 分）
留まる。この間は新しい指定値での測定を始めない。

| したいこと | 安い作り方 |
|---|---|
| 複数の指定値を順に測る | 低い値から高い値へ、上げる方向だけの 1 系列にする |
| 下げた値も測りたい | その値をファイルシステム作成時に指定し、上げ直さない前提で作る |
| 下げてから元に戻す往復が必要 | 環境を作り直す方が、6 時間待つより安いことが多い |

## 記録に必ず添える項目（ブロック固有）

[ファイル/S3 プロトコルの一覧](performance-testing-guide.md#記録に必ず添える項目)に加えて、
ブロックでは次を記録する。

- iSCSI: 数えた TCP 接続の本数（指定値ではなく `ss` で数えた実数）
- NVMe/TCP: 要求したキュー数と実効キュー数（`nvme get-feature --feature-id 7`）、コントローラ数
- ANA: カーネルの `CONFIG_NVME_MULTIPATH` の有無、確認したカーネル版
- `iopolicy` の設定値と、`nvme-cli` のバージョン
- 経路ごとのバイト数（ONTAP 側のカウンタとクライアント側の集計の両方）
- ONTAP のバージョン。**`FileSystemTypeVersion` は Lustre 専用フィールドで FSx for ONTAP では
  取得できないため、クラスタ側の API か手動記録に頼る必要がある**

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [ファイル/S3 プロトコルの考慮点](performance-testing-guide.md) | プロトコル共通の落とし穴と記録項目 |
| [ブロック測定の実行手順](../verification/block-measurement-runbook.md) | 症状・原因・確認方法の一覧 |
| [プロトコル別測定の結果](../verification/perf-matrix-results.md) | ブロックプロトコルの実測記録 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |

---

<!-- lang-switcher:start -->
🌐 [日本語](block-protocol-testing-guide.md) | [English](../../en/reference/block-protocol-testing-guide.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
