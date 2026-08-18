# 用語の整理 — 「ファイルを S3 で見せる」機能の呼び名

<!-- lang-switcher:start -->
🌐 [日本語](object-access-on-ontap.md) | [English](../../../en/reference/glossary/object-access-on-ontap.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->

「S3 でもファイルでも同じデータを読める」という機能は、プラットフォームごとに**別の名前と
別の実装**を持つ。ここを混ぜると対応バージョンの議論が噛み合わなくなる。

この構成が使うのは表の 1 行目だけである。残りは移植や将来の変種を検討するときの選択肢として
挙げてある。

| 呼び名 | 実装元 | 何をするか | 最小要件 | この構成での位置 |
|---|---|---|---|---|
| S3 Access Point（FSx for ONTAP に接続） | AWS | AWS 側のエンドポイントを ONTAP ボリュームに接続し、S3 API で読み書きする | ONTAP 9.17.1 以降。アクセスポイントとボリュームが同一リージョン・同一アカウント（[制限事項](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html)） | **収集層で使う** |
| ONTAP S3（native bucket） | NetApp | ONTAP 自身が S3 オブジェクトサーバとして専用バケットを提供する | ONTAP 9.8 以降、AFF / FAS / ONTAP Select。S3 ライセンスは無償だが必要（[対応プラットフォーム](https://docs.netapp.com/us-en/ontap/s3-config/ontap-version-support-s3-concept.html)） | 参考。AWS 外に収集層を置く場合の対応物 |
| ONTAP S3 NAS bucket（S3 マルチプロトコル） | NetApp | **既存の** NFS / SMB ボリュームのディレクトリを S3 バケットとして写像する | ONTAP 9.12.1 以降（[概要](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/index.html)） | 参考。同上 |
| FlexCache duality | NetApp | **Cache ボリューム**に ONTAP 自身の S3 アクセスを許可する | ONTAP 9.18.1 以降、`-is-s3-enabled true`（[FlexCache duality](https://docs.netapp.com/us-en/ontap/flexcache/enable-flexcache-duality.html)） | **使わない。** 1 行目とは別の機構であり、同一視しない |
| object REST API | Microsoft | Azure NetApp Files のディレクトリを S3 互換バケットとして写像する | [object REST API](https://learn.microsoft.com/en-us/azure/azure-netapp-files/object-rest-api-introduction)。キャッシュボリュームでは非対応 | 参考 |
| S3 multiprotocol | Google | Google Cloud NetApp Volumes で S3 アクセスを提供する | ONTAP モードのみ（[概要](https://docs.cloud.google.com/netapp/volumes/docs/discover/overview)） | 参考 |

## 混同すると何を間違えるか

表の 1 行目と 4 行目は、名前が近く、どちらも「ONTAP のボリュームに S3 でアクセスする」と
要約できてしまう。しかし実装元が AWS と NetApp で異なり、有効化の方法も最小バージョンも別で、
**別の機構**である。

そのため、次の推論はいずれも成り立たない。

| 成り立たない推論 | なぜ |
|---|---|
| duality が ONTAP 9.18.1 で使えるようになったから、Cache ボリュームに S3 Access Point を接続できる | 別の機構である。実装元も有効化方法も違い、片方の対応状況は他方の根拠にならない |
| duality が未対応のバージョンだから、Cache ボリュームに S3 Access Point は接続できない | 別の機構なので、否定の方向にも使えない |
| どちらも「S3 マルチプロトコル」だから同じ制約が当てはまる | ONTAP S3 NAS bucket（3 行目）が「S3 マルチプロトコル」と呼ばれる機能で、4 行目とは別 |

この構成はどちらも使わない。収集層で使うのは 1 行目だけで、Cache 側にオブジェクトアクセスを
出さないため、4 行目の対応状況は設計に影響しない。

## その他の用語

| 用語 | 意味 |
|---|---|
| Origin ボリューム | FlexCache の元になるボリューム。この構成では正本であり、書き込みの受け口 |
| Cache ボリューム | Origin の内容を必要な範囲だけ保持するボリューム。この構成では読み取り用途 |
| ファンアウト | 1 つの Origin から複数の Cache へ配ること |
| write-around | Cache 経由の書き込みを Origin へ直接向ける動作 |
| write-back | Cache 側にいったん書き、非同期で Origin へ返す動作。この構成では主題にしない |
| FileSystemIdentity | S3 Access Point 経由のアクセスを、どのファイルシステム識別情報として扱うかの設定 |
| SVM | Storage Virtual Machine。ONTAP のテナント単位 |

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [構成の形](../../architecture.md) | 収集層と配布層の全体像 |
| [サポート状況](../../support-matrix.md) | 対応構成と最小バージョン |
| [移植性](../../portability.md) | 収集層をこの表の他の機構に置き換える場合 |

---

<!-- lang-switcher:start -->
🌐 [日本語](object-access-on-ontap.md) | [English](../../../en/reference/glossary/object-access-on-ontap.md) | [🏠 リポジトリトップ](../../../../README.md)
<!-- lang-switcher:end -->
