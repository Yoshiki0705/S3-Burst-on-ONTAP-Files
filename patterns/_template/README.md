# パターンの雛形

新しいパターンは `skeleton/` を複製して作ります。手でコピーせず、スクリプトを使ってください。

```bash
make new-pattern AXIS=collect SLUG=s3ap-ingest
```

`AXIS` は `collect` / `serve` / `pipelines` のいずれか、`SLUG` は英小文字・数字・ハイフンで
3〜40 文字です。`patterns/<AXIS>/<SLUG>/` が作られ、`__PATTERN_AXIS__` /
`__PATTERN_SLUG__` / `__PATTERN_TITLE__` が置き換わります。

## なぜ `skeleton/` を挟むのか

複製元と複製先の**ディレクトリの深さを揃える**ためです。

パターンは `patterns/<axis>/<slug>/` に置かれるので、リポジトリのルートまでは 3 つ上がります。
雛形の中身を `patterns/_template/` に直接置くと 2 つ上がるだけになり、
`../../../docs/ja/architecture.md` のようなリンクが雛形の側では壊れます。
逆に雛形側で正しくすると複製先で壊れます。

`skeleton/` を 1 階層挟むと両方が `patterns/<なにか>/<なにか>/` の形になり、
**相対リンクを書き換えずに複製できます。** リンク検査（`make links`）は雛形の側も
検査するので、複製先だけで壊れるリンクは残りません。

翻訳で同じ考え方を使っています。日本語版と英語版を同じ深さに置くので、
翻訳は「コピーして本文を置き換える」だけで済み、相対リンクは 1 文字も変わりません。

## 中身

| ファイル | 役割 |
|---|---|
| `skeleton/template.yaml` | 単体でデプロイできるテンプレート。1 パターン 1 テンプレート |
| `skeleton/README.md` | 前提・デプロイ・確認・削除・不可逆な設定 |
| `skeleton/params.example.json` | パラメータの例。実際の値は入れない |
| `skeleton/samconfig.toml.example` | スタック名とリージョン |
| `skeleton/functions/handler.py` | エントリポイントは `handler.handler` 固定 |
| `skeleton/tests/test_handler.py` | 契約テスト。実装を差し替えても残す |
| `skeleton/docs/` | 必要な場合のみ |

`skeleton/` 配下のテストは、ディレクトリ名が `_` で始まるためテストの自動検出からは
除外されます。代わりに `tests/test_scaffold_pattern.py` が、**複製した結果**に対して
`cfn-lint` と `pytest` を実行します。読者が実際に受け取るものを検査するほうが確実です。

## 1 パターン 1 テンプレート

パターン数は `patterns/*/*/template.yaml` を数えて求めます（`make counts`）。
テンプレートのないディレクトリは数えられず、2 つあるディレクトリは曖昧になります。

数を本文に書かないでください。書いた場合は同じ検査の対象になり、
ファイルシステムと食い違えば失敗します。ゼロが返った場合は
「まだ無い」ではなく「読み取り側が壊れた」として報告されます。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](../../docs/ja/architecture.md) | 収集層と配布層の全体像 |
| [最初に決めること](../../docs/ja/design-first-decisions.md) | Origin 作成前に決める項目 |
| [CONTRIBUTING.md](../../CONTRIBUTING.md) | 執筆規約とゲート |
