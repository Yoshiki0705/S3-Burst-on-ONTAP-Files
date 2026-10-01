# 委任台帳 — TR 由来知見の作業主体判定

この台帳は、スコープ内とした Technical Report（TR）から取り出した知見ごとに、読み込み・集約という
作業をどの作業主体（Hub 側 Kiro か、この Spoke 側 Kiro か）が主導するかの判定を記録したものである。
要件 9「作業主体の委任判断と引き渡し」に対応する。

委任判定は、[スコープ台帳](scope-ledger.md)が記録するスコープの内外とは直交する独立した分類である
（要件 9.3）。スコープ内の TR であっても、そこから取り出す知見が横断的なら Hub、この構成固有なら
Spoke に分かれる。知見は TR 単位ではなく、1 本の TR から複数の知見が別々の判定を受けうる。

判定の対象は、スコープ台帳でスコープ内とした 10 本（優先 7・後続 3）から取り出した知見である。
スコープ外とした TR からは、本イニシアチブでは知見を取り出さない。

## 判定基準（要件 9.2）

| 判定 | 該当条件 |
|---|---|
| Hub（横断的） | (a) 2 つ以上の Spoke のアーキテクチャで参照されうる、構成に依存しない ONTAP の一般的性質、または (b) 採用判断（FSx for ONTAP を選ぶ/選ばないの意思決定材料）に属し特定の実装手順ではない |
| Spoke（構成固有） | (c) この構成固有のアーキテクチャ（S3 Access Points での収集、FlexCache 配布、特定の origin 構成）に密結合した手順・設定・検証、または (d) この repo で実測した/これから実測する性能・挙動の知見 |
| 保留 | (a)〜(d) で一意に決まらない知見。委任先が確定するまで Hub と Spoke のいずれにも本体記述を行わない（要件 9.9） |

役割分担の要点（要件 9.1）: 知見の読み込みと集約は Hub が担い、検証の実施・詳細な知見の公開/共有・
ブログ反映はこの Spoke（Subject Matter Expert）が担う。

## 委任判定

列構成は設計のデータモデル節「委任台帳」に従う。配置先 repo が Hub の知見への参照リンクは絶対 URL、
この Spoke 内の知見への参照は相対リンクで記録する（要件 2.4）。参照リンクは本体の配置後に確定する
ため、本体未配置の行は参照リンクを `—（本体配置後に付与）` とする。保留の行は配置先 repo を未定と
する。

| 対象 TR | 知見 | 委任判定 | 判定根拠 | 配置先 repo | 参照リンク |
|---|---|---|---|---|---|
| High_file_count_NAS_workloads | inode が 1 件あたり一定容量を占め、ボリュームの最大ファイル数がその容量とボリュームサイズで決まる性質 | Hub | (a) 構成に依存しない ONTAP の一般的性質。複数 Spoke のサイジングで参照されうる | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| High_file_count_NAS_workloads | 単一ディレクトリの最大サイズ（maxdir-size）の上限と、超過時の列挙コストの増大 | Hub | (a) 構成に依存しない ONTAP の一般的性質 | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| High_file_count_NAS_workloads | 高ファイル数ワークロードで FSx for ONTAP を選ぶ/選ばないの採用判断材料 | Hub | (b) 採用判断材料であり特定の実装手順ではない | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| High_file_count_NAS_workloads | この構成（S3 API 収集 → origin → FlexCache 配布）で高ファイル数時に実測すべきメタデータ操作・列挙の挙動 | Spoke | (d) この repo でこれから実測する挙動の知見 | s3-burst-on-ontap-files | —（本体配置後に付与） |
| FlexCache_and_FlexGroup_volumes | FlexCache のキャッシュ無効化・メタデータ複製の一般的な動作特性 | Hub | (a) 構成に依存しない ONTAP の一般的性質 | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| FlexCache_and_FlexGroup_volumes | この構成で origin から各拠点キャッシュへ配布する際の FlexCache 構成手順と検証 | Spoke | (c) この構成固有のアーキテクチャに密結合した手順・検証 | s3-burst-on-ontap-files | —（本体配置後に付与） |
| NFS | NFS の一般的なマウント・バージョン・性能に関わる指針 | Hub | (a) 構成に依存しない ONTAP の一般的性質 | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| SMB | SMB の一般的な共有・バージョン・性能に関わる指針 | Hub | (a) 構成に依存しない ONTAP の一般的性質 | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| NFS / SMB | この構成で FlexCache キャッシュを NFS / SMB で消費する際の配布検証 | Spoke | (d) この repo でこれから実測する挙動の知見 | s3-burst-on-ontap-files | —（本体配置後に付与） |
| S3 | ONTAP オブジェクトストアの一般的な動作・制限（オブジェクトサイズ上限等） | Hub | (a) 構成に依存しない ONTAP の一般的性質 | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| S3 | この構成で S3 Access Points を origin ボリュームに付与して収集する際の手順・設定 | Spoke | (c) この構成固有のアーキテクチャに密結合した手順・設定 | s3-burst-on-ontap-files | —（本体配置後に付与） |
| Networking | クラスタ / SVM ピアリングの到達性要件と、FlexCache 配布に必要なネットワーク前提 | Spoke | (c) この構成固有の配布経路に密結合した前提。ピアリングはこの構成の成立条件 | s3-burst-on-ontap-files | —（本体配置後に付与） |
| Tiering | FabricPool による非アクティブデータの階層化がもたらすコスト設計上の選択肢 | Hub | (b) 採用判断材料であり特定の実装手順ではない | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| Data_protection_and_disaster_recovery | SnapMirror / スナップショットによる保護・複製の一般的な設計選択肢 | Hub | (b) 採用判断材料であり特定の実装手順ではない | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |
| Security | NFS / SMB で配布するデータに対するランサムウェア対策 / WORM / FPolicy の適用可否 | 保留 | (a) 一般的性質とも (c) この構成固有の検証とも読め、FPolicy の S3 経路での挙動を含むため一意に決まらない | 未定 | —（判定確定後に付与） |
| Security_hardening | origin とキャッシュを載せる ONTAP の管理アカウント / 暗号化の運用セキュリティ指針 | Hub | (a) 構成に依存しない ONTAP の一般的な運用セキュリティ | FSx-for-ONTAP-Adoption-Playbook | —（本体配置後に付与） |

## 保留の扱い

保留とした知見は、委任先が確定するまで Hub と Spoke のいずれにも本体を記述しない（要件 9.9）。
確定の判断材料が得られた時点で、この表の委任判定・判定根拠・配置先 repo を更新する。更新時は、
Security の FPolicy が S3 Access Points 経由の操作で発火するかという既存の検証結果（この repo の
[検証状況](../../verification-status.md)）と整合させる。

## 内訳

- Hub: 11 知見 / Spoke: 5 知見 / 保留: 1 知見（合計 17 知見）
- 判定根拠を持たない知見・観点未分類の知見は残していない（要件 9.2）。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [スコープ台帳](scope-ledger.md) | TR のスコープ内外の判定（委任判定と直交する軸） |
| [検証状況](../../verification-status.md) | 評価段階の定義。保留知見の確定時に整合させる |
| [構成の形](../../architecture.md) | この構成が解くこと・解かないこと |
