# プロトコル別測定の結果

**測定中の記録である。** 完了したケースだけを載せ、残りは
[測定計画](throughput-protocol-matrix-plan.md)側に未測定として置いてある。可否は
[プロトコル別の可否](protocol-matrix-efs-vs-ontap.md)にある。

環境と手順は[測定環境](../../../environments/perf-matrix/README.md)にあり、テンプレートと
スクリプトから再現できる。

## 測定条件（全ケース共通）

| 項目 | 値 |
|---|---|
| 測定日 | 2026-09-05 |
| リージョン | ap-northeast-1、単一 AZ、全ターゲットと全クライアントが同一サブネット |
| ONTAP | 9.18.1P5 |
| ファイルシステム | FSx for ONTAP 第二世代、SINGLE_AZ_2、**6,144 MBps ×1 HA ペア** |
| SSD | 4,096 GiB、プロビジョンド **200,000 IOPS** |
| **NVMe リードキャッシュ** | **無効**（両ノードで `is_enabled: false` を読み直して確認） |
| ボリューム | 900 GiB、UNIX セキュリティスタイル、階層化なし、**インライン効率化なし** |
| テストデータ | 600 GiB の単一ファイル、非圧縮（dedup 1、compression 1） |
| クライアント | c5n.9xlarge ×1（ネットワーク 50 Gbps は保証値）、Amazon Linux 2023、カーネル 6.18.44 |
| 測定器 | auto_vdbench 1.1.0（VDBENCH 5.04.07 を駆動）、`openflag=o_direct` |
| 並列度 | 512 スレッド |
| 1 試行 | 120 秒 + ウォームアップ 30 秒 |

**インメモリキャッシュは 256 GB で、読んだ量はその 2.3 倍である。** NVMe 層も無効なので、
この読み取りは SSD に到達している。

## E: 第二世代、NFSv4.1、1 MiB 逐次読み取り

**実効マウントオプション**（要求値ではない）:

```text
vers=4.1,rsize=1048576,wsize=1048576,hard,proto=tcp,nconnect=16,timeo=600,retrans=2,sec=sys
```

| 目標 IOPS | 達成 IOPS | スループット | 応答時間 | 応答時間の標準偏差 | キュー深度 | クライアント CPU |
|---|---|---|---|---|---|---|
| 500 | 496.1 | 496 MB/s | 1.96 ms | — | — | — |
| 1,000 | 1,002.9 | 1,003 MB/s | 3.74 ms | — | — | — |
| 2,100 | 2,102.1 | 2,102 MB/s | 5.52 ms | — | — | — |
| 4,200 | 4,190.3 | 4,190 MB/s | 7.80 ms | — | — | — |
| **4,400** | **4,405.9** | **4,406 MB/s** | **8.86 ms** | 8.64 ms | 39.0 | 12.4% |
| 無制限 | 4,204.5 | 4,204 MB/s | **121.79 ms** | — | — | — |

レイテンシ基準の到達点（auto_vdbench 算出）: **2 ms で 508 IOPS、3 ms で 793、4 ms で 1,165。**
1 ms の値は算出されていない。

### 無制限に流すと下がる

**目標 4,400 では 8.86 ms で 4,406 MB/s 出るのに、無制限では 4,204 MB/s で 121.79 ms である。**
スループットが 5% 下がり、応答時間は 14 倍になる。512 スレッドで制限なく投げた結果である。

**`iorate=max` の値だけを「上限」として記録すると、到達可能な値より低く、かつレイテンシが 1 桁
悪い数字が残る。** 上限を探すときは、無制限の 1 点ではなく目標値を振った系列で見る。

### 指定した 6,144 MBps に対して 72%

**4,406 MB/s は、指定したスループットキャパシティ 6,144 MBps の 72% である。** 次の 2 つは
この値の説明にならない。

