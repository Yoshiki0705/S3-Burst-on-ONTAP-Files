# 検証記録 — S3 Access Point 経由の書き込みが FlexCache の Cache ボリュームでいつ見えるか
<!-- lang-switcher:start -->
🌐 [日本語](flexcache-s3ap-visibility.md) | [English](../../en/verification/flexcache-s3ap-visibility.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->

**この構成の中核的な主張を検証した記録です。** S3 Access Point で Origin ボリュームに書いた
オブジェクトが、FlexCache を経由して別クラスタの Cache ボリューム上の NFS マウントで
いつ読めるようになるかを実測しました。

## 検証環境

| 項目 | 値 |
|---|---|
| 計測日 | 2026-08-09（UTC） |
| リージョン | ap-northeast-1 |
| Origin クラスタ | ファイルシステム 1（`fs-0123456789abcdef0`、Origin 役）、SINGLE_AZ_1、128 MBps、1 HA ペア |
| Cache クラスタ | ファイルシステム 2（`fs-0123456789abcdef0`、オンプレミス相当の Cache 役）、SINGLE_AZ_1、128 MBps、1 HA ペア |
| **ONTAP バージョン** | **NetApp Release 9.18.1P3D1**（両クラスタ同一） |
| 接続 | VPC ピアリング（同一リージョン、同一アカウント） |
| Origin ボリューム | `s3burst_origin_vol2`、SVM `fsxsvm02`、セキュリティスタイル UNIX |
| Cache ボリューム | `s3burst_cache_vol2`、SVM `FSxN_OnPre`、FlexCache（`use_tiered_aggregate: true`） |
| S3 Access Point | `s3burst-verify-ap`、ファイルシステム識別情報 UNIX（root）、`NetworkOrigin` 指定なし（Internet） |
| クライアント | 同一 VPC・Cache クラスタと同一サブネットの EC2、NFSv3 |
| マウント | `actimeo=0`（サーバ側の反映を測るため） |
| オブジェクトサイズ | 64 B |
| 並列度 | 1 |
| 測定方法 | 書き込み（S3 PutObject）と読み取り（NFS `cat`）を**同一ホスト・同一クロック**で実行 |

## 測定結果

### S3 PutObject（Origin）→ FlexCache Cache NFS で読めるまで

| n | min | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| 30 | 10 ms | 14 ms | 18 ms | 19 ms | 19 ms |

### 初回読み取りとキャッシュヒット後の読み取り

| 読み取り | 所要 |
|---|---|
| 初回（まだ Cache に取り込まれていない状態） | 16 ms |
| 2 回目以降（Cache に取り込み済み） | 3〜5 ms |

### マルチパートアップロード中の可視性

| 時点 | Cache NFS 側 |
|---|---|
| パート 1 アップロード後、`CompleteMultipartUpload` 前 | **見えない** |
| `CompleteMultipartUpload` 後 | 見える（6,291,456 バイト、8 ms 後） |

### 削除の反映

| 操作 | 所要 |
|---|---|
| S3 DeleteObject → Cache NFS から消えるまで（`actimeo=0`） | 9 ms |

## 同一ボリュームの測定との比較

| 方向 | 同一ボリューム p50 | FlexCache 経由 p50 | 差分 |
|---|---|---|---|
| S3 PutObject → NFS で読める | 9 ms | 14 ms | +5 ms |
| S3 DeleteObject → NFS から消える | 7 ms | 9 ms | +2 ms |

**FlexCache が加える遅延は約 5 ms です。** 同一リージョン・VPC ピアリング経由・同一サブネットに
クライアントがいる条件では、FlexCache の有無はほぼ見えません。

## 読み取れること

- **この構成の中核的な主張が成り立ちます。** S3 Access Point で Origin に書いたオブジェクトは、
  FlexCache を経由して Cache ボリューム上の NFS マウントから 10〜19 ms で読めます
- **部分的なオブジェクトは Cache 側にも現れません。** マルチパートアップロード中に
  中途半端なファイルを読む心配は不要です
- **削除もミリ秒で反映されます。**`actimeo=0` の条件で 9 ms です
- **2 回目以降の読み取りは 3〜5 ms です。** FlexCache のキャッシュが効いた状態では、
  Origin への往復が不要になります

## 読み取れないこと

| 問い | この測定では答えられない理由 |
|---|---|
| 遠隔拠点・高レイテンシ環境でどうなるか | 同一リージョン・VPC ピアリング（サブミリ秒のネットワーク遅延）での測定です |
| スループットはどれくらいか | 並列度 1、64 B のオブジェクトです。スループットの測定ではありません |
| オンプレミス ONTAP を Cache にした場合 | 両方とも FSx for ONTAP です。オンプレミスは未検証です |
| SMB / NTFS セキュリティスタイルの場合 | NFS / UNIX のみです |
| ファンアウト数を増やした場合 | Cache は 1 つだけです |
| `actimeo=0` 以外のマウントオプション | `actimeo=0` 専用です。既定値では NFS クライアントキャッシュの影響が支配的になります（[同一ボリュームの検証記録](s3ap-nfs-visibility.md)で実測済み） |

## 検証環境の作成と削除

| 項目 | 状態 |
|---|---|
| VPC ピアリング | 作成・計測・**削除済み** |
| クラスタピア / SVM ピア | 作成・計測・**削除済み**（SVM ピア解除が非同期のため cluster peer は orphaned として残存するが、ネットワーク経路が無いため unavailable に遷移し、課金なし） |
| FlexCache ボリューム | **削除済み** |
| Origin ボリューム | **削除中**（FSx for ONTAP API 経由で DELETE 発行済み） |
| S3 Access Point | **削除済み** |
| セキュリティグループルール | **6 件すべて削除済み** |
| テストオブジェクト | **0 件**（スクリプト内で確認） |
| 一時的な IAM 権限 | **0 件**（実行前と同一状態に戻したことを確認） |

## 再現手順

1. 2 つの FSx for ONTAP ファイルシステムを用意し、VPC ピアリングで接続する
2. Origin 側にボリュームを作り、S3 Access Point を接続する
3. クラスタピア → SVM ピア → FlexCache の順に作成する（[配布側のデプロイ](../deployment/onprem-terraform.md)）
4. Cache 側ボリュームを `actimeo=0` で NFS マウントする
5. **書き込みと読み取りを同じホストで行う**（単一クロック）
6. 30 回程度繰り返し、分布で見る
7. 環境情報（上の表の全項目）を数値と一緒に記録する
8. **削除は FlexCache → SVM ピア → クラスタピア → ルート → ピアリングの順。逆順にすると消せないリソースが残る**

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [同一ボリュームの検証記録](s3ap-nfs-visibility.md) | Origin ボリュームを S3 と NFS の両方から読み書きした場合（FlexCache を経由していない） |
| [検証状況](../verification-status.md) | 主張ごとの段階 |
| [サポート状況](../support-matrix.md) | 対応構成と制約 |
| [PoC チェックリスト](../poc-checklist.md) | 検証の順序 |
| [構成の形](../architecture.md) | 全体像 |

---

<!-- lang-switcher:start -->
🌐 [日本語](flexcache-s3ap-visibility.md) | [English](../../en/verification/flexcache-s3ap-visibility.md) | [🏠 リポジトリトップ](../../../README.md)
<!-- lang-switcher:end -->
