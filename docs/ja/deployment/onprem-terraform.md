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

## 2. ピアリングを確立する

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

### 何が作られるか

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
