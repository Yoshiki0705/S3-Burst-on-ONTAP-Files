# SMB でマウントできる名前と、識別子を読む場所

**このページは 1 回の失敗から書いた。** 2026-09-06、SMB の測定環境で、ボリュームの junction path
を共有名としてマップしようとして 9 台すべてが失敗した。**手順はこのリポジトリに既にあり、
読まずに API の出力から推測したことが原因である。** 同じ形の失敗を 3 件連続で踏んだので、
機構と、誤りの現れ方と、一般化した規則を残す。

- [SMB で到達できるのは共有だけ](#smb-で到達できるのは共有だけ)
- [既定で存在する共有と、その制約](#既定で存在する共有とその制約)
- [原因が別物に見える 3 つのエラー](#原因が別物に見える-3-つのエラー)
- [3 件が同じ形だった理由](#3-件が同じ形だった理由)
- [識別子は読む。隣の名前から導出しない](#識別子は読む隣の名前から導出しない)
- [着手前に通す検査](#着手前に通す検査)

## SMB で到達できるのは共有だけ

**ボリュームの junction path は共有名ではない。** NFS はエクスポートされたパスを直接マウント
できるが、SMB クライアントが指定するのは共有（CIFS share）で、これは ONTAP 上の別のオブジェクト
である。共有を作るまで、そのボリュームに SMB で到達する名前は存在しない。

| | NFS | SMB |
|---|---|---|
| クライアントが指定するもの | junction path | **共有名** |
| ボリューム作成で使えるようになるか | なる（export policy 次第） | **ならない。共有の作成が別に必要** |
| 作る手段 | — | `vserver cifs share create`、または REST `POST /api/protocols/cifs/shares` |

共有の `-path` は**ボリューム内に存在するパス**でなければならない
（[vserver cifs share create](https://docs.netapp.com/us-en/ontap-cli/vserver-cifs-share-create.html)）。
つまり junction path は**共有の指す先**として使うもので、共有名として使うものではない。

**新しく作った共有の既定 ACL は Everyone / Full Control である**
（[Manage CIFS shares](https://docs.netapp.com/us-en/ontap-restapi-9151/manage_cifs_shares.html)）。
測定用途では足りるが、**権限を測る目的には使えない。** その場合は ACL を明示して記録する。

## 既定で存在する共有と、その制約

CIFS サーバーを作ると管理用の共有が自動で作られる。**データ用の共有は作られない。**

| 共有 | 用途 | 測定に使えるか |
|---|---|---|
| `ipc$` | 名前付きパイプ。ONTAP が使う | **使えない。**設定・プロパティ・ACL を変更できず、削除も改名もできない |
| `admin$` | SVM のリモート管理。**ONTAP 9.8 以降は既定で作られない** | 使えない |
| `c$` | SVM ルートボリュームへの管理アクセス | **推奨しない。**下記 |

出典は
[Learn about the default administrative ONTAP SMB shares](https://docs.netapp.com/us-en/ontap/smb-admin/default-administrative-shares-concept.html)。
`$` で終わる共有は隠し共有なので、エクスプローラには出ない。

**`c$` の既定 ACL は `BUILTIN\administrator` の Full Control で、パスは常に SVM ルートで変更でき
ない**（同上）。SVM 管理者は `c$` から junction を越えて名前空間の残りに到達できるので、
`\\<svm>\c$\<volume>` の形は動く。**ただしそれは測定の代表性を落とす。** 管理者アカウントで
マップすると権限評価の一部を迂回するため、**マップに使ったアカウントは結果の一部**になる。
非特権のドメインアカウントと専用共有を使うほうが、後から条件を説明できる。

## 原因が別物に見える 3 つのエラー

**SMB 層のエラー文字列は原因を一意に指さない。** 実際に踏んだ順に並べる。

| クライアント側のエラー | 実際の原因 | 確認する場所 |
|---|---|---|
| `The specified network password is not correct.` | **アカウントがドメインに存在しない。**パスワードは合っている | ディレクトリ側にアカウントがあるか。**シークレットの存在はアカウントの存在ではない** |
| `The network name cannot be found.` | **共有が存在しない。**パスやアカウントの問題ではない | `GET /api/protocols/cifs/shares` の一覧 |
| `System error 53`（`net use`） | UNC のバックスラッシュが JSON → SSM → PowerShell → `cmd` の 4 段で合わなくなった | `New-SmbMapping` に置き換える（パラメータ渡しなので入れ子の引用符が要らない） |

**1 行目がいちばん危険である。** アカウント不在がパスワード誤りとして現れるので、
シークレットの値を疑って時間を使うことになる。**新しく作ったディレクトリでは、シークレットが
残っていてもアカウントは無い。** ディレクトリはアカウントの入れ物で、シークレットは値の入れ物
である。

## 3 件が同じ形だった理由

**3 件すべて「読めば分かることを、隣のデータから推測した」である。**

| 誤り | 推測したもと | 読むべきだったもの |
|---|---|---|
| junction path を共有名として使った | `describe-volumes` の `JunctionPath` | 環境の README のマウント手順（`\\<netbios>.<domain>\<share>` と書いてある） |
| SVM 名を `perfmatrix_smb_svm` と書いた（実際は `-` 区切り） | ボリューム名 `perfmatrix_smb_svm_root` の接頭辞 | `describe-storage-virtual-machines` の `Name` |
| アカウントが存在すると仮定した | シークレットが存在していたこと | ディレクトリ側のアカウント一覧 |

**そして README を断片で読んだことが共通の入口である。** `grep` に絞った語を与え、`| head` で
出力を切って、当たった行だけから手順を組み立てた。**同じ `| head` で、実在する
`vdbench-windows-smb.txt` を「無い」と誤認してもいる。** 走査範囲を切ると検出器は沈黙する、
というのはこのリポジトリが別の文脈で既に記録している失敗である。

**手順が文書にある作業では、最初のコマンドを打つ前にその節を通しで読む。** 断片から組み立てた
手順は、文書と一致しているかを誰も検査していない。

## 識別子は読む。隣の名前から導出しない

**リソース名・共有名・アカウント名・SVM 名は、権威のある API から読む。** 命名規約から導けそうに
見えても導かない。同じ環境の中で区切り文字が混在することは普通にある。実例として、この環境では
**SVM 名がハイフン区切り（`perfmatrix-smb-svm`）でボリューム名が下線区切り
（`perfmatrix_smb_vol`）** である。片方から他方を導くと外れる。

| 欲しいもの | 読む API |
|---|---|
| SVM 名 | `aws fsx describe-storage-virtual-machines`（`Name`） |
| ボリュームの junction path | `aws fsx describe-volumes`（`OntapConfiguration.JunctionPath`） |
| 共有の名前とパス | ONTAP REST `GET /api/protocols/cifs/shares?fields=name,path,svm.name` |
| SMB エンドポイント | `describe-storage-virtual-machines`（`Endpoints.Smb.DNSName`）または NetBIOS 名 |

**スタックの出力が ID を返していても、名前を返しているとは限らない。** この環境の
`SmbStorageVirtualMachineId` は `svm-...` の ID で、名前はそこに無い。**ID があることは名前を
知っていることではない。**

## 着手前に通す検査

`./runbook.sh smb-preflight` が上の 4 つを読んで、**足りないものを理由付きで報告する。**
マウントを試す前に走らせる。**汎用のエラー文字列を読んで原因を推測する代わりに、
先に状態を読む**ためにある。

検査するもの。

1. SVM が存在し、AD に参加していること（`Lifecycle` と NetBIOS 名を読む）
2. **データ用の CIFS 共有が存在すること。** `c$` と `ipc$` しか無い状態を「共有あり」と数えない
3. 共有の `path` が、実在するボリュームの junction path と一致すること
4. マップに使うドメインアカウントがディレクトリで解決できること（**シークレットの存在では代用
   しない**）

**どれか 1 つでも欠けたら非ゼロで終わる。** 4 つ揃ったという出力が、マウントしてよいという判断の
根拠になる。

## 関連ドキュメント

- [検証環境の手順](../../../../environments/perf-matrix/README.md) — この環境の作成順序
- [性能検証の考慮点](../performance-testing-guide.md) — 記録に必ず添える項目
- [規約がコードにあるとき](../../../agent/policy-in-code.md) — 外部の観測だけで判断しない理由
