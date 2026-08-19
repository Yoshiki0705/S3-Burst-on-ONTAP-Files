# セキュリティ

## 脆弱性の報告

このリポジトリはドキュメントと CloudFormation / SAM のテンプレート集で、
稼働中のサービスを含みません。それでも、次のようなものは報告してください。

- テンプレートが過剰な権限を付与している、または安全でない既定値を持っている
- ドキュメントが安全でない手順を推奨している
- 秘密情報・アカウント ID・内部ホスト名がコミットに残っている

**公開の Issue には書かないでください。** GitHub の
[Security Advisories](https://github.com/Yoshiki0705/s3-burst-on-ontap-files/security/advisories/new)
から非公開で報告してください。

AWS のサービス自体、または ONTAP 製品自体の脆弱性は、それぞれの窓口へ報告してください。
このリポジトリの管理者は、そのいずれについても修正する立場にありません。

## このリポジトリの前提

| 項目 | 状態 |
|---|---|
| 実行時のサービス | なし。テンプレートは読者が自分のアカウントにデプロイする |
| 秘密情報 | 一切コミットしない。`gitleaks` が push とプルリクエストと週次で走る |
| 依存 | `requirements-dev.txt` でバージョンを固定。開発時のみ |
| GitHub Actions | すべてコミット SHA で固定（`make pinning` が検査） |
| 個人情報 | コミットしない。`make audit` が検査 |

## テンプレートを使う側の責任

雛形の `template.yaml` に含まれる IAM ポリシーは**プレースホルダー**です。
`s3:*` を `Deny` する形になっており、そのままでは動きません。
これは意図的で、動く広い権限を置くと、そのまま本番に届くためです。

デプロイする前に、そのパターンが実際に必要とする最小権限に置き換えてください。
FSx for ONTAP に対する S3 呼び出しでは、アクセスポイント形式の ARN
（`arn:aws:s3:<region>:<account>:accesspoint/<name>`、オブジェクト操作には `/object/*` を付ける）を
使います。**バケット形式の ARN（`arn:aws:s3:::<alias>`）では動きません**（[ARN・エイリアス・
virtual-hosted-style URI での参照](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/referencing-access-points-for-fsxn.html)）。サービスロールが自動生成したポリシーが
バケット形式で書かれていることがあり、その場合は `AccessDenied` になります。
機構の説明は[姉妹リポジトリの認可モデル](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/s3ap-authorization-model.md)にあります。

認可は二層です。AWS 側（IAM とアクセスポイントポリシー）と
ONTAP 側（ファイルシステム識別情報）の両方が許可する必要があります。
片方だけを絞っても、もう片方が広ければ実効権限は広いままです。

**AWS 側で絞るのは明示的な拒否です。** 同一アカウントでは identity-based ポリシーと
アクセスポイントポリシーが結合されるため、`Allow` を狭く書くことは絞り込みになりません
（[実測](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/security-governance/notes/access-point-authorization-layers.md#layer-1--結合で評価されることの帰結)）。

**VPC エンドポイントを経由する場合、そのエンドポイントポリシーも許可している必要があります。**
既定が全許可なので、絞っていない環境ではこの層の存在に気づきません。逆に絞ってある環境では、
アクセスポイントを追加したときにその ARN を許可対象へ追加しないと `AccessDenied` になります
（[ネットワークアクセスの設定](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)。AWS のドキュメント記載で、このリポジトリでは実測していません）。

## 不可逆操作

削除できなくする機能（SnapLock、改ざん防止 Snapshot、Object Lock、Vault Lock）を
このリポジトリのテンプレートは有効化しません。
有効化する場合は保持期間を明示した判断の上で行ってください。
検証環境も例外ではありません。削除できない検証リソースは長期の請求になり、
同居する他のリソースも動かせなくします。

背景と確認手順は [AGENTS.md](AGENTS.md) の該当節にあります。

## 未検証であることの扱い

このリポジトリの主張は段階が分かれています（[検証状況](docs/ja/verification-status.md)）。
中核の end-to-end は Cache 側も FSx for ONTAP という条件で検証済みで、主経路である
オンプレミス ONTAP Cache は未検証です。
未検証の記述を、セキュリティ上の保証として読まないでください。
本番環境に適用する前に、必ず自分の環境で確認してください。
