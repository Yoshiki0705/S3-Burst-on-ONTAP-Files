# S3 Access Point 経路で ONTAP の機能は使えるか

<!-- lang-switcher:start -->
🌐 [日本語](s3ap-interoperability.md) | [English](../../../en/reference/limits/s3ap-interoperability.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->

問いは 1 つだけである。**FSx for ONTAP の S3 Access Point をアタッチしたボリュームで、ONTAP の
機能は使えるのか。** 使えないなら、何がどう失敗するのか。

答えは実測で出ている。**測った範囲では、すべて使えた。**

| ONTAP の機能 | S3 Access Point 経路での結果 | 段階 |
|---|---|---|
| Qtree | 作れる。S3 のプレフィックスとして見え、PUT したオブジェクトが qtree の中に入る | 検証済み |
| Quota | qtree の tree クォータが S3 の PUT を拒否する | 検証済み |
| FlexClone（ボリューム単位） | クローンを作れ、**クローン自身に S3 Access Point を取り付けられる** | 検証済み |
| FlexClone（ファイル単位） | S3 経由で書いたファイルをクローンでき、**クローンもアクセスポイント経由のオブジェクトとして見える** | 検証済み |
| FlexGroup ボリューム | **S3 Access Point を取り付けられる。** PUT / GET / LIST とマルチパートが通る | 検証済み |
| FlexGroup のクローン | **クローンを作れる**（S3 Access Point を持つ FlexGroup から） | 検証済み |

いずれも 2026-08-26、ap-northeast-1、ONTAP 9.18.1P3D1、SINGLE_AZ_1 / 128 MBps で測った。
手順と対照は下記。

## この問いの出どころ

NetApp が公開している
[ONTAP S3 interoperability](https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-interoperability-concept.html)
の表は、**ONTAP S3 サーバ**（ONTAP がバケットを提供する機構）について、Qtree・Quota・FlexClone・
ONTAP S3 バケットを含む FlexGroup ボリュームのクローンを「非対応」と記載している。

FSx for ONTAP の S3 Access Point は AWS 側の機構で、取り付け先はバケットではなく**ボリューム**で
ある。取り付けると SVM 上に ONTAP の S3 サーバが立ち、アクセスポイント経由の I/O は ONTAP の
S3 プロトコルスタックを通る（実測）。だから同じ制約が出る可能性はあった。**出なかった。**

この表は問いの出どころとしてだけ扱う。**「ONTAP S3 で非対応と書かれているから、この経路でも
非対応」と読むことはできない。** 上の実測がその読みを否定している。逆向きも同じで、この表の
「対応」を S3 Access Point 経路の根拠にはしない。

FPolicy と監査については別の測定で結論が出ており、こちらは NetApp の記載と一致した。

| 機構 | S3 Access Point 経路 |
|---|---|
| FPolicy | **通知されない。`mandatory` 指定の同期ポリシーでも遮断されない**（NetApp も ONTAP S3 について非対応と記載） |
| ONTAP ネイティブ監査ログ | **記録される**（オブジェクト操作は `Source=HTTP`、LIST は `Source=S3`）。ただし要求者は残らない |
| ARP（バージョン 5.0） | **検知する** |

つまり「ONTAP の機能はこの経路では効かない」という一般化も誤りである。**機構ごとに答えが違う。**

## 測った手順

環境は上記のとおり。UNIX セキュリティスタイルの 1 GiB ボリューム 2 本（片方にアクセスポイント、
もう片方は対照）、NTFS ボリューム 1 本、400 GiB の FlexGroup 1 本。identity は UNIX / `root`。
すべて使い捨てで、測定後に削除した。

### Qtree

| 手順 | 結果 |
|---|---|
| アクセスポイントを取り付けたボリュームに qtree を作成 | 成功 |
| 対照: アクセスポイントを持たないボリュームに同じ qtree を作成 | 成功。**差は出ない** |
| `list-objects-v2 --delimiter /` | qtree が CommonPrefixes に現れる |
| qtree のプレフィックスへ PUT | 成功 |
| ONTAP 側で qtree の中身を確認 | 書いたファイルが qtree ディレクトリの中にある |

副産物: アクセスポイントを取り付けたボリュームの直下に、S3 レイヤーが作る内部ディレクトリ
`____NTAP_S3_MAPPING` が存在する。NFS / SMB から見えるので、収集層のボリュームを人が覗く運用では
これが見えることを知っておく必要がある。

### Quota

| 手順 | 結果 |
|---|---|
| qtree に tree クォータを設定（space 1 MiB、files 10）、ボリュームのクォータを有効化 | 成功 |
| `quota report` | rule が active。**S3 経由で書いたファイルが files used に計上されている** |
| 小さいオブジェクトを 15 個 PUT | **8 個成功、7 個拒否。** files used がちょうど 10/10 で止まった |
| 拒否時に S3 クライアントが受けた応答 | HTTP 507 `InsufficientCapacity` / `Maximum storage capacity of file system has been reached.` |
| 対照: files の上限を 10 → 50 に上げ、拒否された同一キー・同一ボディで再 PUT | **成功** |

対照が結論を支えている。上限を上げただけで同じ PUT が通ったので、拒否はクォータによるもので、
容量不足や権限の副作用ではない。

**エラーメッセージが原因を誤って伝える点は設計に効く。** ファイルシステムは満杯ではなく、
qtree のファイル数クォータに当たっただけである。507 と「ファイルシステムの容量上限」を見た
運用者はファイルシステムの拡張を検討してしまう。クォータを使うなら、この応答が何を意味するかを
runbook に書く必要がある。

### FlexClone

ボリューム単位とファイル単位の両方を測った。どちらも、アクセスポイントを取り付けたボリュームを
対象にしている。

#### ボリューム単位

| 手順 | 結果 |
|---|---|
| アクセスポイントを取り付けたボリュームの FlexClone を作成 | 成功。`is_flexclone=true`、`online`、親を記録 |
| 対照: アクセスポイントを持たないボリュームの FlexClone | 成功。**差は出ない** |
| クローンの中身 | S3 経由で書いたファイル、qtree の中身、`____NTAP_S3_MAPPING` すべて含む |
| **クローンにアクセスポイントを取り付け** | **成功。`Lifecycle=AVAILABLE`** |
| クローンのアクセスポイント経由で LIST / GET | **成功。256 MiB ファイルの sha256 が親と一致** |
| クローンのアクセスポイント経由で PUT | **成功。書いたオブジェクトは親側には現れない**（`HeadObject` が 404） |
| クローンが見せる時点 | 基底スナップショット時点。スナップショット後に親へ作ったファイルはクローンに無い |

収集したデータの複製を、元をコピーせずに作れる。NFS / SMB から読めるだけでなく、クローン自身の
アクセスポイントを立てて S3 からも読める。書き込みは親から独立している。

#### ファイル単位

`POST /api/storage/file/clone`（FlexClone のファイル単位クローン）を、S3 経由で書いたファイルに
対して実行した。

| 対象 | 結果 |
|---|---|
| ルート直下の 256 MiB ファイル | 成功 |
| プレフィックスの中のファイル（`/sub/nested.txt`） | 成功 |
| クローンのクローン | 成功 |
| 存在しないディレクトリを宛先にする | **失敗。ただし応答は 202 で、エラーは観測できない**（下記） |
| 事前に作ったディレクトリを宛先にする | 成功 |

ブロックが共有されていることは容量で確認した。**論理 1,350,942,720 B に対して物理
277,200,896 B。** 256 MiB のファイル 4 本をクローンして物理は約 23 MB しか増えていない。
コピーではない。

S3 側から見た結果が本題である。

| 確認 | 結果 |
|---|---|
| ファイルクローンがアクセスポイント経由の LIST に出るか | **出る。サイズも一致** |
| `HeadObject` | **成功。`StorageClass=FSX_ONTAP`** |
| クローン 4 本と元 1 本を S3 GET して sha256 比較 | **5 本すべて一致** |
| プレフィックス内のクローン（`sub/nested-clone.txt`） | **出る。内容一致** |
| クローンを S3 の PUT で上書き | **成功。元ファイルは変わらない** |

**ファイルクローンは S3 側から通常のオブジェクトとして扱える。** S3 が書いていないファイルでも
アクセスポイント経由で見え、読め、上書きできる。

**ただし失敗が観測できない。** `POST /api/storage/file/clone` は 202 とジョブ UUID を返すが、
その UUID は解決できない。

| 呼び出し | ジョブ UUID の取得 |
|---|---|
| `POST /storage/file/clone` | **404 `entry doesn't exist`。** ジョブ一覧 166 件を検索しても該当なし |
| 対照: `POST /storage/volumes`（ボリューム作成） | **200。`state=success`** |
| 対照: `POST /storage/volumes`（ボリュームクローン） | **200。`state=success`** |

対照が取れているので、これは権限の問題ではない。**ファイル単位クローンだけがジョブを残さない。**
存在しないディレクトリを宛先にした呼び出しも 202 を返し、実際には何も作られていなかった。
**成否は宛先ファイルを見て判定する必要がある。**

### FlexGroup

作成には条件がある。順に失敗して分かった。

| 手順 | 結果 |
|---|---|
| 既定のパラメータで作成 | 失敗。`Volumes of this type must be at least 50GB` |
| 50 GiB 相当で再試行 | 失敗。`Aggregates not matching FabricPool requirements: aggr1` |
| aggregate を明示して再試行 | 失敗。`Minimum size is "400GB"`（8 constituent × 50 GiB） |
| 400 GiB、aggregate 明示、`tiering.policy=none`、thin | **成功** |

FSx for ONTAP の API に FlexGroup を作る手段は無いので、ONTAP 側で作る。そのあとが本題である。

| 手順 | 結果 |
|---|---|
| FSx for ONTAP 側に `VolumeStyle=FLEXGROUP` として現れる | **現れる。`fsvol-` ID が付く** |
| **FlexGroup に S3 Access Point を取り付け** | **成功。`Lifecycle=AVAILABLE`** |
| PUT / GET / LIST | **成功。GET の内容が一致** |
| 12 MiB のマルチパートアップロード | **成功。`StorageClass=FSX_ONTAP`** |
| FlexGroup のスナップショットを作成 | 成功 |
| **その FlexGroup のクローンを作成** | **成功。`style=flexgroup`、`is_flexclone=true`、online** |

NetApp が「ONTAP S3 バケットを含む FlexGroup ボリュームのクローンは非対応」と記載している項目
そのものだが、S3 Access Point を持つ FlexGroup のクローンは作れた。

## この経路で実際に失敗したこと

制約は NetApp の表の側にはなく、別のところにあった。**測った範囲では、この 3 つが実際の落とし穴で
ある。**

### セキュリティスタイルと identity の不一致による、取り付け成功後の失敗

| 手順 | 結果 |
|---|---|
| NTFS セキュリティスタイルのボリューム + UNIX identity（`root`）で取り付け | **成功。`Lifecycle=AVAILABLE`** |
| その アクセスポイントへ PUT | **拒否。`AccessDenied`（本文は `Access Denied` のみ）** |
| 対照: 同じ identity・同じ呼び出し元・UNIX ボリューム | PUT / GET / LIST すべて成功 |
| この SVM の CIFS サーバ | **無い**。UNIX → Windows のマッピングが解決できない |

**`AVAILABLE` はファイルシステム層の健全性を意味しない。** 取り付けられることと使えることは別で、
IAM もアクセスポイントポリシーも通過したうえでファイルシステム層が拒否する。エラー本文は
`Access Denied` だけで、どの層が拒否したかを示さない。identity 層で拒否された場合は
`no identity-based policy allows ...` と出るので、**本文の違いが層の手がかりになる。**

WINDOWS identity を同じ SVM で試した場合は、取り付け自体が完了しない。

| 手順 | 結果 |
|---|---|
| CIFS サーバの無い SVM で WINDOWS identity を指定して取り付け | **失敗。`did not stabilize`（`NotStabilized`）でスタックがロールバック** |
| ロールバック後に取り付けが残るか | **残らない**。孤児にはならなかった |

### ONTAP 側で作ったものが AWS 側に現れるまでの待ち時間

ONTAP API で作ったボリュームは、AWS 側の `describe-volumes` にすぐには現れない。`fsvol-` ID が
無いと `AWS::FSx::S3AccessPointAttachment` も `create-and-attach-s3-access-point` も参照できない。

| 測定 | 結果 |
|---|---|
| 20 秒間隔・ギャップ無しで FlexGroup を観測 | **599 秒（約 10 分）で出現**、`fsvol-` ID 付き |
| 20 秒間隔・ギャップ無しで FlexClone ボリュームを観測 | **1,177 秒（約 19.6 分）で出現**、`fsvol-` ID 付き |
| 別の回（FlexVol と FlexClone） | 1,258 秒（約 21 分）の時点でまだ出現していない。その後の系列に穴があり、正確な出現時刻は不明 |

**3 回の観測が一致しないので、これは上限値ではない。** 10 分・19.6 分・21 分でまだ出ていない回が
ある。**桁は 10 分台**だが、待ち時間を固定値として設計に埋めるには足りない。AWS の記載は次の
とおりで、実測はその「数分」より長い。

> Amazon FSx periodically syncs with ONTAP to ensure consistency. If you create or modify volumes <!-- allow:naming verbatim AWS documentation; the wording is theirs -->
> using NetApp applications, it may take up to several minutes for these changes to be reflected in
> the AWS Management Console, AWS CLI, API and SDKs.
>
> — [Managing FSx for ONTAP resources using NetApp applications](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-resources-ontap-apps.html)

**当初この遅延を「現れない」と読み違えた。** 約 2.5 分の観測で「ONTAP API で作ったボリュームには
`fsvol-` ID が存在しない」と結論し、そこから「クローンにも FlexGroup にもアクセスポイントは
取り付けられない」と書いた。両方とも誤りで、待てば現れ、取り付けられる。2.5 分は AWS が記載する
「数分」の内側であり、**「まだ現れていない」と「現れない」を区別していなかった。**

### 逆向きにも遅れる junction path の反映

| 手順 | 結果 |
|---|---|
| ONTAP 側でクローンに junction path を設定 | 成功、`online` |
| 直後にアクセスポイントを取り付け | **失敗。** `Amazon FSx is unable to attach S3access point because the volume is not mounted.`（サービスの応答文をそのまま引用） <!-- allow:naming verbatim service error message --> |
| そのときの AWS 側の `JunctionPath` | `None`。ONTAP では設定済みなのに AWS 側にまだ来ていない |
| 代わりに `aws fsx update-volume` で設定 | 約 40 秒で AWS 側に反映 |
| 反映後に取り付けを再試行 | **成功** |

**エラーメッセージは正しいことを言っている。** AWS 側から見えている状態ではボリュームがマウント
されていない。誤っていたのは、ONTAP 側で設定したから AWS 側でも見えているはずだという前提である。
**書き込みは可能な限り AWS 管理面から行う。** 同じ設定が ONTAP 経由では 2 分待っても反映されず、
FSx for ONTAP の API 経由では約 40 秒だった。

### テアダウン: 無言で戻る削除

| 手順 | 結果 |
|---|---|
| `delete-volume` | `DELETING` を返してから、無言で `CREATED` に戻る。2 回とも同じ |
| 原因の在り処 | `describe-volumes` の `LifecycleTransitionReason` にのみ。`Failed to delete volume because it has one or more clones.` |
| 実際のクローン | 削除済み。ONTAP の **volume recovery queue** に残っていた |
| 親側のフラグ | `clone.has_flexclone` が `true` のまま |
| recovery queue を purge | フラグが `false` になり、同じ `delete-volume` が通った |

AWS 側の API だけを見るテアダウンでは詰まる。recovery queue はコンソールにも FSx for ONTAP の
API にも出ない。**成功レスポンスは成功の証拠ではない。** `DELETING` が返っても、数十秒後の状態で
判定する。

### テアダウン: アクセスポイントを外してもボリュームが消えない

これは別の測定（2026-08-28）で当たった。**アクセスポイントを取り付けたボリュームは、
アクセスポイントを全部外した後も ONTAP 側の削除を拒否する。**

```text
Cannot delete volume "..." in SVM "..." because it is associated with the following
object store NAS buckets: "amazon-fsx-fsvol-0123456789abcdef0"
```

| 確認したこと | 結果 |
|---|---|
| バケット名の由来 | **ボリューム ID と完全一致**（`amazon-fsx-<volume-id>`）。アクセスポイント単位ではなくボリューム単位に作られる |
| アクセスポイントを全部削除した後 | 拒否は続く。数時間後も同じ |
| ボリュームを online・マウント済みに戻す | 拒否は続く |
| アクセスポイントを再取り付けして正しい順序で外す | 拒否は続く。**アクセスポイントのライフサイクルとは独立している** |
| ONTAP `/protocols/s3/buckets` と `vserver object-store-server bucket show` | **どちらもこのバケットを列挙しない** |
| ボリュームの `is_object_store` | `false` |
| **`aws fsx delete-volume`** | **成功。ボリュームとバケットの両方が消えた** |

**ONTAP 側からは削除できず、AWS 側の `delete-volume` でしか消えない。** NetApp が文書化している
[NAS バケット構成の削除手順](https://docs.netapp.com/us-en/ontap/revert/remove-nas-bucket-task.html)
は `vserver object-store-server bucket delete` を使うが、**この経路では対象を列挙できないので
適用できない。**

リーダーの盲点も測れた。`/svm/svms` はこの SVM の S3 サーバ（`amazon-fsx-svm-...`）を `enabled` と
返すのに、`/protocols/s3/services` はこの SVM を列挙しない。**AWS が管理するオブジェクトは標準の
ONTAP S3 ビューから隠れている。** 「バケットが無い」と 2 つのリーダーで確認しても、両方が同じ
盲点を持っていた。

設計への含意は 1 つ。**S3 アクセスポイントを取り付けたボリュームのテアダウンは、AWS 側の API で
行う。** ONTAP 側の `volume delete` を前提にした手順書は、この経路では詰まる。`aws fsx
delete-volume` はボリュームに FSx for ONTAP のバックアップが有効であることを求める旨がドキュメントに
あるが、バックアップ無効のボリュームでも `SkipFinalBackup=true` で通った（実測）。

## まだ測っていないもの

| 項目 | 状態 |
|---|---|
| FlexClone の LUN 単位 | 未検証。LUN を作るには iSCSI の構成が必要で、この構成の経路にない |
| ONTAP 側で作ったボリュームの反映時間の上限 | 未検証。3 回の観測が一致していない |
| FabricPool 階層化 | 未検証。別のアグリゲート構成が必要 |
| QoS | 未検証 |
| 重複排除 / 圧縮 / コンパクション | 未検証 |
| SnapMirror | 未検証 |
| SnapLock / Object Lock | 未検証。**不可逆**。保持期間を名指しした指示なしに有効化しない |
| キャッシュ側ボリュームへの取り付け | 未検証。cluster peer と SVM peer が前提で、このリポジトリのテンプレートは作らない。なお ONTAP の FlexCache duality と、ボリュームへの S3 Access Point 取り付けは別の機構であり、一方の対応状況を他方の根拠にはしない |
| Vscan | 未検証 |

「未検証」は「できない」ではない。冒頭の表に並べた項目がいずれもそうだったとおり、この経路では
**測るまで分からない**。

## 出典

| 出典 | 何について |
|---|---|
| [アクセスポイントの制限事項](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html) | 同一リージョン、同一アカウント、ONTAP 9.17.1 以降 |
| [アクセスポイントのトラブルシューティング](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/troubleshooting-access-points-for-fsxn.html) | マウント済みボリュームであること |
| [アクセスポイントの互換性](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html) | 対応する S3 API |
| [NetApp アプリケーション経由の管理](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-resources-ontap-apps.html) | ONTAP 側の変更が AWS 側に反映されるまでの遅延 |
| [ONTAP S3 interoperability](https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-interoperability-concept.html) | ONTAP S3 サーバについての記載。この経路の結論ではなく、問いの出どころ |
| [S3 Access Point の上限値](s3-access-point.md) | このリポジトリがまとめた制約と段階 |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [ONTAP 上のオブジェクトアクセス](../glossary/object-access-on-ontap.md) | 「ファイルの上の S3」と呼ばれる機構の区別 |
| [S3 Access Point の上限値](s3-access-point.md) | 出典と段階つきの制約一覧 |
| [検証状況](../../verification-status.md) | 4 つの段階の定義と現状 |
| [s3-access-point-attachment パターン](../../../../patterns/collect/s3-access-point-attachment/README.md) | アクセスポイントを単独で管理するテンプレート |

<!-- lang-switcher:start -->
🌐 [日本語](s3ap-interoperability.md) | [English](../../../en/reference/limits/s3ap-interoperability.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->
