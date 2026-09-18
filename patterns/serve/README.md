# patterns/serve/ — 空であることの説明

**このディレクトリに実装はありません。** 数えて 0 なので、README がそれを「0 件」と書くのか
「読み取りが壊れている」のかを区別できるようにしておきます。**意図的に 0 件です。**

## 空である理由

**配る側の中心的な操作に AWS API がありません。**

| 操作 | どこにあるか | CloudFormation / SAM で書けるか |
|---|---|---|
| cluster peer の作成 | ONTAP（REST / CLI） | **書けない** |
| SVM peer の作成と受諾 | ONTAP | **書けない** |
| FlexCache ボリュームの作成 | ONTAP | **書けない** |
| ジャンクションパスの設定・解除 | ONTAP | **書けない** |
| 消費側のエクスポートポリシー | ONTAP | **書けない** |

`patterns/` の単位は**1 つの `template.yaml` = 1 つのデプロイ可能なパターン**です
（`make counts` はそれを数えます）。配る側はテンプレート 1 枚で表せないので、
**この軸に置くものがまだ決まっていません。**

## 現在の置き場所

| 目的 | 場所 | 形 |
|---|---|---|
| 拠点側に FlexCache を作る | [`environments/onprem-cache/`](../../environments/onprem-cache/) | **Terraform**（ONTAP プロバイダ） |
| ピアリングと FlexCache の手順 | [配布側のデプロイ](../../docs/ja/deployment/onprem-terraform.md) | 手順書（踏んだ 5 点つき） |
| origin 側の SG をピア向けに開ける | [`environments/aws-origin/`](../../environments/aws-origin/) の `AllowFlexCachePeering` | CloudFormation |
| FlexCache の実測 | [スループット・IOPS・並列度](../../docs/ja/verification/throughput-iops-concurrency.md) | 測定記録 |

**ピアリングはこのリポジトリが作りません。** 2 つのクラスタのインタークラスタ LIF 間に
IP 到達性が必要で、それはネットワーク構成（VPC ピアリング、Transit Gateway、専用線）の側にあり、
**利用者の既存の経路設計に属します。**

## ここに置くとしたら何か（未決）

**決まっていないことを、決まっていないと分かる形で残します。**

- **Terraform モジュールを `patterns/serve/<slug>/` に置く案。** `patterns/` の規約が
  `template.yaml` を前提にしているので、規約側を変えることになります
- **SSM ドキュメント + Automation で ONTAP REST を叩く案。** CloudFormation から起動できますが、
  **失敗時の状態が CloudFormation の管理外に残ります**（FlexCache の削除は専用経路で、
  先に unmount と offline が必要）
- **カスタムリソース（Lambda）で ONTAP REST を叩く案。** 削除順序の固定を Lambda に持たせる
  ことになり、**スタック削除が Lambda の可用性に依存します**

**どれも試していません。** 現状は「配る側は Terraform、集める側は CloudFormation」で分ける形
（[環境テンプレートの索引](../../environments/README.md)）を採っています。
