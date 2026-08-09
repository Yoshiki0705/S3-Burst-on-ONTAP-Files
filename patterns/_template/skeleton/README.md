# __PATTERN_TITLE__

<!-- 雛形。`make new-pattern AXIS=<axis> SLUG=<slug>` がこのディレクトリを複製し、
     __PATTERN_TITLE__ / __PATTERN_SLUG__ / __PATTERN_AXIS__ を置き換えます。
     置き換えたあと、この HTML コメントと「雛形のまま残っている項目」の節を削除してください。 -->

> 軸: `__PATTERN_AXIS__` — 収集（`collect`）/ 配布（`serve`）/ 組み合わせ（`pipelines`）のいずれか。
> 全体像は[構成の形](../../../docs/ja/architecture.md)にあります。

1 段落でこのパターンが何をするかを書いてください。「何を入力に、何を出力するか」と
「どのワークロードのどの部分を担うか」が分かる形にします。

## 前提

| 項目 | 値 |
|---|---|
| ONTAP バージョン | 収集側は 9.17.1 以降（S3 Access Point の要件） |
| セキュリティスタイル | 利用側のプロトコルに合わせる（[最初に決めること](../../../docs/ja/design-first-decisions.md)） |
| リージョン / アカウント | S3 Access Point とボリュームは同一リージョン・同一アカウント |
| 検証段階 | 未検証 / ドキュメント記載 / 検証済み のいずれかを書く（[検証状況](../../../docs/ja/verification-status.md)） |

S3 Access Point 自体は CloudFormation では作れないため、CLI で作成します。
位置引数の `--ontap-configuration` は解析が壊れやすいので、必ず JSON ファイルを渡してください。

```bash
aws fsx create-and-attach-s3-access-point \
  --cli-input-json file://create-ap.json
```

## デプロイ

```bash
cp params.example.json params.json    # 実際の値を入れる。params.json は追跡されない
sam build
sam deploy --parameter-overrides "$(python3 -c '
import json,sys
print(" ".join(f"{p[\"ParameterKey\"]}={p[\"ParameterValue\"]}" for p in json.load(open("params.json"))))
')"
```

`samconfig.toml.example` を `samconfig.toml` にコピーしてスタック名とリージョンを設定すると、
`sam deploy` の引数を省略できます。

## 確認

- [ ] `cfn-lint --non-zero-exit-code error template.yaml` がエラーゼロ
- [ ] `make test` が通る（`tests/` は自動で検出されます）
- [ ] 関数のログに wiring チェックの結果が出て、`missing` が空
- [ ] このパターンが実際に担う動作を確認した（何を確認したかを書く）

## 削除

削除の順序を書いてください。配布側を含むパターンでは順序が結果を変えます。

1. Cache ボリュームを解放する
2. SVM ピアを解除する
3. クラスタピアを解除する
4. `sam delete` でスタックを削除する

Origin 側を先に消さないでください。S3 Access Point を含む場合は、ボリュームより先に
アクセスポイントを外します。

## 不可逆な設定

このパターンが不可逆な設定に触れる場合、ここに列挙してください。触れない場合は
「なし」と書いてください。空欄にしないでください。

削除できなくする機能（SnapLock、改ざん防止 Snapshot、Object Lock、Vault Lock）は、
保持期間を明示した指示がない限り有効化しません。検証環境も例外ではありません。

## 実測値

実測していない性能値・コスト値は書きません。実測した場合は次を併記します。

計測日 / リージョン / ONTAP バージョン / ファイルシステムの世代と構成とスループット設定 /
オブジェクトサイズと並列度 / 何を測ったか。

## 雛形のまま残っている項目

<!-- 実装したら、この節ごと削除してください。 -->

- [ ] `template.yaml` の `Policies` がプレースホルダーの `Deny` のまま。最小権限に置き換える。
      FSx for ONTAP に対する S3 呼び出しはアクセスポイント形式の ARN が必要で、
      バケット形式の ARN では動きません。オブジェクト操作には `/object/*` を付けます
- [ ] `functions/handler.py` が wiring チェックのみ。`implemented` を `True` にできる実装に置き換える
- [ ] `tests/test_handler.py` の契約テストは残したまま、パターン固有のテストを足す
- [ ] `params.example.json` の値がプレースホルダーのまま
- [ ] この README の前提・確認・削除・不可逆な設定を埋める

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](../../../docs/ja/architecture.md) | 収集層と配布層の全体像 |
| [最初に決めること](../../../docs/ja/design-first-decisions.md) | Origin 作成前に決める項目 |
| [サポート状況](../../../docs/ja/support-matrix.md) | 対応状況と制約 |
| [検証状況](../../../docs/ja/verification-status.md) | 段階の定義 |
| [PoC チェックリスト](../../../docs/ja/poc-checklist.md) | 検証の順序 |
| [CONTRIBUTING.md](../../../CONTRIBUTING.md) | 執筆規約とゲート |
