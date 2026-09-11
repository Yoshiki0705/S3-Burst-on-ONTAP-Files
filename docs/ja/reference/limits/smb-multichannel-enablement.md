# SMB Multichannel が既定で無効であることと、有効化が既に張られた接続に届かないこと

**このページも 1 回の測定から書いた。** 2026-09-06、SMB の台数試験を始めた直後、1 台目が
942.65 MB/s で読んでいる最中に SVM 宛ての確立済み TCP が **1 本**しかなかった。同じ環境の別
インスタンスでは以前 4 本を観測していたので、インスタンス種別の違いだと考えたが、**違った。**
SVM 側で Multichannel が無効だった。有効化してからも 1 本のままで、そこにもう 1 つ機構がある。

- [観測と、原因を切り分けた順序](#観測と原因を切り分けた順序)
- [既定値と、有効化が届く範囲](#既定値と有効化が届く範囲)
- [チャネル数を読む場所と、空を返す条件](#チャネル数を読む場所と空を返す条件)
- [測定に対する影響](#測定に対する影響)
- [出典](#出典)

## 観測と、原因を切り分けた順序

| 段 | 読んだもの | 結果 |
|---|---|---|
| 1 | `Get-NetTCPConnection -RemotePort 445 -State Established` | **1 本**（読み取り 942.65 MB/s の最中） |
| 2 | `Get-SmbClientConfiguration` | `EnableMultiChannel: True`、`ConnectionCountPerRssNetworkInterface: 4` |
| 3 | `Get-SmbClientNetworkInterface` / `Get-NetAdapterRss` | `RssCapable: True`、受信キュー 8 |
| 4 | ONTAP `vserver cifs options` | **`is_multichannel_enabled: false`** |

クライアント側は 4 接続を張る設定で、NIC も RSS 対応だった。**残っていたのはサーバー側で、
そこが無効だった。** インスタンス種別の違いという最初の見立ては、2 段目で否定されている。

有効化したあとも 1 本のままで、**ローカルポートが有効化前と同一（`50244`）だった。** 同じ
TCP 接続が使われ続けていたということで、`Remove-SmbMapping` でドライブ文字を消しても、その下の
SMB セッションは残って再利用される。`LanmanWorkstation` を再起動して初めて 4 本になった。

| 操作 | 有効化後の確立済み TCP |
|---|---|
| `vserver cifs options modify -is-multichannel-enabled true` のみ | 1 |
| 上記 + `Remove-SmbMapping` → `New-SmbMapping` | 1（ローカルポートも同一） |
| 上記 + `Restart-Service LanmanWorkstation -Force` → 再マップ | **4**（`CurrentChannels: 4` / `MaxChannels: 4`） |

## 既定値と、有効化が届く範囲

NetApp のナレッジベースが 2 つとも明記している。

- **既定で無効。** ONTAP 9 の SMB Multichannel は無効で出荷される。ONTAP が SMB 3.0 以降を
  既定で有効にしていることとは別の設定で、**プロトコル版が 3.1.1 でネゴシエートされていても
  Multichannel が張られているとは限らない。** 測定環境では `dialect=3.1.1` と 1 チャネルが
  同時に成立していた。
- **有効化・無効化は新規接続にしか効く（具体的には Tree Connect）。** 既に確立している接続は
  設定変更後もそのまま動き続ける。**成功したという応答は、その接続に適用された証拠ではない。**

`max_connections_per_session` は別の値で、測定環境では既定の 32 だった。**32 が設定されていても
Multichannel が無効なら 1 チャネルである。** この 2 つを混同すると、上限を上げたのに増えないと
読み違える。

## チャネル数を読む場所と、空を返す条件

`Get-SmbMultichannelConnection` は Multichannel が確立していないとき**何も返さない**。返らない
ことを「取得できない」と読むと probe を疑い始めるが、**それが答えである**（この機構では
「無効」を意味する）。実際に確立すると、インターフェース対 1 組につき 1 行が返り、その行の
`CurrentChannels` と `MaxChannels` がチャネル数を持つ。

**行数はチャネル数ではない。** 4 チャネルでも行は 1 行なので、`Measure-Object` で数えると 1 に
なる。台数試験の途中でこれを 1 と記録しかけた。

| 読みたいもの | 読む場所 |
|---|---|
| チャネル数 | `(Get-SmbMultichannelConnection).CurrentChannels` |
| 上限 | 同 `.MaxChannels` |
| プロトコル水準の裏付け | `Get-NetTCPConnection -RemotePort 445 -State Established` の**本数** |
| サーバー側の可否 | ONTAP `vserver cifs options` の `is-multichannel-enabled` |

`Get-SmbConnection` に `CurrentChannels` は**存在しない**。ここを探して見つからず、cmdlet が
権威でないと判断しかけたが、探す場所が違っただけだった。

## 測定に対する影響

**既に取得済みの数値には、そのときのチャネル数を併記しないと比較できない。** 同一ファイル
システム・同一共有・同一パラメータでも、Multichannel の有無で 1 MiB 逐次読みが変わる。

| 条件 | 1 MiB 逐次読み | 備考 |
|---|---|---|
| c5n.2xlarge、1 チャネル、64 スレッド | 942.65 MB/s | Multichannel 無効の SVM で観測。台数試験の予備測定 |

この 942.65 MB/s は、**Multichannel が無効だと気づく前に取れた点**である。捨てずに残すが、
4 チャネルの数値と同じ列に置いてはいけない。

> **この 2 点には NVMe リードキャッシュの状態が記録されていない。** 第二世代 6,144 MBps には
> **1,900 GB の NVMe リードキャッシュがあり、既定で有効**である（2026-09-10 に別のファイル
> システムで実機確認。[実測](../../verification/throughput-capacity-burst-and-baseline.md)）。
> 同じ perf-matrix 環境の 2026-09-05 の測定条件表は無効と記録しているが、**この測定が同じ
> ファイルシステムだったかは記録から確定できない。**
>
> **チャネル数の差そのものは影響を受けない**（接続の本数の話なので）。影響を受けるのは
> **942.65 と 1,824 という絶対値**で、これをディスク経路の値として引用してはいけない。
> **条件の記録漏れは、値を消す理由ではなく、値の引用先を狭める理由である。**

**台数試験を始める前に確認する。** 有効化してから走らせないと、点ごとにチャネル数が違う可能性が
残り、台数以外の差が混ざる。手順は
[perf-matrix の README](../../../../environments/perf-matrix/README.md)。

## 出典

- [Should I enable SMB Multichannel](https://kb.netapp.com/on-prem/ontap/da/NAS/NAS-KBs/Should_I_enable_SMB_Multichannel)
  — 既定で無効であること、および有効化・無効化が新規接続にのみ効くこと（Tree Connect）
- [Configure ONTAP SMB Multichannel for performance and redundancy](https://docs.netapp.com/us-en/ontap/smb-admin/configure-multichannel-performance-task.html)
  — Multichannel の利用条件が SMB 3.0 以降のネゴシエートであること、および ONTAP が SMB 3.0
  以降を既定で有効にしていること
- [MSFT_SmbMultichannelConnection class](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/smb/msft-smbmultichannelconnection)
  — `CurrentChannels` がインターフェース対ごとの確立済みチャネル数であること

## 関連

- [SMB でマウントできる名前と、識別子を読む場所](smb-share-and-identifier-reading.md) — 同じ
  測定環境で先に踏んだ 3 件
- [規約がコードにあるとき](../../../agent/policy-in-code.md) — 失敗したときに次の試行より先に
  通す 4 段。このページはその 4 段をそのまま適用した結果である