| 候補 | 実測 | 判定 |
|---|---|---|
| クライアントのネットワーク帯域 | 4,406 MB/s = 35.2 Gbps、保証値は 50 Gbps | **届いていない** |
| クライアントの CPU | 12.4%（sys + user） | **余っている** |

**確認できた事実として、この SVM の NFS/SMB データ LIF は 1 本しかない。**

| SVM | LIF | ノード | 用途 |
|---|---|---|---|
| `perfmatrix-gen2-svm` | `nfs_smb_management_1` | **-01** | NFS / SMB / 管理 |
| 同 | `iscsi_1` | -01 | iSCSI |
| 同 | `iscsi_2` | -02 | iSCSI |

マウントはこの 1 本（`/proc/mounts` の `addr=` がこの LIF のアドレスと一致）を使っている。**iSCSI には両ノードに LIF があるが、
NFS / SMB 用は 1 本で、NFS を 2 ノードへ分散させる宛先が存在しない。**

**指定値の 6,144 MBps は HA ペア単位である。** したがって「1 本の LIF・1 ノードを通る経路の上限が
4,406 MB/s だった」という読みは筋が通るが、**これは未検証である。** 確定させるには、
**クライアントを増やしても同じ 1 本の LIF に対して合計が 4,400 付近で止まるか**を見る必要がある。
止まるならクライアント側ではなく経路側の上限であり、伸びるならクライアント 1 台の限界だった
ことになる。この試験は未実施である。

## 測定器そのもので踏んだ非互換

**再現しようとする人が同じ壁に当たるので記録する。** どちらも測定値には影響しないが、
**片方は「測定に失敗した」と誤解させる形で出る。**

| 事象 | 原因 | 対処 |
|---|---|---|
| `AttributeError: module 'numpy' has no attribute 'RankWarning'` | numpy 2.x で `np.RankWarning` が `np.exceptions` へ移動。auto_vdbench は numpy 1.x 前提 | `getattr(np, 'RankWarning', np.exceptions.RankWarning)` に置換 |
| `Image export requires the Kaleido package, v1.0.0 or greater` | plotly 7 が kaleido ≥1 を要求し、**kaleido 1.x は外部 Chrome を要求する** | **plotly 5.24.1 + kaleido 0.2.1** に固定。0.2.1 は Chromium を同梱する |

**numpy の方は測定が完走したあとのレポート生成だけで落ちる。** VDBENCH の出力は残っているので、
例外を見て測定失敗と判断すると、取れているデータを捨てることになる。`create-report` で
やり直せる。

**kaleido の方はインターネットに出られない環境で顕在化する。** kaleido 1.x は実行時に Chrome を
取得しようとする。

## 未測定

| ケース | 状態 |
|---|---|
| E: 第二世代 1 MiB 逐次書き込み | 未測定 |
| E: 第二世代 NFSv3 / NFSv4.0 / NFSv4.2 | 未測定（マウント可否のみ実測） |
| E: 第二世代 64 KiB / 4 KiB | 未測定 |
| E: SMB | 未測定（AD 参加と SMB エンドポイントの発行まで実測） |
| D: EFS Elastic / Provisioned | 未測定 |
| E1: 世代差（第一世代 対 第二世代、NFSv4.1 固定） | 未測定 |
| 台数を増やす試験（上の LIF の仮説を確定させるもの） | 未測定 |
| A-1 / A-2: S3 API と NFS の同一データ比較 | 未測定 |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [測定計画](throughput-protocol-matrix-plan.md) | 測定パターンと必要な環境 |
| [プロトコル別の可否](protocol-matrix-efs-vs-ontap.md) | どの組み合わせがマウントできるか |
| [測定環境](../../../environments/perf-matrix/README.md) | テンプレート、実行順序、削除手順 |
| [性能検証の考慮点](../reference/performance-testing-guide.md) | 測る前に確認すること |
| [検証パターンごとの費用構造](../reference/comparison/finops-performance-test-patterns.md) | 費用と、消し忘れたときの額 |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
