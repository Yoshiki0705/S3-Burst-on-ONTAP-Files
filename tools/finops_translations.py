"""English for the strings `finops_model.py` generates.

Keyed by the Japanese source text, which is also what appears at the call site — see the language
section of `finops_model.py` for why there are no invented key names. Three rules follow from that
choice and are worth stating where the entries are:

1. **The key is the Japanese source, character for character.** Reword the Japanese and the entry is
   orphaned; `--translation-gaps` reports it rather than letting Japanese reach the English document.
2. **Placeholders, not values.** `{amount}` stays a placeholder on both sides. Interpolating first
   would make every distinct number a distinct key.
3. **No identity entries.** A source string with no Japanese character in it is returned unchanged by
   `t()`, so `S3 Standard-IA GET / 1,000` and `GB-Mo` do not appear here.

The English is not a gloss of the Japanese. Where the Japanese is compressed in a way English is not
— 「〜が支配項になる」, 「〜の側にある」 — the entry says the same thing in the way the target
language says it, because the two documents are read by different people and neither is a
translation exercise.
"""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # --- units and labels carried by the price table ------------------------------------------
    "アジアパシフィック (東京)": "Asia Pacific (Tokyo)",
    "タスク実行": "task execution",
    "S3 Standard ストレージ (最初の 50 TiB)": "S3 Standard storage (first 50 TiB)",
    "S3 Standard-IA ストレージ": "S3 Standard-IA storage",
    "S3 One Zone-IA ストレージ": "S3 One Zone-IA storage",
    "S3 Glacier Instant Retrieval ストレージ": "S3 Glacier Instant Retrieval storage",
    "S3 Intelligent-Tiering 頻繁アクセス層": "S3 Intelligent-Tiering Frequent Access tier",
    "S3 Intelligent-Tiering 低頻度アクセス層": "S3 Intelligent-Tiering Infrequent Access tier",
    "S3 Intelligent-Tiering アーカイブインスタントアクセス層": "S3 Intelligent-Tiering Archive Instant Access tier",
    "S3 標準 PUT / COPY / POST / LIST": "S3 standard PUT / COPY / POST / LIST",
    "S3 標準 GET およびその他": "S3 standard GET and all other requests",
    "S3 Standard-IA GET およびその他": "S3 Standard-IA GET and all other requests",
    "S3 Standard-IA 取り出し": "S3 Standard-IA retrieval",
    "S3 Glacier Instant Retrieval 取り出し": "S3 Glacier Instant Retrieval retrieval",
    "S3 AP 経由 PUT / COPY / POST / LIST (FSx for ONTAP 宛)": "PUT / COPY / POST / LIST through an S3 AP (to FSx for ONTAP)",
    "S3 AP 経由 GET およびその他 (FSx for ONTAP 宛)": "GET and all other requests through an S3 AP (to FSx for ONTAP)",
    "SSD ストレージ Single-AZ (第一 / 第二世代)": "SSD storage, Single-AZ (first / second generation)",
    "SSD ストレージ Multi-AZ (第一 / 第二世代)": "SSD storage, Multi-AZ (first / second generation)",
    "スループットキャパシティ Single-AZ 第一世代": "Throughput capacity, Single-AZ first generation",
    "スループットキャパシティ Single-AZ 第二世代": "Throughput capacity, Single-AZ second generation",
    "スループットキャパシティ Multi-AZ 第一世代": "Throughput capacity, Multi-AZ first generation",
    "スループットキャパシティ Multi-AZ 第二世代": "Throughput capacity, Multi-AZ second generation",
    "追加 SSD IOPS Single-AZ": "Additional SSD IOPS, Single-AZ",
    "追加 SSD IOPS Multi-AZ": "Additional SSD IOPS, Multi-AZ",
    "キャパシティプールストレージ Single-AZ": "Capacity pool storage, Single-AZ",
    "キャパシティプールストレージ Multi-AZ": "Capacity pool storage, Multi-AZ",
    "キャパシティプール読み取りリクエスト": "Capacity pool read requests",
    "キャパシティプール書き込みリクエスト": "Capacity pool write requests",
    "バックアップストレージ": "Backup storage",
    "S3 Files 高性能ストレージ (アクティブ分のみ)": "S3 Files high-performance storage (active data only)",
    "S3 Files データ読み取り": "S3 Files data read",
    "S3 Files データ書き込み": "S3 Files data write",
    "インターネット向けデータ転送 (最初の 10 TB)": "Data transfer out to the internet (first 10 TB)",
    "Direct Connect 経由のデータ転送 (東京、ポート料金は別)": "Data transfer over Direct Connect (Tokyo; port charges separate)",
    "DataSync 転送 (Basic モード)": "DataSync transfer (Basic mode)",
    "DataSync 転送 (Enhanced モード)": "DataSync transfer (Enhanced mode)",
    "DataSync タスク実行 (Enhanced モード)": "DataSync task execution (Enhanced mode)",
    "Single-AZ 第一世代": "Single-AZ, first generation",
    "Multi-AZ 第一世代": "Multi-AZ, first generation",
    "Single-AZ 第二世代": "Single-AZ, second generation",
    "Multi-AZ 第二世代": "Multi-AZ, second generation",
    # --- the price table ------------------------------------------------------------------------
    "### 単価表": "### Unit prices",
    "{region_label} (`{region}`)、オンデマンド、税別。"
    "AWS Price List API から {snapshot} に取得したもので、`effective` は API が返した適用開始日である。": "{region_label} (`{region}`), on demand, excluding tax. "
    "Read from the AWS Price List API on {snapshot}; `effective` is the date the API returned as the start of applicability.",
    "**この表は取得時点の値である。** 現在の単価は"
    "[S3 料金]({source_s3})と[FSx for ONTAP 料金]({source_fsx})で確認し、"
    "更新するときは `make finops-write` で再生成する（`make finops` が食い違いを検出する）。": "**These are the values as read on that date.** Check the current ones against "
    "[S3 pricing]({source_s3}) and [FSx for ONTAP pricing]({source_fsx}), and regenerate with "
    "`make finops-write` when updating them (`make finops` detects the drift).",
    "サービス": "Service",
    "課金項目": "Billed item",
    "単価": "Unit price",
    "S3 Standard のストレージ単価は使用量で段階が変わる"
    " (最初の 50 TiB {first}、次の 450 TB {next_450}、500 TB 超 {beyond} / GB-Mo)。"
    "以下の試算はこの段階を反映している。": "S3 Standard storage is priced in volume bands "
    "(first 50 TiB {first}, next 450 TB {next_450}, beyond 500 TB {beyond} per GB-Mo). "
    "The estimates below follow those bands.",
    # --- request price asymmetry ---------------------------------------------------------------
    "### リクエスト単価の非対称": "### Requests are not priced the same way on both sides",
    "同じ API 操作でも、宛先が S3 バケットか FSx for ONTAP ボリュームかで単価が違う。": "The same API operation carries a different unit price depending on whether it lands on an S3 bucket or on an FSx for ONTAP volume.",
    "GET およびその他": "GET and all other requests",
    "{ratio} 倍": "{ratio}x",
    "操作": "Operation",
    "S3 バケット宛": "To an S3 bucket",
    "S3 AP 経由 (FSx for ONTAP 宛)": "Through an S3 AP (to FSx for ONTAP)",
    "S3 バケット宛が何倍か": "Ratio, bucket to S3 AP",
    "低頻度アクセス層を選ぶと逆に開く。S3 Standard-IA の PUT は {ia_put} で、"
    "S3 AP 経由の {ratio} 倍にあたる。"
    "保存単価を下げる目的で階層を落とすと、書き込みが多いワークロードではリクエスト側で戻ってくる。": "Moving to an infrequent-access tier widens the gap rather than closing it. A PUT to S3 Standard-IA is {ia_put}, which is {ratio}x the S3 AP price. "
    "Dropping a tier to cut the storage rate gives the saving back on the request side of a write-heavy workload.",
    # --- the fixed floor -----------------------------------------------------------------------
    "### 固定費の下限": "### The floor",
    "S3 バケットに下限はない。1 バイトも置かなければ請求は発生しない。"
    "FSx for ONTAP は SSD 1 TiB とスループットキャパシティ 1 段が最小構成で、"
    "使用量に関わらずこの分が毎月かかる。": "An S3 bucket has no floor: store nothing and nothing is billed. "
    "The smallest FSx for ONTAP file system is 1 TiB of SSD and one throughput capacity step, "
    "and that much is billed every month whatever the usage.",
    "デプロイ": "Deployment",
    "API 値": "API value",
    "最小 SSD": "Minimum SSD",
    "最小スループット": "Minimum throughput",
    "SSD 分": "SSD portion",
    "スループット分": "Throughput portion",
    "月額下限": "Monthly floor",
    "第二世代の最小スループットは 384 MBps で、第一世代の 128 MBps より 3 段上にあたる。"
    "第二世代を選ぶ理由は MBps あたりの単価ではなく、"
    "SSD 512 TiB、200,000 IOPS、Single-AZ で最大 12 HA ペアという上限の側にある"
    "([世代の比較]({url}))。"
    "上限に用がないワークロードで第二世代を選ぶと、使わない余力に払うことになる。": "The second generation starts at 384 MBps, three steps above the first generation's 128 MBps. "
    "The reason to choose it is not the price per MBps but the ceilings: 512 TiB of SSD, 200,000 IOPS, and up to 12 HA pairs on Single-AZ "
    "([generation comparison]({url})). "
    "Choosing it for a workload that has no use for those ceilings means paying for headroom that stays idle.",
    # --- object size ---------------------------------------------------------------------------
    "### オブジェクトサイズが効く理由": "### Why object size decides this",
    "リクエスト課金は容量ではなく回数にかかる。"
    "同じ 1 GiB を書くとき、オブジェクトが小さいほど回数が増え、リクエスト課金が保存料金を追い越す。": "Requests are billed by count, not by volume. "
    "Writing the same 1 GiB in smaller objects takes more requests, and past a point the request charge overtakes the storage charge.",
    "平均オブジェクトサイズ": "Average object size",
    "1 GiB あたりの PUT 回数": "PUTs per GiB",
    "S3 バケット宛の PUT / GiB": "PUT to a bucket, per GiB",
    "S3 AP 経由の PUT / GiB": "PUT through an S3 AP, per GiB",
    "S3 の PUT が S3 Standard 1 か月保存料の何倍か": "Bucket PUT as a multiple of one month of S3 Standard storage",
    "平均オブジェクトサイズが約 {kib} KiB を下回ると、"
    "S3 バケットへの PUT 料金が S3 Standard の 1 か月分の保存料金を超える。"
    "小さいオブジェクトを高頻度で書く収集系では、保存単価ではなくリクエスト単価が支配項になる。": "Below an average object size of roughly {kib} KiB, the PUT charge to an S3 bucket exceeds one month of S3 Standard storage for the same bytes. "
    "For a collection workload writing small objects often, the request price is the dominant term, not the storage price.",
    # --- the scenario section header -----------------------------------------------------------
    "### ユースケース別の試算": "### Estimates by use case",
    "いずれも**試算**であり実測ではない。単価は上の単価表、使用量は各表の前提に置いた仮定である。": "Every figure below is an **estimate**, not a measurement. The unit prices are the table above; the usage figures are assumptions stated with each table.",
    "自分のワークロードで置き換えるべき値は、月間オブジェクト数、平均オブジェクトサイズ、"
    "保持期間、読み出し回数、ストレージ効率の 5 つ。": "Five values are the ones to replace with your own: monthly object count, average object size, "
    "retention period, read count, and storage efficiency.",
    "<!-- 生成物。編集しない。tools/finops_model.py で再生成する -->": "<!-- Generated. Do not edit. Regenerate with tools/finops_model.py -->",
    # --- the four options each scenario is costed against ---------------------------------------
    "S3 単独 (利用側も S3 API)": "S3 alone (consumers also speak the S3 API)",
    "S3 バケット + DataSync + FSx for ONTAP": "S3 bucket + DataSync + FSx for ONTAP",
    "FSx for ONTAP S3 AP (この構成)": "FSx for ONTAP S3 AP (this architecture)",
    "S3 バケット + S3 Files": "S3 bucket + S3 Files",
    # --- cost line items -----------------------------------------------------------------------
    "ストレージ (S3 Standard)": "Storage (S3 Standard)",
    "ストレージ (S3 Standard、着信面 {size})": "Storage (S3 Standard, landing area {size})",
    "ストレージ (S3 Standard、正本はバケットに残る)": "Storage (S3 Standard; the authoritative copy stays in the bucket)",
    "PUT リクエスト": "PUT requests",
    "GET リクエスト": "GET requests",
    "PUT リクエスト (S3 バケット宛)": "PUT requests (to an S3 bucket)",
    "PUT リクエスト (S3 AP 経由)": "PUT requests (through an S3 AP)",
    "PUT リクエスト (S3 AP 経由) の節約": "the PUT requests through an S3 AP that replace them",
    "GET / LIST リクエスト (同期の読み出し)": "GET / LIST requests (read by the sync task)",
    "GET リクエスト (初回読み出しはバケットからストリーム)": "GET requests (the first read is streamed from the bucket)",
    "GET リクエスト (バケットから直接ストリーム)": "GET requests (streamed straight from the bucket)",
    "DataSync 転送": "DataSync transfer",
    "SSD ストレージ ({size})": "SSD storage ({size})",
    "SSD ストレージ ({size}、階層化不可)": "SSD storage ({size}; cannot be tiered)",
    "スループットキャパシティ ({mbps} MBps)": "Throughput capacity ({mbps} MBps)",
    "キャパシティプールストレージ ({size})": "Capacity pool storage ({size})",
    "S3 Files 高性能ストレージ (アクティブ {share})": "S3 Files high-performance storage ({share} active)",
    "S3 Files 書き込み (高性能ストレージへの取り込み)": "S3 Files write (import onto high-performance storage)",
    "S3 Files 書き込み (メタデータの取り込み)": "S3 Files write (metadata import)",
    "S3 Files 読み取り (取り込み後の読み出しとメタデータ)": "S3 Files read (reads after import, plus metadata)",
    "S3 Files 読み取り (メタデータ)": "S3 Files read (metadata)",
    # --- the assumptions table shared by every scenario ----------------------------------------
    "想定業種: {industry}": "Industries this fits: {industry}",
    "前提": "Assumption",
    "値": "Value",
    "内訳": "Line item",
    "月額": "Monthly",
    "月間オブジェクト数": "Objects per month",
    "月間書き込み量": "Written per month",
    # The unit sits in the row label, not the cell: a bare "{months}" avoids both "1 months"
    # and the "month(s)" hedge, for any value the scenarios use.
    "保持期間": "Retention period (months)",
    "{months} か月": "{months}",
    "定常保存量 (論理)": "Steady-state stored volume (logical)",
    "1 オブジェクトあたり読み出し回数": "Reads per object",
    "ストレージ効率の仮定 (SSD 層)": "Assumed storage efficiency (SSD tier)",
    "ストレージ効率の仮定 (キャパシティプール層)": "Assumed storage efficiency (capacity pool tier)",
    "{share} — 階層化後は背景の効率化が動かないため、"
    "SSD 層の {retained} と仮定": "{share} — background efficiency does not run on tiered data, so this is assumed to be {retained} of the SSD-tier figure",
    "平均所要スループット": "Average throughput required",
    "キャパシティプールへ落とす割合": "Fraction tiered to the capacity pool",
    "スループットの余裕": "Throughput headroom",
    "平均所要の {multiple} 倍を満たす最小の段を選ぶ": "the smallest step that covers {multiple}x the average requirement",
    "SSD のプロビジョニング余裕": "SSD provisioning headroom",
    "効率適用後の {share} 増し": "{share} above the post-efficiency figure",
    "着信面 (S3) の保持期間": "Retention in the S3 landing area (months)",
    "{months} か月 — 同期後にライフサイクルで失効させる想定": "{months} — assumed to be expired by a lifecycle rule once the sync has run",
    "利用側がファイルプロトコルを要求するか": "Do the consumers require a file protocol?",
    "はい": "Yes",
    "いいえ": "No",
    "**合計 (月額)**": "**Total (monthly)**",
    "論理 1 GiB あたり": "Per logical GiB",
    "**{option}**: 要件を満たさないため試算しない（{reason}）。": "**{option}**: not costed, because it does not meet the requirement ({reason}).",
    "利用側がファイルプロトコルを要求するため": "the consumers require a file protocol",
    "同期ジョブを挟む構成と比べ、この構成は月額 {amount} ({pct}%) 下回る。"
    "差の最大項は「{term}」で、差の {share}% を占める。": "This architecture is {amount} ({pct}%) a month cheaper than the one with a sync job in the middle. "
    'The largest term in the difference is "{term}", which accounts for {share}% of it.',
    "同期ジョブを挟む構成と比べ、この構成は月額 {amount} ({pct}%) 上回る。"
    "差の最大項は「{term}」で、差の {share}% を占める。": "This architecture is {amount} ({pct}%) a month more expensive than the one with a sync job in the middle. "
    'The largest term in the difference is "{term}", which accounts for {share}% of it.',
    # --- the scenarios -------------------------------------------------------------------------
    "車載 / IoT テレメトリ — 小オブジェクト高頻度": "Vehicle / IoT telemetry — small objects, written often",
    "自動車、製造、IoT": "Automotive, manufacturing, IoT",
    "テキスト / JSON 主体だが同一内容の重複は少ない。AWS 公表値の汎用ファイル共有・圧縮のみ 50% を当てる": "Mostly text and JSON, but with little duplicate content. AWS's published 50% for general-purpose file sharing with compression only is applied",
    "解析処理を AWS 側の Linux コンピュートで動かす前提。マウントヘルパーを入れられる": "Assumes the analysis runs on Linux compute inside AWS, where the mount helper can be installed",
    "3 億オブジェクト / 月 (1 日あたり 1,000 万) を 64 KiB で受ける": "300 million objects a month (10 million a day) arriving at 64 KiB each",
    "利用側が S3 API を話せる場合を想定し、S3 単独も参考として並べる。"
    "NFS / SMB が要るなら S3 単独は選択肢から外れる": "S3 alone is shown for reference, on the assumption that the consumers can speak the S3 API. "
    "If NFS or SMB is required, it is not an option",
    "HiL テストベンチ — 走行ログを装置へ配る": "HiL test benches — distributing drive logs to the equipment",
    "自動車 (AV / ADAS)": "Automotive (AV / ADAS)",
    "センサー由来のバイナリが主体。AWS 公表値で最も近い地震探査データの 40% を当てる": "Mostly sensor-derived binary. AWS's closest published figure, 40% for seismic data, is applied",
    "テストベンチは構成を変えられない物理機器で、AWS 外にある。マウントヘルパーを入れられない": "The test benches are physical equipment outside AWS whose configuration cannot be changed, so the mount helper cannot be installed",
    "テストベンチは NFS / SMB マウントしか話さない。S3 単独は要件を満たさない": "The test benches speak nothing but an NFS or SMB mount, so S3 alone does not meet the requirement",
    "3 割は再読み出し頻度が低くキャパシティプールへ落ちるものとして置く": "30% is assumed to be re-read rarely enough to tier to the capacity pool",
    "EDA / CAE — バースト読み出し、メタデータ操作が多い": "EDA / CAE — bursty reads, heavy metadata traffic",
    "半導体、製造": "Semiconductors, manufacturing",
    "AWS 公表値のエンジニアリングデータ 75% (圧縮 + 重複排除) を当てる": "AWS's published 75% for engineering data (compression plus deduplication) is applied",
    "ツールチェーンを AWS の EC2 Linux で動かす前提。オンプレミスのファームに残す場合は選べない": "Assumes the toolchain runs on EC2 Linux in AWS; not available if it stays on an on-premises farm",
    "ツールチェーンが POSIX セマンティクスを要求する。S3 単独は要件を満たさない": "The toolchain requires POSIX semantics, so S3 alone does not meet the requirement",
    "第二世代を選ぶ理由は単価ではなく上限 (SSD 512 TiB、200,000 IOPS)": "The second generation is chosen for its ceilings (512 TiB of SSD, 200,000 IOPS), not for its unit price",
    "メディア / レンダリング — 大オブジェクト、リクエストは少ない": "Media / rendering — large objects, few requests",
    "メディア、エンターテインメント": "Media, entertainment",
    "既に圧縮された素材。圧縮も重複排除も効果を見込まない": "Already-compressed material. Neither compression nor deduplication is assumed to save anything",
    "レンダリングノードが AWS の EC2 Linux である前提。Windows ベースの工程や SMB が要る場合は選べない": "Assumes the render nodes are EC2 Linux in AWS; not available for a Windows-based pipeline or where SMB is required",
    "レンダリングノードは NFS マウント。S3 単独は要件を満たさない": "The render nodes mount over NFS, so S3 alone does not meet the requirement",
    "リクエスト単価の差はほぼ効かない。効くのはスループットとストレージ": "The request price difference barely matters here. Throughput and storage are what move the total",
    "ゲノム解析 — シーケンサー出力を HPC へ": "Genomics — sequencer output to an HPC cluster",
    "ライフサイエンス、研究": "Life sciences, research",
    "FASTQ / BAM は部分的に圧縮済み。AWS 公表値で最も近い地震探査データの 40% を当てる": "FASTQ and BAM are partly compressed already. AWS's closest published figure, 40% for seismic data, is applied",
    "HPC クラスタを AWS の EC2 Linux で動かす前提": "Assumes the HPC cluster runs on EC2 Linux in AWS",
    "HPC クラスタは NFS マウント。S3 単独は要件を満たさない": "The HPC cluster mounts over NFS, so S3 alone does not meet the requirement",
    "長期保持が効くため、キャパシティプールへの階層化が最大のレバーになる": "Long retention dominates, which makes tiering to the capacity pool the largest lever",
}

