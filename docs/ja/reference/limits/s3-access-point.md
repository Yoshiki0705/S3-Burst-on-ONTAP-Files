# 上限値 — 収集層（FSx for ONTAP S3 Access Point）
<!-- lang-switcher:start -->
🌐 [日本語](s3-access-point.md) | [English](../../../en/reference/limits/s3-access-point.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->

数値は出典と段階を併記する。段階の定義は[検証状況](../../verification-status.md)にある。

## サイズ

| 項目 | 値 | 段階 | 備考 |
|---|---|---|---|
| 単一 `PutObject` | 5 GiB | 検証済み | 姉妹リポジトリでの実測。ドキュメントの「5 GB」表記に対して実測は 2 進接頭辞（5,368,709,120 バイト） |
| `UploadPart` 1 パート | 5 GiB | 検証済み | 同上 |
| オブジェクト全体 | 50 GiB | 検証済み | 同上。判定は `CompleteMultipartUpload` の時点で行われるため、全ペイロードの転送後に失敗する。クライアント側で先に検証する |

出典: 姉妹リポジトリ
[FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns)
の実測記録。

## 名前

| 項目 | 値 | 段階 | 出典 |
|---|---|---|---|
| S3 オブジェクト名 | 1024 バイト | ドキュメント記載 | [NAS データ要件](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html) |
| ファイル / ディレクトリ名 | 255 文字 | ドキュメント記載 | 同上 |
| 同名の衝突 | `part1/part2` と `part1/part2/part3` は NAS 上で同時に存在できない | ドキュメント記載 | 同上。前者がファイル、後者が同名ディレクトリを要求するため |
| ボリューム名 | 英数字とアンダースコアのみ | ドキュメント記載 | — |

スラッシュを含まない名前はすべてルートディレクトリに集まる。数が多いと性能問題になる。
上記出典は、NAS フレンドリでない名前を多用するアプリにはオブジェクトストアのほうが適すると
明記している。

## 構成上の前提

| 項目 | 値 | 段階 | 出典 |
|---|---|---|---|
| 最小 ONTAP バージョン | 9.17.1 | ドキュメント記載 | [制限事項](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html) |
| リージョン | アクセスポイントとボリュームが同一リージョン | ドキュメント記載 | 同上 |
| アカウント | アクセスポイントとボリュームが同一アカウント | ドキュメント記載 | 同上 |
| `NetworkOrigin` | 作成後は変更できない | ドキュメント記載 | 同上。**到達性は origin の種別ではなく呼び出し元の位置とルーティングで決まる。** Gateway エンドポイントは VPC 内で発生したトラフィックだけをルーティングし、VPN / Direct Connect / ピア VPC / Transit Gateway 経由の呼び出しには Interface エンドポイントが必要（[ネットワークアクセス](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)） |
| 認可 | AWS 側と ONTAP 側の両方が許可する必要がある | ドキュメント記載 | [二層認可](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/s3-ap-manage-access-fsxn.html) |
| アクセスポイントポリシーのサイズ | ドキュメント上の上限は 20 KB。**判定は正規化後の文書に対して行われる** | ドキュメント記載 / **別環境での実測** | 24,620 B は受理、24,861 B は `MalformedPolicy: Normalized policy document exceeds the maximum allowed size`。境界は書き方で動くので**手元の JSON のバイト数を予算にできない**。FSx API がフィールドとして受け付ける 200,000 文字は実効上限ではない（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#ポリシーサイズの上限は正規化後で判定される)。ONTAP 9.18.1P3D1、2026-08-17〜18、`ap-northeast-1`。**このリポジトリでは測っていない**） |

## ネットワークで絞るときに効く条件キー

この構成は収集の書き込み経路を 1 本にするので、送信元での絞り込みを設計に入れることがある。
**条件キーはリクエストに載っているときしか比較できない。** 載らない条件キーで `Allow` を書くと
その文は成立せず、`Deny` を書くと当たらない。**`Allow` 側と `Deny` 側で結果が反転する。**

| 条件キー | リクエストに載る条件 |
|---|---|
| `aws:SourceVpc` / `aws:SourceVpce` / `aws:VpcSourceIp` | **VPC エンドポイントを経由するときだけ** |
| `aws:SourceIp` | **VPC エンドポイントを経由しないときだけ** |

出典は[ネットワークアクセスの設定](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)。
両者は相互排他で、**エンドポイント経由のリクエストを `aws:SourceIp` では絞れない**。
`aws:VpcSourceIp` は大文字小文字を**区別する**。

**`Allow` の `Condition` に書いても絞り込みにならない。** 同一アカウントでは identity-based
ポリシーと結合されるため、絞るには逆条件の**明示的な拒否**が要る。AWS も両方の文が必要だと
記載している。**ただし `VPC` origin のアクセスポイントでは不要で**、`aws:SourceVpc` が束縛先の
VPC と一致しないリクエストを拒否する明示的な拒否と同等に振る舞う（同出典）。

この節は AWS のドキュメント記載である。このリポジトリでは実測していない。
実測されているのは `aws:SourceVpce` が S3 ゲートウェイエンドポイント経由で埋まることだけで、
[条件キーの実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#条件キーはリクエストに載っているときしか比較できません)にある。

## 監査で追えるものと追えないもの

ONTAP のファイルアクセス監査は S3 Access Point 経由のアクセスも記録するが、**記録される主体は
アクセスポイントに固定した識別情報**で、呼び出し元の IAM プリンシパルではない。
下の 4 点は、監査要件がある場合に設計を変える。

| 追えないもの | 記録される値 | 設計への影響 |
|---|---|---|
| 呼び出し元の IAM プリンシパル | `SubjectUserSid` に AP の識別情報の SID。`SubjectUserName` と `SubjectDomainName` は **`Not Present`**（名前解決されない） | 特定には AWS CloudTrail との突き合わせが要る。**用途ごとに AP を分けることが監査の粒度を決める** |
| 呼び出し元のアドレス | `SubjectIP` は AWS のサービス側アドレス。1 クライアントの連続 2 リクエストで**別の値**になった | 送信元 IP で絞り込む監査要件はこの経路では満たせない |
| ローカルユーザーかどうか | `SubjectUserIsLocal` が、実際にはローカルの Windows ユーザーに対して `false` | このフィールドを判定条件に使えない |
| UNIX 実効スタイルのボリュームの操作 | SVM で監査を有効化しても**記録が 1 件も出ない**（同一 SVM・同一設定の NTFS ボリュームでは記録あり）。mode bits は監査情報を持たないため、対象を指定する **ACE（SACL）が必要** | UNIX ボリュームで監査が要件なら、有効化だけでは足りない |

いずれも[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#監査ログには誰が記録されるか)（`WINDOWS` タイプの AP、ONTAP 9.18.1P3D1、2026-08-17〜18、`ap-northeast-1`。
UNIX ボリュームの件は[この節](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#unix-セキュリティスタイルのボリュームでは監査を有効化しても記録されない)）。**このリポジトリでは測っていない。**
AD グループで認可を分けても、監査は AP に紐づく 1 つの識別情報として記録される。

## 対象外の機能

すべて[対応表](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)の記載である。

| 機能 | 状態 |
|---|---|
| イベント通知 | 対象外。ポーリングまたは FPolicy を検討する |
| ライフサイクル | 対象外 |
| バージョニング（Object Versioning、`ListObjectVersions`） | 対象外 |
| Object Lock | 対象外。WORM が要るなら SnapLock |
| Object Annotations | 対象外 |
| Requester Pays | 対象外 |
| Static Website Hosting | 対象外 |
| 多要素認証（MFA delete） | 対象外 |
| 条件付き書き込み | 対象外 |
| `Presign` | 対応表では非対応。**実測では `PutObject` / `HeadObject` / `GetObject` の 3 つとも成功**（[検証記録](../../verification/s3ap-operations.md)、2026-08-19。SigV4 / SigV2 の両方）。測定は対応表と逆向きであり、**対応表が非対応としている間は依存させない**（[設計ガイド](s3ap-design-guide.md#presigned-url)） |
| ACL | `bucket-owner-full-control` 以外は対象外。他の値は `InvalidArgument` |
| ストレージクラス | `FSX_ONTAP` のみ |
| サーバー側暗号化 | `SSE-FSX` のみ。`SSE-S3` / `SSE-KMS` は指定できない |
| Block Public Access | **常に有効で、変更できない**（[アクセス管理](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/s3-ap-manage-access-fsxn.html)） |

### 完全性の検証に効く 2 点

| 項目 | 内容 |
|---|---|
| ETag | オブジェクト内容のハッシュだが、**MD5 ダイジェストではない。** メタデータの変更では変わらない |
| チェックサム | アップロード時に指定すると転送中の検証には使われるが、**値はボリュームに保存されず応答にも返らない。** ダウンロード時の検証には使えない |

収集パイプラインが完全性を ETag やチェックサムで担保している場合、この 2 点は設計に直接効く。

### マルチパートアップロードの副作用

| 項目 | 内容 |
|---|---|
| 未完了パートとバックアップ | 進行中（未完了）のマルチパートのパートは、ボリュームのバックアップに含まれない |
| 未完了パートと容量メトリクス | 宛先ボリュームの `StorageUsed` には現れないが、親ファイルシステムの `StorageUsed` には現れる |
| 完了後のパート情報 | 完了すると各パートのメタデータは保持されない。`GetObjectAttributes` でのパート情報取得も、パート番号単位のダウンロードもできない |

## 配布層（FlexCache）

| 項目 | 値 | 段階 | 備考 |
|---|---|---|---|
| Origin あたりの Cache 数 | AWS ドキュメントは Origin ボリュームが 10 を超える場合に write-around を推奨 | ドキュメント記載 / 挙動は未検証 | ファンアウト数の設計に影響する可能性がある |
| 対応構成 | 3 通り | ドキュメント記載 | [移植性](../../portability.md)に一覧 |
| 書き込みモード | write-around (既定) と write-back (ONTAP 9.15.1 以降) | ドキュメント記載 | [FlexCache での複製](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)。write-around は Origin 確定後に応答、write-back は Cache 確定後に非同期で Origin へ |
| Cache の階層化 | 不可 | ドキュメント記載 | [対応機能一覧](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html)。FabricPool の Origin を Cache できるが、Cache ボリューム自体は階層化されない |
| Cache のサイジング | Origin の最低 10% を推奨、作成時の既定値も 10% | ドキュメント記載 | [サイジング指針](https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html) |
| セキュリティスタイル | Cache 作成時に Origin から継承される項目として扱われる | 未検証 | 根拠は Azure NetApp Files のキャッシュボリューム要件。この構成の主経路では未確認（[最初に決めること](../../design-first-decisions.md)） |

## 書かない数値

性能値は、実測して環境を併記できるまで書かない。
環境の併記がない数値は再現できないので、比較にも見積りにも使えない。
必要な項目は[検証状況](../../verification-status.md)にある。

コストについては、単価と試算を分けて扱う。単価は AWS Price List API から取得した値を
リージョンと適用開始日つきで[FinOps の費用構造](../comparison/finops-s3-vs-s3ap.md)に置いている。
そこから出る月額は使用量の仮定に依存するため、試算として扱い実測と混ぜない。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [S3 AP 設計ガイド](s3ap-design-guide.md) | 対応オペレーション詳細、並行度設計、ディレクトリ設計、マルチプロトコル一貫性 |
| [サポート状況](../../support-matrix.md) | 制約の全体像 |
| [検証状況](../../verification-status.md) | 段階の定義と現在の状態 |
| [構成の形](../../architecture.md) | この構成が解かないこと |

---

<!-- lang-switcher:start -->
🌐 [日本語](s3-access-point.md) | [English](../../../en/reference/limits/s3-access-point.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->
