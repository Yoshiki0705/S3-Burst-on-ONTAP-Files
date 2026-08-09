# 検証環境のデプロイテンプレート

この構成を実機で確かめるための環境を、2 つに分けて用意しています。
手順は言語ごとのデプロイガイドにあります。

| ディレクトリ | 何をデプロイするか | ツール | ガイド |
|---|---|---|---|
| [`aws-origin/`](aws-origin/) | 収集側（Origin）: FSx for ONTAP、SVM、Origin ボリューム、VPC 内の検証ホスト | CloudFormation | [日本語](../docs/ja/deployment/aws-cloudformation.md) / [English](../docs/en/deployment/aws-cloudformation.md) |
| [`onprem-cache/`](onprem-cache/) | 配布側（Cache）: FlexCache ボリュームと読み取り専用の NFS エクスポート | Terraform | [日本語](../docs/ja/deployment/onprem-terraform.md) / [English](../docs/en/deployment/onprem-terraform.md) |

## なぜツールが 2 つなのか

**収集側は AWS の中だけで完結します。** FSx for ONTAP、SVM、ボリューム、検証ホスト、IAM、
Secrets Manager はすべて AWS のリソースなので、CloudFormation で 1 スタックになります。

**配布側は AWS の外にあり得ます。** ファンアウト先はオンプレミスの ONTAP、ONTAP Select、
あるいは別リージョンの FSx for ONTAP です。ONTAP を相手にする以上、AWS の
コントロールプレーンでは記述できません。Terraform の ONTAP プロバイダを使います。

分けたことの副産物として、**片方だけ差し替えられます。** 収集層を AWS の外に移しても
配布側の記述は変わらず、逆も同じです（[移植性](../docs/ja/portability.md)）。

## この 2 つがカバーしていないもの

| 項目 | なぜ含めないか |
|---|---|
| クラスタピア / SVM ピア | 2 つのクラスタの intercluster LIF 間に IP 到達性が必要で、VPC 間なら VPC ピアリングか Transit Gateway とルートが前提になります。ネットワーク構成はこのリポジトリの外で管理されるものなので、勝手に作りません。**FlexCache の作成が失敗する原因として最も多いのがこれです** |
| S3 Access Point | CloudFormation に FSx for ONTAP のボリュームへ接続するリソースがありません。CLI で作成します（`aws-origin/access-point.example.json`）。1 回の API 呼び出しのために Lambda をデプロイの信頼経路に入れるのは割に合いません |
| Active Directory | NTFS / SMB を使う場合に必要ですが、参加の失敗は原因が分かりにくく、テンプレートに隠すと切り分けが難しくなります |
| 不可逆な機能 | SnapLock、改ざん防止 Snapshot は**一切有効化しません**。有効化するとボリューム・SVM・ファイルシステム全体が保持期間中削除できなくなり、検証環境はそれを置く場所として最悪です |

## 費用について

どちらも課金されるリソースを作ります。**使い終わったら消してください。**
削除の順序は配布側 → ピアリング → 収集側です。逆順にすると消せないものが残ります。

- SSD 容量とスループットは**確保した量**に対して課金されます（使った量ではありません）
- FlexCache のボリュームは疎で、実際に読まれた分だけを保持します。サイズは上限であって割り当てではありません
- 検証ホストは EC2 の通常料金です

実測していない金額はこのリポジトリには書きません。見積りは
[AWS Pricing Calculator](https://calculator.aws/) でご自身の構成に対して出してください。

## 検証状況

**この構成の中核はまだ未検証です。** S3 Access Point 経由で書いたオブジェクトが
FlexCache の Cache ボリューム側でいつ見えるかは確かめていません。
Origin ボリューム自体を両プロトコルから読み書きする部分は実測済みです
（[検証記録](../docs/ja/verification/s3ap-nfs-visibility.md)）。両者は別の問いです。

確かめる順序は [PoC チェックリスト](../docs/ja/poc-checklist.md)にあります。