# The generated block links into the hand-written part of the same document by anchor, so the
# English heading is fixed by the entry below rather than chosen when that section is translated:
#   ## S3 Files を選ぶ場合の仕様
#     → ## Specifications that decide whether S3 Files fits
#       → #specifications-that-decide-whether-s3-files-fits
# `make links` fails on a mismatch, but it can only do so once the English document exists, which is
# several steps later. Written here so the two are decided in one place.
TRANSLATIONS.update(
    {
        # --- the read-heavy section --------------------------------------------------------------
        "### 読み取りが繰り返されるとき — 効くのは Egress": "### When the same data is read repeatedly — egress is what decides it",
        "ここまでの試算は利用側が同一リージョンにいることを前提にしていた。"
        "同一リージョン内のデータ転送には課金がないため、比較は保存単価とリクエスト単価の話になる。": "Every estimate so far assumed the consumers sit in the same Region. "
        "Transfer within a Region is not charged, which is why the comparison came down to storage and request rates.",
        "**利用側がオンプレミスにいると話が変わる。**"
        "データ転送はリージョンから出たバイト数に課金されるので、"
        "同じファイルを読み直した回数だけ倍になる。"
        "キャッシュが取り除くのはまさにこの倍数である。": "**With the consumers on premises it is a different question.** "
        "Data transfer is charged on bytes leaving the Region, so it multiplies by the number of times the same file is read again. "
        "That multiplier is exactly what a cache removes.",
        "データセット全体 (論理)": "Whole dataset (logical)",
        "月間の作業セット (実際に触るユニークなバイト数)": "Monthly working set (unique bytes actually touched)",
        "同じファイルを読む回数 / 月": "Reads of the same file per month",
        "月間の読み出し総量": "Total read per month",
        "キャッシュの再取得率の仮定": "Assumed cache refetch rate",
        "転送経路": "Transfer path",
        "インターネット (段階単価)": "Internet (tiered rate)",
        "参照データセットを毎月 30 回読み直す。回帰試験、再生、突き合わせのように"
        "同じ入力を何度も読むワークロードを想定する": "A reference dataset re-read 30 times a month. The shape assumed is a workload that reads the same input over and over — regression testing, replay, reconciliation",
        "ストレージ (S3 Standard、{size})": "Storage (S3 Standard, {size})",
        "GET リクエスト ({count} 回)": "GET requests ({count})",
        "**データ転送 (読んだ量 {size} がそのまま出る)**": "**Data transfer (all {size} read leaves the Region)**",
        "データ転送 (全量 {size} を 1 回)": "Data transfer (the whole {size}, once)",
        "データ転送 (作業セット {size} + 再取得 {refetch})": "Data transfer (working set {size} plus {refetch} refetch)",
        "オンプレミスから S3 を直接読む": "Reading S3 directly from on premises",
        "S3 から全量をオンプレミスへコピーして読む (DataSync)": "Copying everything from S3 to on premises and reading it there (DataSync)",
        "FSx for ONTAP + FlexCache で読む (この構成)": "Reading through FSx for ONTAP + FlexCache (this architecture)",
        "直接読む構成では、転送料金だけで {egress} "
        "({share}%) を占める。"
        "保存料金とリクエスト料金は誤差に近い。"
        "この構成は同じ読み取りを {cache_total} で提供し、"
        "直接読む場合の {ratio} 分の 1 になる。": "Reading directly, transfer alone accounts for {egress} ({share}%). "
        "Storage and requests are close to rounding error. "
        "This architecture serves the same reads for {cache_total}, a {ratio}th of reading directly.",
        "全量コピーとの差は転送量の差である。"
        "コピーはデータセット全量 {dataset} を運ぶ。"
        "キャッシュは作業セット {working_set} と再取得分だけを運ぶ。"
        "月額では {copy_total} と {cache_total} の差になる。"
        "加えて、オンプレミス側に確保する容量が全量か作業セット分かで違う。"
        "こちらは AWS の請求には出ない。": "The difference from a full copy is a difference in bytes moved. "
        "The copy carries the whole dataset, {dataset}. "
        "The cache carries the working set, {working_set}, plus refetches. "
        "Monthly, that is {copy_total} against {cache_total}. "
        "On top of it, the capacity provisioned on premises is the whole dataset in one case and the working set in the other. "
        "That part does not appear on an AWS bill.",
        # --- request charges on the read side ----------------------------------------------------
        "S3 GET ({count} 回)": "S3 GET ({count})",
        "S3 AP 経由 GET ({count} 回)": "GET through an S3 AP ({count})",
        "キャパシティプール読み取り ({count} 操作)": "Capacity pool reads ({count} operations)",
        "S3 リクエスト": "S3 requests",
        "キャパシティプール読み取り ({count} 操作、キャッシュ充填分のみ)": "Capacity pool reads ({count} operations, cache fill only)",
        "S3 GET ({count} 回、全量を 1 回)": "S3 GET ({count}; the whole dataset, once)",
        "利用側の読み出し (ローカル)": "Reads by the consumers (local)",
        "、": ", ",
        "なし": "none",
        "S3 バケットを直接読む": "Reading the S3 bucket directly",
        "FSx for ONTAP S3 AP 経由で読む": "Reading through an FSx for ONTAP S3 AP",
        "FSx for ONTAP + FlexCache を NFS / SMB で読む (この構成)": "Reading FSx for ONTAP + FlexCache over NFS / SMB (this architecture)",
        "S3 + DataSync で全量コピー": "A full copy with S3 + DataSync",
        "#### 読み取り {reads} 回時点のリクエスト課金": "#### Request charges at {reads} reads",
        "前提は上と同じで、読み取り回数だけ {reads} 回に固定する。"
        "作業セット {working_set} を {object_mib} MiB のオブジェクトで持つと"
        "ユニークなオブジェクト数は {objects} 個、"
        "読み出し回数は {requests} 回になる。": "The assumptions are those above, with the read count fixed at {reads}. "
        "A working set of {working_set} in {object_mib} MiB objects is {objects} unique objects and {requests} reads.",
        "方式": "Approach",
        "リクエスト課金の合計": "Total request charges",
        "**この規模ではリクエスト課金は支配項ではない。** 同じ条件での転送料金は {egress} で、"
        "直接読む構成のリクエスト課金 {requests} の "
        "{ratio} 倍にあたる。"
        "この構成が読み取り側で効くのは、リクエスト単価ではなく転送量を減らすからである。": "**At this scale request charges are not the dominant term.** Transfer under the same conditions is {egress}, "
        "which is {ratio}x the {requests} of request charges incurred by reading directly. "
        "What this architecture does on the read side is carry fewer bytes, not pay a lower request rate.",
        "FlexCache 経由の読み出しに S3 リクエストは発生しない。"
        "利用側は NFS / SMB で読むためである。"
        "残るのはキャッシュ充填時に Origin 側のキャパシティプールから読む分だけで、"
        "FabricPool が {object_mib} MB 単位で扱うためこの操作数で計上している。": "Reading through FlexCache incurs no S3 requests at all, because the consumers read over NFS or SMB. "
        "What remains is the read from the origin's capacity pool while the cache fills, counted in the operation size FabricPool works in, {object_mib} MB.",
        "S3 Files はこの表に入れていない。**この構成が対象とする利用側では使えない。**"
        "対応プロトコルが NFSv4.1 と NFSv4.2 だけで、"
        "NFSv3 と SMB が対象外である ([非対応事項とクォータ]({url}))。"
        "NFSv3 で固定された装置や Windows の工程はこれで外れる。"
        "ドキュメントが挙げる対応コンピュートも EC2、Lambda、EKS、ECS で、"
        "オンプレミスからのマウントについては記載がない。"
        "利用側を AWS へ移せる場合の参考値は後述する。": "S3 Files is not in this table. **It is not available to the consumers this architecture is for.** "
        "The protocols supported are NFSv4.1 and NFSv4.2 only; NFSv3 and SMB are not ([unsupported features and quotas]({url})). "
        "That rules out equipment fixed on NFSv3 and any Windows stage of a pipeline. "
        "The supported compute the documentation lists is EC2, Lambda, EKS and ECS, with nothing said about mounting from on premises. "
        "The case where the consumers can move into AWS is priced further down.",
        "#### リクエスト課金が効いてくるのはオブジェクトが小さいとき": "#### Request charges start to matter when the objects are small",
        "読み出す総量は同じで、オブジェクトサイズだけを変える。回数が変わるので課金額も変わる。": "The total read stays the same and only the object size changes. The count changes with it, and so does the charge.",
        "月間の読み出し回数": "Reads per month",
        "S3 を直接読む": "Reading S3 directly",
        "S3 AP 経由": "Through an S3 AP",
        "この構成 (FlexCache)": "This architecture (FlexCache)",
        "直接読む場合の転送料金に対する比": "As a share of the transfer charge for reading directly",
        "最右列が読みどころである。オブジェクトが数 MiB 以上なら、リクエスト課金は転送料金の 1% に届かない。"
        "一桁 KiB まで小さくすると数十 % に達し、このときは転送とリクエストの両方が問題になる。"
        "**「S3 の API コールが高額になる」という見立てが成立するのは、この小オブジェクト側の領域である。**"
        "オブジェクトが大きいワークロードでは、削減対象は転送量に絞ってよい。": "The rightmost column is the one to read. At a few MiB and above, request charges do not reach 1% of the transfer charge. "
        "Down at single-digit KiB they reach tens of percent, and at that point both transfer and requests are problems. "
        '**"S3 API calls get expensive" holds in this small-object region, and only there.** '
        "For a workload with large objects, bytes moved is the only thing worth attacking.",
        # --- the transfer / request matrix -------------------------------------------------------
        "直接読むほうが安い": "Reading directly is cheaper",
        "**両方**": "**Both**",
        "転送 (リクエストも無視できない)": "Transfer (requests not negligible)",
        "転送": "Transfer",
        "リクエスト": "Requests",
        "### 転送とリクエストを同時に見る": "### Looking at transfer and requests together",
        "読み取り側の課金は転送とリクエストの 2 つで、効く手が違う。"
        "転送はバイト数を減らすことで下がり、リクエストは呼び出し回数を減らすことで下がる。"
        "**どちらが支配項かで打つ手が変わる**ので、自分のワークロードがどこにいるかを先に確かめる。": "There are two charges on the read side, transfer and requests, and they respond to different remedies. "
        "Transfer falls by carrying fewer bytes; requests fall by making fewer calls. "
        "**Which one dominates decides what to do**, so locate your own workload first.",
        "作業セットとデータセットの量は固定し、平均オブジェクトサイズと読み取り回数だけを振る。"
        "合計にはどちらの側も保管料金を含める"
        "(直接読む側は S3 Standard、この構成は SSD とキャパシティプールとスループット)。"
        "変動するのは転送とリクエストの 2 列である。": "The working set and dataset sizes are fixed; only average object size and read count vary. "
        "Both totals include storage — S3 Standard for reading directly, SSD plus capacity pool plus throughput for this architecture. "
        "The two columns that move are transfer and requests.",
        "平均オブジェクト": "Average object",
        "読み取り回数 / 月": "Reads per month",
        "リクエストの占率": "Request share",
        "直接読む計": "Total, reading directly",
        "この構成": "This architecture",
        "倍率": "Ratio",
        "支配項": "Dominant term",
        "読み方は 2 つある。**縦に見ると回数の効果**が出る。"
        "回数が増えて増えるのは転送だけで、リクエストの占率はほぼ変わらない。"
        "**横に見るとサイズの効果**が出る。サイズを小さくすると転送は変わらず"
        "リクエストだけが増えるので、占率が上がる。": "There are two ways to read it. **Down a column is the effect of the read count.** "
        "Raising the count raises transfer alone; the request share barely moves. "
        "**Across a row is the effect of size.** Making the objects smaller leaves transfer unchanged and raises requests, so the share climbs.",
        "#### 支配項ごとの打ち手": "#### What to do about each dominant term",
        "症状": "Symptom",
        "効く手": "What helps",
        "効かない手": "What does not",
        "同じデータを何度も読む。オブジェクトは数 MiB 以上": "The same data is read many times, in objects of a few MiB or more",
        "作業セットだけを運ぶ (FlexCache)、利用側の移設、Direct Connect で単価を下げる": "Carry only the working set (FlexCache), move the consumers, or lower the rate with Direct Connect",
        "オブジェクトをまとめる。回数は減っても運ぶバイト数は変わらない": "Batching the objects. The count falls but the bytes moved do not",
        "オブジェクトが一桁 KiB で、読み出し回数が非常に多い": "Objects of single-digit KiB, read a very large number of times",
        "オブジェクトをまとめて大きくする、S3 API を経由しない読み出し経路にする": "Batch into larger objects, or read by a path that does not go through the S3 API",
        "転送単価の交渉。金額の大半がリクエスト側にある": "Negotiating the transfer rate. Most of the money is on the request side",
        "両方": "Both",
        "小さいオブジェクトを繰り返し読む": "Small objects, read repeatedly",
        "まとめる (リクエスト) とキャッシュする (転送) の併用。片方だけでは残る": "Batching (for requests) and caching (for transfer) together. Either alone leaves the other",
        "片方だけの対処": "Addressing only one of the two",
        "どちらも小さい": "Neither",
        "読み取り回数が少ない。ファイルプロトコルの要件もない": "Few reads, and no file-protocol requirement",
        "S3 を直接読む。ファイルシステムの固定費を負わない": "Read S3 directly and carry no file system floor",
        "キャッシュの導入。固定費のほうが大きい": "Introducing a cache. The floor costs more than it saves",
        "この構成の列がサイズと回数でほとんど動かないのは、"
        "読み出しが S3 API を経由せず、運ぶのが作業セットに限られるためである。"
        "**そのぶん固定費が先に立つ**ので、読み取りが少ない領域では不利になる。"
        "表の「直接読むほうが安い」行がその領域である。": "This architecture's column barely moves with size or count because the reads do not go through the S3 API and what is carried is limited to the working set. "
        "**The floor is therefore what stands out**, which puts it behind in the low-read region — "
        'the rows marked "Reading directly is cheaper".',
        # --- consumers moved into AWS ------------------------------------------------------------
        "S3 GET ({count} 回、しきい値超のためバケットから直接)": "S3 GET ({count}; above the threshold, so straight from the bucket)",
        "S3 Files メタデータ読み取り": "S3 Files metadata read",
        "S3 Files メタデータ取り込み": "S3 Files metadata import",
        "S3 Files 高性能ストレージ": "S3 Files high-performance storage",
        "データ転送": "Data transfer",
        "#### 参考 — 利用側を AWS へ移した場合": "#### For reference — with the consumers moved into AWS",
        "この構成の前提は「利用側が AWS の外にいて、動かせない」ことである。"
        "動かせるなら話は変わるので、参考としてその場合を並べる。": "This architecture assumes the consumers are outside AWS and cannot be moved. "
        "If they can be moved it is a different question, so that case is priced here for reference.",
        "**同一リージョン内のデータ転送には課金がない。**"
        "上の表で {egress} を占めていた転送料金がそのまま消える。"
        "ストレージ層をどう選ぶかで動く金額より、この 1 項目のほうが大きい。": "**Transfer within a Region is not charged.** "
        "The {egress} of transfer in the table above disappears entirely. "
        "That single line is larger than anything the choice of storage layer moves.",
        "EC2 から S3 を直接読む": "Reading S3 directly from EC2",
        "EC2 から S3 Files でファイルとして読む": "Reading as files from EC2 through S3 Files",
        "FSx for ONTAP を同一リージョンで読む": "Reading FSx for ONTAP in the same Region",
        "データが高性能ストレージに載らず": "the data is not held on high-performance storage and ",
        "S3 Files は直接読む場合との差が {delta} しかない。"
        "平均オブジェクトサイズ {object_mib} MiB は"
        "しきい値 {threshold} KiB を超えるため"
        "{not_resident}"
        "保管の課金が増えないためである。"
        "POSIX のファイルセマンティクスを S3 のデータに与える手段としては安い。": "S3 Files differs from reading directly by only {delta}. "
        "An average object size of {object_mib} MiB is above the {threshold} KiB threshold, so {not_resident}"
        "storage charges do not increase. "
        "As a way to give POSIX file semantics to data in S3, it is inexpensive.",
        "FSx for ONTAP を同一リージョンで使う場合は {total} で、"
        "直接読む場合の {ratio} 倍になる。"
        "転送料金という差が消えた状態では、ファイルシステムの固定費が残るためである。"
        "この状況で FSx for ONTAP を選ぶ理由は費用ではなく、"
        "SMB、NFSv3、ONTAP のデータ管理機能、あるいはオンプレミスとの併用といった要件になる。": "FSx for ONTAP in the same Region is {total}, {ratio}x reading directly, "
        "because with the transfer difference gone the file system floor is what is left. "
        "The reason to choose FSx for ONTAP here is not cost but a requirement: SMB, NFSv3, ONTAP's data management features, or running alongside on-premises systems.",
        "**読み取り側の費用を下げる手段として、利用側の移設が最も効く。**"
        "移設できるなら、まずそれを検討する。"
        "この構成が対象とするのは、装置が現地にある、計測対象との距離が要る、"
        "既存設備の投資が残っている、といった理由で移設できない場合である。": "**Moving the consumers is the most effective way to reduce read-side cost.** "
        "If they can move, consider that first. "
        "This architecture is for the cases where they cannot: the equipment is on site, proximity to what is being measured is required, or investment in existing facilities has not been written off.",
        # --- sweeping the read count -------------------------------------------------------------
        "{count} 回": "{count}",
        "#### 読み取り回数を振る": "#### Sweeping the read count",
        "同じ作業セットを何回読むかだけを変えて、他の前提は固定する。": "Only the number of times the same working set is read changes; every other assumption is held.",
        "直接読む構成": "Reading directly",
        "直接読む構成が何倍か": "Ratio, direct to this architecture",
        "読み取りが 1 回なら直接読むほうが安い。"
        "運ぶ量が同じで、ファイルシステムの固定費を負わないためである。"
        "回数が増えると直接読む構成の転送料金だけが比例して増え、"
        "キャッシュ側は増えない。**損益分岐は読み取り回数で決まる。**": "At one read, reading directly is cheaper: the same bytes move and no file system floor is carried. "
        "As the count rises, only the transfer charge for reading directly rises with it, while the cache side does not. "
        "**The break-even point is a read count.**",
        "Direct Connect を使う場合、転送単価は {dx} / GB の定額になり"
        " (インターネットの最初の 10 TB は {internet} / GB)、"
        "倍率は下がるが構造は変わらない。ポート料金は別に発生し、接続する施設によって変わる。": "Over Direct Connect the rate is a flat {dx} per GB "
        "(against {internet} per GB for the first 10 TB to the internet), "
        "which lowers the ratio without changing the structure. Port charges are separate and depend on the facility.",
        "この節の前提で最も効くのは作業セットの割合である。"
        "作業セットがデータセット全体に近づくほどキャッシュの利点は薄れ、"
        "全量コピーとの差が縮む。逆に参照が局所的なほど差が開く。": "The assumption with the most leverage in this section is the working set as a share of the dataset. "
        "The closer it gets to the whole dataset, the less a cache is worth and the smaller the gap to a full copy. "
        "The more localised the access, the wider the gap.",
        # --- the cache site ---------------------------------------------------------------------
        "### 配布側 — フル SSD の Cache ボリューム": "### The distribution side — an all-SSD cache volume",
        "(下限に張り付き)": "(at the floor)",
        "ここまでの試算は収集側 (Origin) だけを見ている。"
        "この構成は配布側に FlexCache の Cache ボリュームを置くので、その分が別に載る。": "Every estimate so far looks only at the collection side, the origin. "
        "This architecture places a FlexCache cache volume on the distribution side, which is charged separately.",
        "Cache ボリュームには階層化ができない。"
        "ONTAP の仕様として、FabricPool の Origin を Cache することはできるが"
        "**Cache ボリューム自体は階層化されない** "
        "([対応機能一覧]({url}))。"
        "したがって Cache は全量が SSD に載る。": "A cache volume cannot be tiered. "
        "ONTAP allows a FabricPool origin to be cached, but **the cache volume itself is not tiered** "
        "([supported and unsupported features]({url})). "
        "All of the cache therefore sits on SSD.",
        "それが成立するのは Cache が疎だからである。FlexCache は Origin の全データを複製せず、"
        "実際に読まれたブロックだけを保持する。"
        "NetApp のサイジング指針は Origin の**最低 10%**を推奨し、作成時の既定値も 10% である"
        " ([サイジング指針]({url}))。"
        "読み取り中心のワークロードでは 5〜15% に収める運用が一般的で、"
        "この帯であれば全量 SSD でも費用が成り立つ。": "That works because the cache is sparse. FlexCache does not replicate all of the origin's data; it holds only the blocks actually read. "
        "NetApp's sizing guidance recommends **at least 10%** of the origin, which is also the default at creation "
        "([sizing guidance]({url})). "
        "Read-heavy workloads are commonly run at 5-15%, and within that band an all-SSD footprint is affordable.",
        "以下は Cache 比率を {ratio} に置いた場合の配布側の月額と、"
        "同じ場所に全量コピーを置いた場合の比較である。"
        "全量コピーは通常のボリュームなので階層化できるものとして計算している。"
        "全量 SSD として計算すれば差はさらに開くが、それは比較として不当なので採らない。": "Below is the monthly cost of the distribution side at a cache ratio of {ratio}, against a full copy at the same site. "
        "The full copy is a normal volume, so it is costed with tiering available to it. "
        "Costing it as all-SSD would widen the gap, and would not be a fair comparison.",
        "ワークロード": "Workload",
        "Origin 論理": "Origin logical",
        "Cache SSD (効率適用後、10%)": "Cache SSD (post-efficiency, 10%)",
        "Cache 10% の月額": "Cache at 10%, monthly",
        "Cache 20% の月額": "Cache at 20%, monthly",
        "全量コピーの月額": "Full copy, monthly",
        "コピーが何倍か": "Ratio, copy to cache",
        "差が小さく出るのは、Origin の階層化割合が大きいワークロードである。"
        "コピー側もキャパシティプールに落とせるため、SSD 単価の差が効きにくくなる。"
        "逆にホットなデータが多いワークロードでは、コピー側も SSD に置くことになり差が開く。": "The gap is narrowest where a large share of the origin is tiered: the copy can tier too, which blunts the difference in SSD rates. "
        "Where most of the data is hot, the copy has to sit on SSD as well and the gap widens.",
        "サイジング指針の下限、かつ作成時の既定値": "the lower bound in the sizing guidance, and the default at creation",
        "作業セットが読みきれないときの比較用": "for comparison when the working set does not fit",
        "実質的にコピー。階層化できないぶんコピーより高い": "effectively a copy, and more expensive than one because it cannot tier",
        "Cache 比率を動かしたときの月額を、Origin 論理が最大の"
        "「{workload}」({size}) で示す。": "Monthly cost against cache ratio, shown on the workload with the largest origin, {workload} ({size}).",
        "Cache 比率": "Cache ratio",
        "Cache SSD": "Cache SSD",
        "Cache の月額": "Cache, monthly",
        "備考": "Note",
        "比率 100% は成立しない選択である。階層化できない Cache に全量を置くと、"
        "階層化できる通常のボリュームに全量コピーを置くより高くつく。"
        "Cache を「コピーの代わり」として全量でサイジングすると、この領域に入る。": "A ratio of 100% is not a defensible choice. Putting everything in a cache that cannot tier costs more than putting a full copy in a normal volume that can. "
        'Sizing a cache at full size, as a "replacement for a copy", lands here.',
        # --- the three options at a single site --------------------------------------------------
        "要件を満たさない": "does not meet the requirement",
        "### 3 つの選択肢を並べる — 収集と利用が同じ場所の場合": "### The three options side by side — collection and consumption at the same site",
        "ここでは配布側を足さない。**バケットから DataSync で FSx for ONTAP にコピーすれば、"
        "その FSx for ONTAP 自体が NFS / SMB で読み書きできるので、Cache を置く理由がない。**"
        "Cache が費用に見合うのは、利用側がファイルシステムと別の場所にいる場合だけである。"
        "その場合の比較は Cache と全量コピーの対比（上の表）になる。"
        "この表は 3 案がいずれもファイルシステム 1 つ、または 0 つで済む単一サイトの比較である。": "No distribution side is added here. **Copy from a bucket into FSx for ONTAP with DataSync and that FSx for ONTAP already serves NFS and SMB, so there is nothing for a cache to do.** "
        "A cache earns its cost only when the consumers sit somewhere other than the file system, and the comparison for that case is cache against full copy, in the table above. "
        "This table is the single-site case, where every option is one file system or none.",
        "この表は「利用側にファイルとして配る」ことを前提にした比較である。"
        "利用側が S3 API で足りるなら配布層そのものが不要で、"
        "各ワークロードの試算にある S3 単独の金額が下限になる。": "This table assumes the data is delivered to the consumers as files. "
        "If the S3 API is enough for them, no distribution layer is needed at all, and the S3-alone figure in each workload's estimate is the floor.",
        "3 列目の S3 Files は、S3 バケットをファイルシステムとしてマウントする選択肢である。"
        "FSx for ONTAP を持たないため固定費の下限がなく、正本はバケットに残る。"
        "対応プロトコルは NFSv4.1 と NFSv4.2 で、**NFSv3 と SMB は対象外**である"
        " ([非対応事項とクォータ]({quotas_url}))。"
        "EC2 では S3 Files のマウントヘルパー (`amazon-efs-utils` に含まれる) が必要で、"
        "`s3files` というファイルシステムタイプでマウントする"
        " ([マウント手順]({mounting_url}))。"
        "対応するコンピュートは EC2、Lambda、EKS、ECS である"
        " ([S3 Files の概要]({overview_url}))。"
        "費用だけでは決められない仕様上の制約が複数あるので、"
        "この表の金額は後述の[S3 Files を選ぶ場合の仕様](#s3-files-を選ぶ場合の仕様)と併せて読む。": "The third column, S3 Files, mounts an S3 bucket as a file system. "
        "There is no FSx for ONTAP and so no fixed floor, and the authoritative copy stays in the bucket. "
        "The protocols supported are NFSv4.1 and NFSv4.2; **NFSv3 and SMB are not** "
        "([unsupported features and quotas]({quotas_url})). "
        "On EC2 it needs the S3 Files mount helper (shipped in `amazon-efs-utils`) and is mounted with the `s3files` file system type "
        "([mounting instructions]({mounting_url})). "
        "The supported compute is EC2, Lambda, EKS and ECS "
        "([S3 Files overview]({overview_url})). "
        "Several constraints here cannot be settled on cost, so read these figures together with "
        "[specifications that decide whether S3 Files fits](#specifications-that-decide-whether-s3-files-fits) below.",
        "オブジェクトサイズで結果が反転する。"
        "S3 Files は既定のしきい値 ({threshold} KiB) を超えるファイルを"
        "高性能ストレージに載せず、バケットから直接ストリームする。"
        "ストレージ課金が発生しないので、大きいオブジェクトを読むワークロードでは安い。"
        "しきい値以下のファイルは高性能ストレージに取り込まれ、"
        "{rate} / GB-Mo が効くので、小さいオブジェクトでは高くつく。": "Object size flips the result. "
        "S3 Files does not hold files above its default threshold ({threshold} KiB) on high-performance storage; it streams them straight from the bucket. "
        "No storage charge arises, which makes it cheap for a workload reading large objects. "
        "Files at or below the threshold are imported onto high-performance storage at {rate} per GB-Mo, which makes it expensive for small objects.",
        "大きいオブジェクトの行で S3 Files の金額がほぼ S3 Standard の保存料金に見えるのは、"
        "計上漏れではなく設計どおりである。1 MiB 以上の読み出しは高性能ストレージを経由せず"
        "バケットから直接ストリームされ、ファイルシステム側のデータ課金が発生しない。"
        "残るのは S3 の GET リクエストと 4 KiB のメタデータ読み取りだけで、"
        "オブジェクトが大きければ回数が少ないため金額に出ない。"
        "S3 の GET と PUT はどの行でも計上している。": "On the large-object rows the S3 Files figure looks like little more than S3 Standard storage. That is the design, not a missing line. "
        "Reads at 1 MiB and above bypass high-performance storage and stream from the bucket, so no file system data charge arises. "
        "What remains is the S3 GET and a 4 KiB metadata read, and with large objects the count is low enough not to show. "
        "S3 GET and PUT are counted on every row.",
        "**配布サイトを増やしたときの増え方は 3 案で違う。**"
        "この構成は Origin 1 つに対してサイトごとに Cache を足すので、"
        "1 サイトあたり Origin 論理の 1 割程度で増える。"
        "DataSync 方式はサイトごとに全量コピーを置くので、1 サイトあたり全量で増える。"
        "S3 Files はファイルシステムあたり 1 VPC なのでサイトごとにファイルシステムを作るが、"
        "同じバケットに複数のファイルシステムを付けられ、"
        "課金されるのは各ファイルシステムが実際に使った分だけである。"
        "サイト数が増えるほど全量コピー方式が不利になる。": "**The three grow differently as distribution sites are added.** "
        "This architecture adds a cache per site against one origin, so each site adds roughly a tenth of the origin's logical size. "
        "The DataSync approach places a full copy per site, so each site adds the whole dataset. "
        "S3 Files is one VPC per file system, so a file system is created per site; several file systems can attach to the same bucket, and each is charged for what it actually uses. "
        "The more sites, the worse the full-copy approach looks.",
        "S3 Files が安く出るワークロードで、それでもこの構成を選ぶ理由は費用ではない。"
        "利用側が構成を変えられない装置である、SMB が要る、AWS 外にいる、"
        "ONTAP のデータ管理機能を収集直後のデータに効かせたい、といった要件の側にある。"
        "費用だけで選ぶなら、その要件がない限り S3 Files のほうが合う場面がある。": "Where S3 Files comes out cheaper, the reason to choose this architecture anyway is not cost. "
        "It is a requirement: the consumers are equipment whose configuration cannot be changed, SMB is needed, they are outside AWS, or ONTAP's data management features have to reach the data as soon as it is collected. "
        "On cost alone, and absent such a requirement, there are cases where S3 Files fits better.",
        # --- why large objects favour S3 Files ---------------------------------------------------
        "#### 大きいオブジェクトで S3 Files が安くなる理由": "#### Why S3 Files is cheaper for large objects",
        "「{workload}」の内訳を並べると理由が 1 行で出る。"
        "S3 Files は**しきい値を超えるファイルのデータを高性能ストレージに載せない**ので、"
        "保管の課金は S3 Standard の単価だけになる。"
        "FSx for ONTAP は作業セット相当を SSD に置く。": "Laying out the line items for {workload} gives the reason in one line. "
        "S3 Files **does not hold the data of above-threshold files on high-performance storage**, so storage is charged at the S3 Standard rate and nothing more. "
        "FSx for ONTAP puts the equivalent of the working set on SSD.",
        "比較項目": "Item",
        "論理データ量": "Logical data",
        "S3 Files の保管 (論理全量を S3 Standard に)": "S3 Files storage (all logical data in S3 Standard)",
        "この構成の SSD 分のみ ({size} × {rate})": "This architecture, SSD portion only ({size} x {rate})",
        "SSD 分が S3 Standard 全量の何倍か": "SSD portion as a multiple of all-S3-Standard",
        "論理データの {share} を SSD に置くだけで、"
        "論理全量を S3 Standard に置いた金額を上回る。"
        "さらにスループットキャパシティの固定費が乗る。S3 Files にはその項目がない。": "Putting {share} of the logical data on SSD already exceeds the cost of holding all of it in S3 Standard. "
        "The throughput capacity floor is on top of that. S3 Files has no such line.",
        "引き換えになっているものも同じ表から読める。"
        "S3 Files でしきい値を超えるファイルは、読み出しのたびにバケットから取得される。"
        "低レイテンシが要るならしきい値を上げることになり、"
        "上げた分は {rate} / GB-Mo の課金対象になる。"
        "この安さは、読み出しが S3 のレイテンシで行われることと引き換えである。": "The same table shows what is given up for it. "
        "An above-threshold file in S3 Files is fetched from the bucket on every read. "
        "If low latency is needed, the threshold has to be raised, and what is raised above it becomes billable at {rate} per GB-Mo. "
        "The low figure is paid for in read latency.",
        # --- sweeping storage efficiency ---------------------------------------------------------
        "AWS 公表値の地震探査データ": "AWS's published figure for seismic data",
        "AWS 公表値の汎用ファイル共有": "AWS's published figure for general-purpose file sharing",
        "AWS 公表値のエンジニアリングデータ": "AWS's published figure for engineering data",
        "#### ストレージ効率の仮定を振ってみる": "#### Sweeping the storage efficiency assumption",
        "効率の仮定は、この文書で最も金額を動かす仮定である。"
        "「{workload}」で SSD 層の効率を振ると次のようになる"
        "（キャパシティプール層は常にその半分と仮定）。": "Efficiency is the assumption that moves the figures in this document most. "
        "Sweeping the SSD-tier efficiency on {workload} gives the following, with the capacity pool tier always assumed to be half of it.",
        "SSD 層の効率": "SSD-tier efficiency",
        "プール層の効率": "Pool-tier efficiency",
        "この構成の月額": "This architecture, monthly",
        "S3 + S3 Files の月額": "S3 + S3 Files, monthly",
        "**S3 Files の列は動かない。** ONTAP の重複排除と圧縮は S3 の保管料金に効かないので、"
        "効率をどう仮定しても S3 Files 側の金額は変わらない。"
        "つまり効率の仮定は、この構成に有利な方向にしか働かない。"
        "楽観的な効率を置くと、この構成が実際より良く見える。": "**The S3 Files column does not move.** ONTAP deduplication and compression do not reach S3 storage charges, so no efficiency assumption changes that figure. "
        "The assumption can therefore only work in this architecture's favour. "
        "An optimistic figure makes it look better than it is.",
        "階層化を有効にしている環境で高い効率を期待するのは慎重に扱う。"
        "**階層化されたデータには背景の効率化処理が動かない**。"
        "SSD にいる間に適用された分だけが保持され、"
        "効率化が走る前に階層化されたブロックは削減なしでプールに残る"
        " ([FSx for ONTAP のドキュメント]({fsx_url})、"
        "[NetApp KB]({netapp_url}))。"
        "cooling period が短い構成や `All` ポリシーでは、プール層の効率は 0% に寄る。": "Be careful expecting a high figure where tiering is enabled. "
        "**Background efficiency processing does not run on tiered data.** "
        "Only what was applied while the block was on SSD is preserved, and a block tiered before efficiency ran stays in the pool with no reduction at all "
        "([FSx for ONTAP documentation]({fsx_url}), [NetApp KB]({netapp_url})). "
        "With a short cooling period, or an `All` policy, the pool-tier figure tends towards 0%.",
        # --- the S3 Files expiry sweep -----------------------------------------------------------
        "{days} 日": "{days}",
        "既定値": "default",
        "小さいオブジェクトの場合、高性能ストレージの有効期限が最大のレバーになる。"
        "「{workload}」で期限を振ると次のようになる"
        "(既定は 30 日、設定可能な範囲は 1 日から 365 日)。": "For small objects the expiry on high-performance storage is the largest lever. "
        "Sweeping it on {workload} gives the following (the default is 30 days; the configurable range is 1 to 365).",
        "有効期限": "Expiry (days)",
        "アクティブ割合": "Active share",
        "期限を詰めれば下がるが、期限外のファイルを読むとバケットからの取り込みが再度発生する。"
        "読み取りの時間的な偏りが小さいワークロードでは、期限を詰めても取り込みの往復で戻ってくる。": "Shortening it lowers the figure, but reading a file that has expired triggers another import from the bucket. "
        "Where reads are spread evenly over time, what shortening saves comes back as import round trips.",
        "しきい値のほうも同じ構造を持つ。"
        "しきい値を上げれば小さくないファイルも低レイテンシで読めるが、"
        "その分が高性能ストレージの課金対象になる。"
        "この列の安さは、しきい値を超えるファイルが S3 のレイテンシで読まれることと引き換えである。": "The threshold has the same structure. "
        "Raising it lets larger files be read at low latency, and what is raised becomes billable on high-performance storage. "
        "This column's low figure is paid for by above-threshold files being read at S3 latency.",
        # --- the marginal case -------------------------------------------------------------------
        "### 既に FSx for ONTAP がある場合の増分": "### The increment when FSx for ONTAP is already there",
        "この構成が対象とする状況では、利用側が NFS / SMB を要求するため FSx for ONTAP は既にある。"
        "そこに S3 の受け口を足すときの比較は、"
        "グリーンフィールドの「S3 か FSx for ONTAP か」ではなく「増分としてどちらが安いか」になる。": "In the situation this architecture is for, the consumers require NFS or SMB, so FSx for ONTAP is already there. "
        'Adding a way in over S3 is therefore not the greenfield question "S3 or FSx for ONTAP" but "which increment is cheaper".',
        "前提は上の「{workload}」と同じ (3 億オブジェクト / 月、64 KiB)。"
        "SSD とスループットは既存ワークロードのために既に払っているものとして、増分だけを並べる。": "The assumptions are those of {workload} above (300 million objects a month at 64 KiB). "
        "SSD and throughput are taken as already paid for by the existing workload, so only the increment is shown.",
        "増分": "Increment",
        "S3 AP を足す": "Add an S3 AP",
        "S3 AP 経由 PUT のみ": "PUT through the S3 AP, nothing else",
        "S3 バケットと同期ジョブを足す": "Add an S3 bucket and a sync job",
        "S3 保存 + S3 PUT + 同期の読み出し GET + DataSync 転送": "S3 storage + S3 PUT + the sync job's GET + DataSync transfer",
        "差": "Difference",
        "S3 AP はアクセスポイント自体に時間課金がないため、増分はリクエスト課金に集約される。"
        "同期ジョブ側の増分には、同じバイト列を 2 系統で持つ保存料金が含まれる。"
        "この差は容量が増えても縮まらない。": "An S3 Access Point carries no hourly charge of its own, so its increment reduces to request charges. "
        "The sync job's increment includes storage for holding the same bytes in two places. "
        "That difference does not narrow as capacity grows.",
    }
)
