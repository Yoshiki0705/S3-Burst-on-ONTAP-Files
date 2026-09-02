# 最初に決めること — Origin ボリュームを作る前に

<!-- lang-switcher:start -->
🌐 [日本語](design-first-decisions.md) | [English](../en/design-first-decisions.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->

この構成で後戻りが最も高くつきうる判断は、**ファンアウト先で NFS を使うのか SMB を使うのか**である。
Origin ボリュームのセキュリティスタイルがこれに関わる。

先に結論だけ述べる。**断定と未確認を分けて読んでほしい。**

> **利用拠点で NFS を使うのか SMB を使うのかは、Origin ボリュームの作成前に決めておくのが安全である。**
> セキュリティスタイル（UNIX / NTFS）は S3 Access Point の識別情報の種別と対応し、そこは確認できている。
> **セキュリティスタイルが Cache 作成時に Origin から継承されるかどうかは未確認である。**
> 継承されるなら、Origin 側で後から変更した場合に Cache は削除して作り直すことになる。
> **先に決める理由は非対称性であって、確認済みの制約があるからではない。**

## 出典と確認できている範囲

この節の根拠は **Azure NetApp Files のキャッシュボリューム要件**である
（[cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes) /
[requirements](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-requirements)）。
FlexCache 一般の仕様として AWS のドキュメントで裏を取れているわけではない。

つまり次の 2 つを分けて読む必要がある。

| 事項 | 状態 |
|---|---|
| セキュリティスタイルとプロトコルの対応（下表） | Azure NetApp Files のキャッシュボリューム要件に記載。**この構成の主経路（FSx for ONTAP Origin → オンプレミス ONTAP Cache）で同じ規則が成り立つかは未確認** |
| 「セキュリティスタイルは Origin から継承される」という性質 | 同じ要件文に記載。上記と同じ理由で、主経路での挙動は未確認 |
| プロトコルを後から変えると配布層の作り直しになる | 上 2 つが成り立つ場合の帰結。前提が未確認なので、断定はしない |

未確認であることを理由にこの判断を後回しにしない、という立場をとっている。
成り立っていた場合の手戻りが大きく、成り立っていなかった場合に失うものが何もないためである。
実機で確かめる手順は [PoC チェックリスト](poc-checklist.md)に入れてある。

## セキュリティスタイルとプロトコルの対応

Azure NetApp Files のキャッシュボリューム要件が示している対応は次のとおり。

| Origin のセキュリティスタイル | Cache のプロトコル | S3 AP 対応 |
|---|---|---|
| UNIX | NFS（SMB も可、name-mapping 必須） | ✅ 対応 |
| NTFS | SMB（SVM に CIFS サーバーが必要） | ✅ 対応（Windows 識別情報） |
| MIXED | NFS または SMB | ⚠️ 非推奨（下記参照） |

### MIXED セキュリティスタイルについて

`mixed` は API 上は指定可能ですが、AWS の公式ガイダンスでは**上級者向け（advanced users only）として
推奨されていません**
（[Enabling multiprotocol workloads with Amazon FSx for NetApp ONTAP](https://aws.amazon.com/blogs/storage/enabling-multiprotocol-workloads-with-amazon-fsx-for-netapp-ontap/)）。
FSx for ONTAP のボリューム作成ガイドでも選択肢は UNIX と NTFS の 2 択として案内されています。

mixed の問題:

- パーミッション型が「最後に書き込んだクライアントの種類」で決まるため、権限状態が予測しにくい
- トラブルシューティングが NFS・SMB 両方のパーミッション体系を調べる必要があり複雑化する
- NetApp 自身も disadvantages として「Complex Permission Management」「Troubleshooting Challenges」を
  [KB で挙げている](https://kb.netapp.com/on-prem/ontap/da/NAS/NAS-KBs/What_are_the_disadvantages_of_the_Mixed_security_style)

**この構成では mixed を使いません。** UNIX か NTFS のどちらかを選んでください。

FSx for ONTAP 側で S3 Access Point に Windows 識別情報を使う構成と UNIX 識別情報を使う構成の
どちらを採るかが、そのままファンアウト先のプロトコル選択と結びつく。

識別情報は、その SVM が名前解決できるユーザーであれば足りる。**どちらの型でも外部の
ディレクトリサービスは必須ではない。** UNIX 識別情報は LDAP や NIS を使わず SVM のローカルユーザーで、
Windows 識別情報は workgroup モードの CIFS サーバーに作ったローカルユーザーで、それぞれ読み書きが
通った実測がある（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-2-の前提--ap-に固定する-id-はファイルシステム側に実在していなければならない)）。workgroup モードは Active Directory ドメインが利用できない場合の
代替として公式に手順が示されている（[SMB server in a workgroup](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html)）。
ただし NTLM 認証のみで Kerberos に対応せず、GPO・VSS・SMB3 CA 共有なども対象外になる。

> **セキュリティに関する補足**: Active Directory 参加 SVM を選んだ場合は、S3 Access Point 経由の
> **すべてのデータ操作**に AD ドメインコントローラーへの到達性が必要になる。`HeadBucket` は
> AD が到達不能でも成功するため、疎通確認には使えない。到達性の確認は必ずデータ操作で行う。
> この挙動は姉妹リポジトリで検証済みとして扱っている（[検証状況](verification-status.md)）。
> **AD 参加を選ばなければ、この依存は生じない。**

## 同じ要件文が挙げているその他の前提

いずれも Azure NetApp Files のキャッシュボリューム要件の記載であり、この構成の主経路で
同じ条件が課されるかは未確認である。検討の入口として挙げておく。

- Cache の作成は REST API のみ（キャッシュ用のエンドポイント経由）
- Origin 側クラスタが ONTAP 9.15.1 以降
- Cache と Origin のプロトコル種別を一致させる
- 同一 Origin を共有する Cache 群で `globalFileLocking` を揃える。変更は Origin 側クラスタの
  CLI（`volume flexcache origin config modify`）で行う

## 決める順序

1. **利用拠点のプロトコルを決める** — NFS か SMB か。装置やアプリが決めているなら、それが答え
2. **Origin のセキュリティスタイルを決める** — 1 に対応するものを選ぶ。UNIX（NFS 主体）か NTFS（SMB 主体）の 2 択。mixed は使わない
3. **S3 Access Point の識別情報を決める** — 2 と整合させる。NTFS 側なら Windows 識別情報、
   UNIX 側なら UNIX 識別情報で、いずれも SVM が名前解決できるユーザーを先に作る。
   **Active Directory 参加を選んだ場合に限り、AD 到達性が定常的な依存になる。**
   識別情報は作成後に変更できないので、書き込み用と読み取り用を分けるならアクセスポイントも分ける
4. **Origin ボリュームを作る**
5. **Cache を作る** — この時点でセキュリティスタイルは選べない

1 から 3 のどれかを保留したまま 4 に進むと、5 で選択肢が消える。

## 不可逆・作り直しになる操作

| 操作 | 影響 |
|---|---|
| Origin のセキュリティスタイル変更 | Cache は削除して作り直すことになる（上記の前提が成り立つ場合） |
| S3 Access Point の `NetworkOrigin` | 作成後は変更できない。変更するには削除して作り直す（エイリアスが変わる）。到達性の条件は[サポート状況](support-matrix.md)にある |
| FlexCache の削除順序 | Cache を残したまま Origin 側を削除しない。ピアリングの削除は Cache と SVM ピアの解除が先 |
| SnapLock / 改ざん防止 Snapshot の有効化 | 取り消せない。**保持期間を明示した指示がない限り有効化しない**。詳細は [AGENTS.md](../../AGENTS.md) の不可逆操作の節 |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](architecture.md) | 収集層と配布層の全体像 |
| [サポート状況](support-matrix.md) | 最小バージョンと対応構成 |
| [検証状況](verification-status.md) | 何が検証済みで何が未検証か |
| [PoC チェックリスト](poc-checklist.md) | この節の未確認事項を実機で確かめる手順 |

---

<!-- lang-switcher:start -->
🌐 [日本語](design-first-decisions.md) | [English](../en/design-first-decisions.md) | [🏠 リポジトリトップ](../../README.md)
<!-- lang-switcher:end -->
