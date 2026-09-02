# 配布側のデプロイ（AWS 以外 / Terraform）

<!-- lang-switcher:start -->
🌐 [日本語](onprem-terraform.md) | [English](../../en/deployment/onprem-terraform.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->

この構成の配布側 — FlexCache のボリュームと、読み取り専用の NFS エクスポート — を作ります。
設定は [`environments/onprem-cache/`](../../../environments/onprem-cache/) です。

収集側を先に作ってください（[収集側のデプロイ](aws-cloudformation.md)）。
FlexCache は Origin が存在しないと作れません。

## 所要時間

| 手順 | 目安 |
|---|---|
| 1. 前提の確認 | 10 分 |
| 2. ピアリングの確立 | 20〜60 分（ネットワーク構成によります） |
| 3. `terraform apply` | 5 分 |
| 4. マウントと確認 | 10 分 |
| 5. 削除 | 10 分 |

## 1. 前提

- 収集側の Origin ボリュームが存在すること
- 配布側の ONTAP クラスタがあること。オンプレミスの AFF / FAS、ONTAP Select、
  または別の FSx for ONTAP です

  > **対応構成に関する補足**: AWS が明記している FSx for ONTAP の FlexCache 対応構成は
  > 3 通りだけで、FSx for ONTAP を Origin とする場合の Cache は
  > **オンプレミス ONTAP と FSx for ONTAP のみ**です。Cloud Volumes ONTAP / ONTAP Select /
  > Azure NetApp Files / Google Cloud NetApp Volumes を Cache にできるかは**未確認**です。
  > 「ONTAP ベースだから動く」とは言えません（[移植性](../portability.md)）。

- **Terraform を配布側クラスタの管理エンドポイントに到達できる場所から実行すること。**
  Cache が FSx for ONTAP の場合、そのエンドポイントは VPC 限定です。手元の端末から実行すると
  ネットワークのタイムアウトになり、設定の誤りには見えません
- `terraform` 1.9 以降

## 2. ピアリングの確立

**この設定はピアリングを作りません。** クラスタピアと SVM ピアが先に必要です。

必要なものは、2 つのクラスタの intercluster LIF 間の IP 到達性です。VPC が別なら
VPC ピアリングか Transit Gateway と、**両側のルート**が前提になります。
ネットワーク構成はこのリポジトリの外で管理されるものなので、勝手に作りません。

**FlexCache の作成が失敗する原因として最も多いのがこれです。** しかもエラーメッセージは
権限や接続の問題を指すことが多く、ピアリングの不足を名指ししてくれません。
apply が失敗したら、まずピアリングを確認してください。

```bash
# 配布側クラスタで
cluster peer show
vserver peer show
```

### ピアリングと FlexCache 作成で実際に踏んだ 5 点

FSx for ONTAP を 2 つ用意し、REST API で一連の手順を通した記録です
（[実測記録](../verification/throughput-iops-concurrency.md#flexcache-経由の読み取り)、2026-09-01、
ONTAP 9.18.1P5）。**エラーメッセージが原因を名指ししない箇所が続きます。**

| 症状 | 実際の原因 |
|---|---|
| `Aggregates not matching FabricPool requirements: aggr1` | **`use_tiered_aggregate` が既定の false。** FSx for ONTAP の aggregate は FabricPool 付きなので、既定では「非 FabricPool の aggregate を探して見つからない」動作になる。**true を明示すると通る**。メッセージは aggregate を名指しし、フラグには触れない |
| `Volume ... results in a volume that is too small - 20GB` | **FlexCache ボリュームの最小サイズは 50 GB。** 20 GiB を指定して失敗した |
| `The value "180" is invalid for field "return_timeout" (<0..120>)` | `return_timeout` の上限は 120 |
| SVM ピアが `pending` のまま進まない | **Origin 側で明示的に受諾が必要。** `PATCH /api/svm/peers/{uuid}` に `{"state":"peered"}` を送る。作成側は `initiated`、相手側は `pending` になる |
| ONTAP REST が HTTP 401 と `User is not authorized.` を返す | **認証の不一致で、権限の問題ではない。** 生成した fsxadmin パスワードが実効パスワードになっていなかった。詳細は[検証状況](../verification-status.md)の該当行 |

削除にも順序があり、**各段が次を名指ししないメッセージで止めます。**

1. **ONTAP 側でジャンクションを外す**（`PATCH /api/storage/volumes/{uuid}` に `{"nas":{"path":""}}`）。
   クライアントの `umount` とは別物で、これを飛ばすと
   `Volume ... must be unmounted before being taken offline` で止まります
2. FlexCache を削除する
3. **SVM ピアを削除し、消えるまで待つ。** 削除は非同期なので、待たずに次へ進むと失敗します
4. クラスタピアを削除する。SVM ピアが残っていると
   `SVM peering relationships exist with the cluster` で拒否されます

**確認は削除の戻り値ではなく件数で行ってください。** 認証が失敗しているだけの状態でも
「対象が見つからない」と読める出力になります。実際にこの罠を踏み、シークレットを読めない
ホストで実行して「FlexCache は存在しない」と誤って報告しました。

### cache が別リージョンにあるときに追加で踏む 3 点

同じ手順をリージョンを跨いで通した記録です（origin は ap-northeast-1、cache は ap-northeast-3、
リージョン間 VPC ピアリング。[実測記録](../verification/throughput-iops-concurrency.md#リージョンを跨いだ-flexcache読み手が遠い場合)）。
**同一リージョン内では起きない 3 点が出ます。**

| 症状 | 実際の原因と対処 |
|---|---|
| ONTAP REST が空応答を返し、`curl` は成功する | **FSx for ONTAP の管理エンドポイントの DNS は、そのファイルシステムの VPC の内側でしか引けません。** リージョン間 VPC ピアリングはプライベートホストゾーンを運びません。対処は名前ではなく IP を使うことです（下記） |
| セキュリティグループのルールを相手側 SG の ID で書けない | **リージョンを跨いだピアリングでは SG 参照が使えません。** CIDR で書きます。必要なのは intercluster の **11104-11105**、ONTAP REST の **443**、NFS の **2049** です |
| ホストが相手リージョンの Secrets Manager を読めない | ホストロールは自分のスタックのシークレットしか許可していません。**インラインポリシーで明示的に許可**します。**スタック削除の前に外さないと、ロールの削除が失敗します** |

管理 IP と intercluster IP は API から取れます。**ONTAP 側の LIF を引く必要もなくなります。**

```bash
aws fsx describe-file-systems --file-system-ids <fs-id> --region <cache region> \
  --query 'FileSystems[0].OntapConfiguration.Endpoints.{Management:Management.IpAddresses,Intercluster:Intercluster.IpAddresses}'
```

**この 3 点はすべて「作成が失敗する」ではなく「何も起きない」形で出ます。** 空応答を認証の
失敗や対象の不在と読み違えやすいので、まず**名前ではなく IP で 1 回叩いて**切り分けてください。

## 3. `terraform apply`

```bash
cd environments/onprem-cache
cp terraform.tfvars.example terraform.tfvars    # terraform.tfvars は追跡されません
# 値を埋める

export TF_VAR_cache_cluster_password="$(aws secretsmanager get-secret-value \
  --secret-id <secret-id> --query SecretString --output text | jq -r .password)"

terraform init
terraform plan
terraform apply
```

**パスワードは `terraform.tfvars` に書かないでください。** Terraform は変数の値を
`sensitive` を含めて state ファイルに平文で書きます。環境変数で渡せば、
読める場所が 2 か所ではなく 1 か所になります。state 自体も暗号化とアクセス制御のある
バックエンドに置いてください。

`allowed_clients` には利用拠点のネットワークを指定します。既定値はありません。
エクスポートルールはアクセス制御の判断であり、`0.0.0.0/0` は変数の検証で拒否されます。

### 作られるリソース

| リソース | 内容 |
|---|---|
| FlexCache ボリューム | Cache ボリュームは FlexCache の作成と同時にできます。**別にボリュームを作りません** |
| エクスポートポリシー | 読み取り専用。`rw_rule` と `superuser` は `none` です |

FlexCache は疎です。実際に読まれたブロックだけを保持し、Origin の複製ではありません。
`cache_volume_size_gb` は**上限**であって割り当てではありません。

> **サイズに関する補足**: 既定値の 50 GB は、FSx for ONTAP における FlexCache の最小
> ボリュームサイズとして姉妹リポジトリに記録されている値です。**このリポジトリでは
> 未検証**なので、出発点として扱ってください。クラスタがより小さい値を受け付けるなら
> その分安くなります。

書き込みモードは既定のままにしてあります。writeback を有効にすると、S3 Access Point 経由の
書き込みと Cache 側の書き込みが同じファイルに当たったときに Cache のダーティデータが
破棄されます。この構成では書き込みは Origin に集約するので、有効にする理由がありません。

## 4. マウントと確認

利用拠点のクライアントからマウントします。

```bash
sudo mount -t nfs -o nfsvers=3,actimeo=0 <cache-svm-nfs-ip>:/cache_vol /mnt/cache
```

`terraform output mount_command` に両方の形式が出ます。

**マウントオプションで見え方が変わります。** Linux の既定（`acdirmin=30` / `acdirmax=60`）では、
クライアントが既に一覧を取得したディレクトリに現れたファイルが最大 1 分見えないことがあります。
これは収集側で実測しています（[検証記録](../verification/s3ap-nfs-visibility.md)）。

> **未検証であることの明示**: S3 Access Point 経由で書いたオブジェクトが Cache 側の NFS で読めることは、
> **Cache 側も FSx for ONTAP という条件で検証済みです**
> （[FlexCache 検証記録](../verification/flexcache-s3ap-visibility.md)）。
> **このガイドが対象とするオンプレミス ONTAP を Cache にした場合は未検証です。**
> 経路の遅延も、セキュリティスタイルの継承も、そこで初めて確かめられます。
> ここで観測した値は[検証状況](../verification-status.md)に環境情報と併せて記録してください。
> 否定的な結果も同じ価値があります。

## 5. 削除

**順序が結果を変えます。**

```bash
terraform destroy
```

そのあと、収集側より先に次を解除します。

1. SVM ピア
2. クラスタピア
3. VPC ピアリング / Transit Gateway のアタッチメント
4. 収集側のスタック（[収集側のデプロイ](aws-cloudformation.md)）

`terraform destroy` が消すのは Cache ボリュームとエクスポートポリシーだけです。
ここで作っていないピアリングは、ここでは消えません。

## うまくいかないとき

| 症状 | 見るところ |
|---|---|
| `terraform init` がプロバイダを取得できない | レジストリへの到達性。プロバイダはバージョン固定です |
| apply が権限エラーや接続エラーで失敗する | **まずピアリング**。エラーはピアリング不足を名指ししません |
| 到達できない / タイムアウト | Cache が FSx for ONTAP なら管理エンドポイントは VPC 限定です。VPC 内から実行してください |
| 証明書の検証で失敗する | ラボの自己署名証明書なら `validate_certs = false` を**意図的に**指定します。既定を緩めないでください |
| セキュリティスタイルの差分が毎回出る | Cache 側では設定できません。Origin 側で決めます |
| Cache に書けない | エクスポートポリシーが読み取り専用です。意図どおりです。書き込みは Origin の S3 Access Point へ |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [収集側のデプロイ](aws-cloudformation.md) | Origin 側 |
| [最初に決めること](../design-first-decisions.md) | セキュリティスタイルとプロトコル |
| [移植性](../portability.md) | 対応構成と未確認の組み合わせ |
| [検証記録](../verification/s3ap-nfs-visibility.md) | 実測値と測定条件 |
| [PoC チェックリスト](../poc-checklist.md) | 確かめる順序 |

---

<!-- lang-switcher:start -->
🌐 [日本語](onprem-terraform.md) | [English](../../en/deployment/onprem-terraform.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
