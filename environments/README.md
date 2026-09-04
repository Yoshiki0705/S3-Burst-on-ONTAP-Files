# 検証環境のデプロイテンプレート

この構成を実機で確かめるための環境を、2 つに分けて用意しています。
手順は言語ごとのデプロイガイドにあります。

| ディレクトリ | 何をデプロイするか | ツール | ガイド |
|---|---|---|---|
| [`aws-origin/`](aws-origin/) | 収集側（Origin）: FSx for ONTAP、SVM、Origin ボリューム、VPC 内の検証ホスト | CloudFormation | [日本語](../docs/ja/deployment/aws-cloudformation.md) / [English](../docs/en/deployment/aws-cloudformation.md) |
| [`onprem-cache/`](onprem-cache/) | 配布側（Cache）: FlexCache ボリュームと読み取り専用の NFS エクスポート | Terraform | [日本語](../docs/ja/deployment/onprem-terraform.md) / [English](../docs/en/deployment/onprem-terraform.md) |

## 比較対象の環境

上の 2 つはこの構成そのものです。もう 1 つ、**比較のための環境**があります。

| ディレクトリ | 何をデプロイするか | ツール | ガイド |
|---|---|---|---|
| [`s3files-compare/`](s3files-compare/) | 比較対象: Amazon S3 Files のファイルシステムとマウントターゲット。収集側スタックの VPC・サブネット・検証ホストを引き継ぐ | CloudFormation | [日本語](../docs/ja/deployment/aws-s3files-compare.md) |

**このディレクトリは未実行の草案です。** 一度もデプロイしていません。
同じ要求に対する別の設計を、同一ホスト・同一クロックで測るために用意したもので、
数値は[比較検証](../docs/ja/verification/s3files-vs-flexcache.md)に入りますが、
実測前なので表は空です。

## プロトコル別の性能測定

Amazon EFS と FSx for ONTAP を、同じサブネットの同じクライアントからプロトコル別に測るための
環境です。

| ディレクトリ | 何をデプロイするか | ツール | ガイド |
|---|---|---|---|
| [`perf-matrix/`](perf-matrix/) | 測定用: EFS、第二世代 FSx for ONTAP、クライアント 9 台。既存の第一世代は流用する | CloudFormation | [手順](perf-matrix/README.md) |

**この環境は時間あたり約 $60 課金されます。** うち EFS Provisioned が $30.30、第二世代
FSx for ONTAP が $22.66 で、**どちらも EC2 のように停止では止まりません。**
全パターンが終わったら `perf-matrix/teardown.sh` を実行し、最後の検証行を確認してください。

**SMB はこの環境では測りません。** 既存 SVM が参加していたドメインコントローラが存在せず、
先にディレクトリを立てる必要があるためです。理由は[手順](perf-matrix/README.md)にあります。

破棄はバージョニングのために順序が決まっています。`teardown.sh` を使ってください。
バケットを空にせずに `delete-stack` すると、ファイルシステムを消し終えた状態で失敗します。

## ツールが 2 つである理由

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

**中核の end-to-end は、Cache 側も FSx for ONTAP という条件で検証済みです**
（[FlexCache 検証記録](../docs/ja/verification/flexcache-s3ap-visibility.md)）。
**このディレクトリの `onprem-cache/` が対象とする「Cache をオンプレミス ONTAP に置く形」は未検証です。**
検証済みの範囲と未検証の範囲は[検証状況](../docs/ja/verification-status.md)にまとめてあります。

確かめる順序は [PoC チェックリスト](../docs/ja/poc-checklist.md)にあります。
