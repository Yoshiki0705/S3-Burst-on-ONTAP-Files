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
    "FSx for ONTAP は SSD 1 TiB とスループットキャパシティ 1 つが最小構成で、"
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
    "第二世代の最小スループットは 384 MBps で、第一世代の 128 MBps より 3 つ上の指定値にあたる。"
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
    "S3 Standard 非現行バージョンの保持": "S3 Standard noncurrent-version retention",
    "PUT リクエスト": "PUT requests",
    "GET リクエスト": "GET requests",
    "PUT リクエスト (S3 バケット宛)": "PUT requests (to an S3 bucket)",
    "PUT リクエスト (S3 AP 経由)": "PUT requests (through an S3 AP)",
    "PUT リクエスト (S3 AP 経由) の節約": "the PUT requests through an S3 AP that replace them",
    "GET / LIST リクエスト (同期の読み出し)": "GET / LIST requests (read by the sync task)",
    "GET リクエスト (初回読み出しはバケットからストリーム)": "GET requests (the first read is streamed from the bucket)",
    "GET リクエスト (バケットから直接ストリーム)": "GET requests (streamed straight from the bucket)",
    "GET リクエスト (1 MiB 以上はバケットから直接ストリーム)": "GET requests (1 MiB or larger reads stream straight from the bucket)",
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
    "平均所要の {multiple} 倍を満たす最小の指定値を選ぶ": "the smallest step that covers {multiple}x the average requirement",
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
    "HiL テストベンチ — 走行ログの装置への配布": "HiL test benches — distributing drive logs to the equipment",
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
        "**利用側がオンプレミスにいると話が変わる**。"
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
        "S3 Files はこの表に入れていない。**この構成が対象とする利用側では使えない**。"
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
        "**「S3 の API コールが高額になる」という見立てが成立するのは、この小オブジェクト側の領域である**。"
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
        "### 転送とリクエストの同時確認": "### Looking at transfer and requests together",
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
        "**同一リージョン内のデータ転送には課金がない**。"
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
        "**読み取り側の費用を下げる手段として、利用側の移設が最も効く**。"
        "移設できるなら、まずそれを検討する。"
        "この構成が対象とするのは、装置が現地にある、計測対象との距離が要る、"
        "既存設備の投資が残っている、といった理由で移設できない場合である。": "**Moving the consumers is the most effective way to reduce read-side cost.** "
        "If they can move, consider that first. "
        "This architecture is for the cases where they cannot: the equipment is on site, proximity to what is being measured is required, or investment in existing facilities has not been written off.",
        # --- sweeping the read count -------------------------------------------------------------
        "{count} 回": "{count}",
        "#### 読み取り回数に対する感度": "#### Sweeping the read count",
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
        "NetApp のサイジング指針は Origin の**最低 10%** を推奨し、作成時の既定値も 10% である"
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
        "その FSx for ONTAP 自体が NFS / SMB で読み書きできるので、Cache を置く理由がない**。"
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
        "**配布サイトを増やしたときの増え方は 3 案で違う**。"
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
        "#### ストレージ効率の仮定に対する感度": "#### Sweeping the storage efficiency assumption",
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
        # --- the common 20 TiB baseline grid -------------------------------------------------------
        "### 共通ベースライン — 20 TiB を同じ条件で": "### A common baseline — 20 TiB under the same terms",
        "パターン": "Pattern",
        "各セルは 4 つの量を別々に導く。**保存オブジェクト数** (保存バイト / サイズ)、"
        "**月間書き込みオブジェクト数** (書き込み量 / サイズ、S3 の PUT と NFS の書き込み操作に対応)、"
        "**月間読み取り回数** (読み取り量 / サイズ、S3 の GET と NFS の読み取り操作に対応)、"
        "そして **capacity pool の課金リクエスト数** である。"
        "最後の 1 つは FabricPool の 4 MiB 単位の読み取り操作数で、"
        "GET 1 回あたりの回数は**未確認 (UNCONFIRMED)** のまま置く。"
        "この 4 つを同じ数として扱わない。": "Each cell derives four quantities separately: the **stored object count** (stored bytes / size), "
        "the **objects written per month** (write volume / size, matching the S3 PUT and NFS write operations), "
        "the **reads per month** (read volume / size, matching the S3 GET and NFS read operations), "
        "and the **capacity-pool billed request count**. "
        "That last one is a count of FabricPool 4 MiB-unit read operations, and the number per GET is left **UNCONFIRMED**. "
        "These four are not treated as the same number.",
        "項目": "Item",
        "リージョン": "Region",
        "単価スナップショット": "Price snapshot",
        "通貨": "Currency",
        "USD、税別": "USD, excluding tax",
        "保存量 (論理、全セル共通)": "Stored volume (logical, common to every cell)",
        "ストレージ効率の仮定 (SSD / プール層)": "Assumed storage efficiency (SSD / pool tier)",
        "1 か月の秒数": "Seconds in a month",
        "{seconds} 秒 (30 × 24 × 3600)": "{seconds} s (30 x 24 x 3600)",
        "GiB / GB-Mo の換算": "GiB / GB-Mo conversion",
        "論理 GiB を GB-Mo の単価に当てる": "Logical GiB is priced at the GB-Mo rate",
        "#### パターン {pattern} — オブジェクト {size}": "#### Pattern {pattern} — {size} objects",
        "導出量": "Derived quantity",
        "capacity pool 課金リクエスト数": "Capacity-pool billed request count",
        "未確認 (GET あたりの回数が未測定)": "unconfirmed (the count per GET is not measured)",
        "**主要費目小計 / major-line-item subtotal**": "**major-line-item subtotal**",
        # --- working-set patterns P1-P8 ------------------------------------------------------------
        "ここまでのユースケース別の試算は、ワークロードごとに前提が違う。"
        "それぞれが現実のどれかに寄っているぶん、方式そのものの差を同じ土俵で見るには向かない。"
        "この節は逆に、**論理 20 TiB という 1 つの土俵**を固定し、"
        "オブジェクトサイズ ({sizes}) と、{count} つの読み書きパターン ({first}〜{last}) だけを振る。"
        "各パターンは、作業セット比・作業セット内の読み取り回数・チャーン率の 3 つで決まり、"
        "月間の読み取り量と書き込み量はそこから導く。"
        "両方式に同じ論理ワークロードを与える。": "The use-case estimates above each start from different assumptions. "
        "Each leans toward one real workload, which is what makes them concrete and also what makes them a poor place to see the difference between the methods on equal footing. "
        "This section does the opposite: it fixes **one footing, 20 TiB of logical data**, and varies only the object size ({sizes}) and {count} read/write patterns ({first} to {last}). "
        "Each pattern is set by three numbers (working-set ratio, reads per working-set object, churn rate), and the monthly read and write volumes are derived from them. "
        "The same logical workload is presented to both methods.",
        "保存量 (論理) はどのセルでも 20 TiB で固定である。"
        "書き込みは既存オブジェクトの置き換えで、月を通して積み増さない。"
        "**月間書き込み量を平均保持量と同一視しない**。"
        "20 TiB の定常保存に対して、月に 1 TiB 書くとはその一部を置き換えることであって、"
        "積み増すことではない。": "The stored volume (logical) is fixed at 20 TiB in every cell. "
        "Writes replace existing objects; nothing accumulates over the month. "
        "**The monthly write volume is not equated with the average retained volume.** Against a steady-state 20 TiB resident set, writing 1 TiB a month replaces part of it; "
        "it does not add to it.",
        "・": ", ",
        " と ": " and ",
        "#### 式と読み方の例": "#### Formulas and a worked example",
        "各セルの量は、次の 5 本の式で導く。": "Each cell's quantities come from these five formulas.",
        "月間読み取り量 = 保存量 × 作業セット比 × 作業セット内の読み取り回数": "read per month = stored volume x working-set ratio x reads per working-set object",
        "月間読み取り回数 = 月間読み取り量 ÷ オブジェクトサイズ": "read requests per month = read per month / object size",
        "保存量に対する倍数 R = 作業セット比 × 作業セット内の読み取り回数": "multiple of the stored volume, R = working-set ratio x reads per working-set object",
        "月間書き込み量 = 保存量 × チャーン率": "written per month = stored volume x churn rate",
        "月間書き込み個数 = 月間書き込み量 ÷ オブジェクトサイズ": "objects written per month = written per month / object size",
        "例: {key} は、保存量 {stored} のうち {w}% ({ws}) を作業セットとし、"
        "その各オブジェクトを月 {n} 回読む。"
        "月間読み取り量は {ws} × {n} = {read} で、保存量の {r} 倍 (R = {r}) になる。"
        "{size} なら {ws_objects} 個を {n} 回読むので {requests} 回。"
        "残り {rest_pct}% ({rest}) は月内に一度も読まれない。"
        "「オブジェクトを月 N 回読む」とだけ書くと、"
        "N 回の対象が全オブジェクトか作業セットかで総量が {factor:g} 倍変わる。"
        "この節では対象を作業セットと明記し、総量を保存量との倍数 R でも示す。": "Example: {key} takes {w}% ({ws}) of the {stored} stored volume as its working set and reads each of those objects {n} times a month. "
        "Monthly read volume is {ws} x {n} = {read}, which is {r}x the stored volume (R = {r}). "
        "At {size}, that is {ws_objects} objects read {n} times, or {requests} requests. "
        "The other {rest_pct}% ({rest}) is not read at all within the month. "
        'Writing only "each object is read N times a month" leaves open whether N applies to every object or only the working set, and the total differs by a factor of {factor:g}. '
        "This section names the working set as the subject of the count and also states the total as the multiple R of the stored volume.",
        "作業セット比と回数は、月間読み取り量を分解して示す軸である。"
        "この表の金額は、月間読み取り量・月間書き込み量・オブジェクトサイズだけで決まり、"
        "作業セット比には連動しない。"
        "月間の読み取り量・書き込み量が同じパターン {groups} は、どのサイズでも金額が同じになる。": "The working-set ratio and the read count are axes that break the monthly read volume down. "
        "The amounts in these tables are set by the monthly read volume, the monthly write volume and the object size alone, and do not follow the working-set ratio. "
        "Patterns with the same monthly read and write volumes, {groups}, cost the same at every size.",
        "この表の 3 つの前提は作業セット比と切り離している。"
        "(a) FSx for ONTAP の capacity pool は全パターンで保存量の {pool}%。"
        "(b) S3 Files の高性能ストレージ ({threshold} KiB 以下のサイズ) は保存量の全量をアクティブとして計上。"
        "(c) 書き込みのないセルの S3 Files ({threshold} KiB 以下) は、"
        "初回読み出しのストリームを計上せず、読み取りをすべて高性能ストレージの読み取りとして計上。"
        "{small_groups} は、作業セット比とチャーン率の和が 100% 未満で、保存量の全体には触れられない。"
        "(a)(b) を触れられる量に合わせる前提に置き換えると、小計は下がる向きになる。"
        "{large_groups} は和が 100% 以上で、保存量の全体に及びうる。"
        "全体に及ぶと置いて (a) を置き換えると、FSx for ONTAP の小計は上がる向きになる。"
        "(c) を置き換え、作業セットの各オブジェクトの初回読み出しを計上すると、"
        "増える項目は、バケットからの GET と、高性能ストレージへの取り込み書き込み "
        "(${write_price} / GB、最小 {min_io} KiB)、減る項目は、高性能ストレージの読み取りである。"
        "取り込み書き込みは、ディレクトリを最初にたどったとき "
        "{threshold} KiB 以下のファイルのデータをまとめて取り込む既定の挙動に従い、"
        "読まれたオブジェクトの数とは対応しないので、このモデルは数えていない。"
        "差し引きの向きは、このモデルでは確定していない。"
        "取り込み書き込みを含めず、GET の増加と読み取りの減少だけを見ると、"
        "(c) が当てはまる {stream_cells} セルの中では "
        "{stream_pattern} の {stream_size} の変化が最大で、{stream_before} から {stream_after} へ、"
        "{stream_delta} ({stream_pct}%) 下がる。この額に取り込み書き込みは入っていない。"
        "示した向きと金額はいずれも試算上の感度で、測定ではない。": "These three premises are held apart from the working-set ratio. "
        "(a) The FSx for ONTAP capacity pool is {pool}% of the stored volume in every pattern. "
        "(b) S3 Files high-performance storage (the row that appears for sizes of {threshold} KiB or smaller) books the whole stored volume as active. "
        "(c) In a cell with no writes, S3 Files ({threshold} KiB or smaller) books no first-read stream and books every read as a high-performance-storage read. "
        "For {small_groups}, the working-set ratio plus the churn rate is below 100%, so not all of the stored volume can be touched; replacing (a) and (b) with premises that follow the touched volume would lower the subtotals. "
        "For {large_groups}, the sum is 100% or more and the whole volume may be touched; if it is, replacing (a) would raise the FSx for ONTAP subtotal. "
        "Replacing (c) so that the first read of each working-set object is counted raises two items, the GET requests to the bucket and the import write onto high-performance storage (${write_price}/GB, {min_io} KiB minimum), and lowers one, the reads from high-performance storage. "
        "The model does not count the import write: by default, on the first access to a directory, the data of every file of {threshold} KiB or smaller is imported together, so the write does not correspond to the number of objects read. "
        "The net direction is not determined by this model. "
        "Looking only at the added GET requests and the removed reads, and leaving out the import write, the change is largest among the {stream_cells} cells where (c) applies in {stream_pattern} at {stream_size}, from {stream_before} to {stream_after}, a decrease of {stream_delta} ({stream_pct}%); that figure does not include the import write. "
        "Every direction and amount shown is a sensitivity on the model, not a measurement.",
        "#### パターンの一覧": "#### The patterns",
        "名前": "Name",
        "作業セット比": "Working-set ratio",
        "作業セット内の回数": "Reads per working-set object",
        "月間読み取り量 (R)": "Read per month (R)",
        "月間書き込み量 (チャーン率)": "Written per month (churn rate)",
        "読み : 書き (バイト比)": "Read : write (byte ratio)",
        "位置づけ": "Where it comes from",
        "{n} 回": "{n}",
        "{gib} (R = {r} 倍)": "{gib} (R = {r}x)",
        "0 GiB (書き込みなし)": "0 GiB (no writes)",
        "{gib} (チャーン率 {pct}%)": "{gib} (churn rate {pct}%)",
        "コールド保管": "Cold archive",
        "全件を 1 回読む": "Read everything once",
        "ホット 20% を再読": "Re-read a hot 20%",
        "小さい作業セットを強く再読": "Re-read a small working set heavily",
        "読み多めに少量取り込み": "Read-mostly with light ingest",
        "読み書き混在": "Mixed read and write",
        "小オブジェクトの大量書き込み": "High-volume small-object writes",
        "書き込み中心": "Write-centred",
        "**仮置き**。出典のある値ではなく、算術を通すための仮置き。"
        "作業セット {w}%、回数 {n}、書き込みなし": "**Placeholder.** Not a sourced value; placed to make the arithmetic work. "
        "Working set {w}%, reads per object {n}, no writes",
        "書き込みのない読み取り専用の形。大きいファイルを順次読み、書き込みがない点が MLPerf Storage の "
        "Unet3D に近い（[MLPerf Storage]({mlperf_url})）。"
        "YCSB C は読み取りのみだが Zipf 分布で偏って読むため、"
        "全件を 1 回ずつ読む形とは違う（[YCSB]({ycsb_url})）": "A read-only shape with no writes. Sequential reads of large files with no writes resemble MLPerf Storage's Unet3D ([MLPerf Storage]({mlperf_url})). "
        "YCSB C is read-only but Zipf-skewed, so it is not one pass over every object ([YCSB]({ycsb_url}))",
        "作業セット比 {w}% は、データの 2 割がホット、8 割がコールドという比を述べる "
        "2 つのブログによる（[EFS ブログ]({efs_url})、"
        "[FSx for ONTAP サイジングブログ]({sizing_url})）。"
        "どちらも算出方法とデータセットを示していない。"
        "ブログが述べるのはホットなデータの容量比で、月内に読まれる割合とは述べていない。"
        "**回数 {n} は出典がなく**、R を 1 倍に揃えるために置いた": "The {w}% working set follows two blogs that describe a 20% hot / 80% cold split ([EFS blog]({efs_url}), [FSx for ONTAP sizing blog]({sizing_url})); neither gives its method or dataset. "
        "What the blogs give is the hot share of the data by capacity; they do not say what share is read within a month. "
        "**The read count of {n} has no source**; it was chosen to make R equal 1",
        "作業セット {w}% ({ws_gib}) は、本文の「読み取りが繰り返されるとき」の節の"
        "作業セットと同じ大きさ。月 {n} 回は、その節の「読み取り回数に対する感度」表にある行の 1 つ。"
        "その節の本表は月 30 回で、capacity pool の割合も 70%"
        "（この節の固定は {pool_pct}%）と違う。"
        "いずれも本リポジトリの試算前提であり、測定値ではない": "The {w}% working set ({ws_gib}) is the same size as the working set in the repeated-read section of this document. "
        "{n} reads a month is one row of that section's read-count sensitivity table; its main table uses 30 reads, and its capacity-pool share is 70% (this section fixes {pool_pct}%). "
        "All of these are repository assumptions, not measurements",
        "読み取りは P4 と同じ（本リポジトリの試算前提）。"
        "書き込みを保存量の {c}%（{write_tib} TiB）とした。"
        "読み : 書きのバイト比は {read_share} : {write_share} で、"
        "YCSB B の読み 95 : 更新 5 に近い形だが、"
        "YCSB B はオペレーション数の比であり同じ量ではない（[YCSB]({ycsb_url})）。"
        "チャーン率 {c}% は置いた値": "Reads as in P4 (repository assumptions), with writes at {c}% of the stored volume ({write_tib} TiB). "
        "The byte ratio {read_share} : {write_share} is close in form to YCSB B's 95 reads : 5 updates, which is an operation-count ratio and not the same quantity ([YCSB]({ycsb_url})). "
        "The {c}% churn rate is a chosen value",
        "**仮置き**。出典のある値ではなく、算術を通すための仮置き。"
        "作業セット {w}%、回数 {n}、保存量と同量の書き込み": "**Placeholder.** Not a sourced value; placed to make the arithmetic work. "
        "Working set {w}%, reads per object {n}, writes equal to the stored volume",
        "全オブジェクトを月に 1 回置き換え、各オブジェクトを {n} 回読む形。"
        "「車載 / IoT テレメトリ」の前提（{auto_objects} 個 / 月、64 KiB、読み出し "
        "{auto_reads} 回、保持 1 か月）に沿った形で、本リポジトリの試算前提。"
        "違う点が 3 つある。保存量はその節の {auto_stored} ではなく {stored_tib} TiB に揃える。"
        "capacity pool の割合はその節の {auto_pool_pct}% ではなくこの節の {pool_pct}%、"
        "SSD の圧縮率はその節の {auto_eff_pct}% ではなくこの節の {eff_pct}%。"
        "64 KiB のとき書き込みは {objs_64k} 個（その節は {auto_objects} 個）": "Every object replaced once a month and read {n} times. "
        "The shape follows the automotive / IoT telemetry scenario ({auto_objects} objects a month at 64 KiB, {auto_reads} reads, one month retention), a repository assumption. "
        "Three things differ: the stored volume is {stored_tib} TiB, not that scenario's {auto_stored}; "
        "the capacity-pool share is this section's {pool_pct}%, not {auto_pool_pct}%; "
        "and the SSD efficiency is this section's {eff_pct}%, not {auto_eff_pct}%. "
        "At 64 KiB this is {objs_64k} objects written (that scenario writes {auto_objects})",
        "{key} の作業セット比": "{key} working-set ratio",
        "{key} の回数": "{key} read count",
        "{key} のチャーン率": "{key} churn rate",
        "{size} で {amount}": "{amount} for {size}",
        "{placeholders} の値は出典がなく、算術を通すために置いた。"
        "{repo_assumed} の値のうち表の位置づけで「試算前提」と書いたものは、"
        "本リポジトリの試算前提であって測定値ではない。"
        "{unsourced}は、出典も試算前提もなく置いた値である。": "{placeholders} have no source; the values were placed to make the arithmetic work. "
        "Of the values in {repo_assumed}, those marked as repository assumptions in the table are assumptions of this repository, not measurements. "
        "{unsourced} have neither a source nor a repository assumption behind them.",
        "両方式とも、下の内訳は**主要費目小計**であって月額総額ではない。"
        "capacity pool の読み取りリクエスト数が未確認であること、"
        "および S3 のバージョニング非現行版・バックアップ・通信費を算入していないことによる。"
        "S3 Files の内訳は、4 KiB × 操作のメタデータ課金を取り込み側と読み取り側の別行で示し、"
        "どちらも小計に算入している。"
        "S3 Files のメタデータ行 (4 KiB × 操作) が 1 MiB 以上の読み取りと取り込みにも立つかは、未確認である。"
        "[計量ページ](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html)は"
        "バケットからの直接読み取りに 4 KiB のメタデータ読み取りが付くと書き、"
        "[料金ページ](https://aws.amazon.com/s3/pricing/)は同じ読み取りに S3 の GET 課金だけが付くと書いている。"
        "2 ページの文面が揃わず、実測もないため、小計には算入したままにしている。"
        "除くと、1 MiB 以上のセルの小計は最大 {delta} (そのセルの小計の {pct}%) 下がる。"
        "増える方向もある。"
        "1 回の読み取りにメタデータ操作が k 回付く場合は、読み取り側の行が k 倍になる。"
        "ディレクトリの初回列挙は、ファイル 1 個ごとに 4 KiB の書き込みを計量する。"
        "{stored_tib} TiB を列挙した場合の 1 回限りの額 ({enumeration_small}) は、"
        "メタデータ分だけの額で、{threshold} KiB 以下のファイルのデータの取り込み書き込み "
        "(${write_price} / GB) は含まない。"
        "既定のトリガ (ディレクトリの初回アクセス) は、このサイズのファイルのデータも取り込むためである。"
        "{threshold} KiB を超えるサイズ ({enumeration_large}) では、"
        "データは取り込まれず直接読まれるので、この額はメタデータ分のみである。"
        "モデルはどちらも算入していない。"
        "どちらも測っていない。"
        "セルごとの除いた小計は、`python3 tools/finops_model.py --baseline-json` の "
        "`subtotal_excluding_metadata_usd` で読める。": "For both methods, each breakdown below is a **major-line-item subtotal**, not a monthly total. "
        "The capacity-pool read-request count is unconfirmed, and S3 noncurrent versioning, backup and transfer are not counted. "
        "The S3 Files breakdown shows the 4 KiB-per-operation metadata charges as separate import-side and read-side lines, and counts both in the subtotal. "
        "Whether the metadata lines (4 KiB per operation) also apply to reads and imports of 1 MiB or larger is unconfirmed. "
        "The [metering page](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html) says a direct read from the bucket carries a 4 KiB metadata read, "
        "while the [pricing page](https://aws.amazon.com/s3/pricing/) says the same read carries only the S3 GET charge. "
        "The two pages do not agree and there is no measurement, so the lines stay in the subtotal. "
        "Without them, the subtotal of a cell of 1 MiB or larger falls by at most {delta} ({pct}% of that cell's subtotal). "
        "The amount can also rise. "
        "If each read carries k metadata operations, the read-side line is k times as large. "
        "The first listing of a directory meters a 4 KiB write for each file in it. The one-off cost of listing {stored_tib} TiB ({enumeration_small}) is for the metadata alone; "
        "it does not include the import write (${write_price}/GB) for the data of files of {threshold} KiB or smaller, because the default trigger (first access to a directory) imports their data as well. "
        "For sizes above {threshold} KiB ({enumeration_large}) the data is not imported but read directly, so the figure is the metadata alone. "
        "The model counts neither. "
        "Neither has been measured. "
        "The subtotal without them, cell by cell, is available as `subtotal_excluding_metadata_usd` in the output of `python3 tools/finops_model.py --baseline-json`.",
        "S3 単独の内訳表は、書き込みのないパターン ({read_only}) にだけ置く。"
        "方式ごとに書き込みの経路 (S3 API の PUT、NFS の書き込みと同期、S3 Access Points 経由の PUT) が違い、"
        "同じ表に並べると書き込みの前提が混ざるためである。"
        "範囲の決めであって、書き込みを含む S3 単独の構成が成り立たないという主張ではない。": "The S3-alone breakdown appears only for the patterns with no writes ({read_only}). "
        "The write path differs by method (an S3 API PUT, an NFS write plus a sync, a PUT through S3 Access Points), and putting them in one table would mix the write assumptions. "
        "This is a choice of scope, not a claim that an S3-alone configuration with writes cannot work.",
        "S3 Files 読み取り (取り込み後の読み出し)": "S3 Files read (reads after import)",
        "S3 Files メタデータ取り込み ({ops} 操作 × 4 KiB)": "S3 Files metadata import ({ops} operations x 4 KiB)",
        "S3 Files メタデータ読み取り ({ops} 操作 × 4 KiB)": "S3 Files metadata read ({ops} operations x 4 KiB)",
        "{pct}% = {gib} ({tib} TiB) / {count} 個。残り {rest_pct}% ({rest_gib}) は月内に読まれない": "{pct}% = {gib} ({tib} TiB) / {count} objects. The other {rest_pct}% ({rest_gib}) is not read within the month",
        "100% = 保存量の全体 ({gib}) / {count} 個。月内に全件が読まれる": "100% = the whole stored volume ({gib}) / {count} objects. Every object is read within the month",
        "0 GiB / 0 個 / チャーン率 0% (書き込みなし)": "0 GiB / 0 objects / churn rate 0% (no writes)",
        "{gib} ({tib} TiB) / {count} 個 / チャーン率 {pct}% (保存量の {ratio} 倍)": "{gib} ({tib} TiB) / {count} objects / churn rate {pct}% ({ratio}x the stored volume)",
        "書き込みなし。保存量は {gib} のまま一定。"
        "書き込みがあるパターンでも、書き込みは既存オブジェクトの置き換えで保存量は変わらない": "No writes. The stored volume stays at {gib}. "
        "Where a pattern does write, the writes replace existing objects and the stored volume does not change",
        "書き込みは既存オブジェクトの置き換えで、保存量は {gib} のまま一定。月を通して積み増さない": "Writes replace existing objects, so the stored volume stays at {gib}. Nothing accumulates over the month",
        "1. 保存量 (論理) と保存オブジェクト数": "1. Stored volume (logical) and stored object count",
        "{gib} ({tib} TiB) / {count} 個": "{gib} ({tib} TiB) / {count} objects",
        "2. オブジェクトサイズ": "2. Object size",
        "3. 作業セット (月内に読まれる部分)": "3. Working set (the part read within the month)",
        "4. 作業セット内の読み取り回数": "4. Reads per working-set object",
        "作業セットの各オブジェクトを月 {n} 回": "Each working-set object is read {n} times a month",
        "5. 月間読み取り (バイト / 回数 / 保存量に対する倍数 R)": "5. Read per month (bytes / requests / multiple of stored volume, R)",
        "{gib} ({tib} TiB) = {ws_gib} × {n} 回 / {requests} 回 / R = {r} 倍": "{gib} ({tib} TiB) = {ws_gib} x {n} reads / {requests} requests / R = {r}x",
        "6. 月間書き込み (バイト / 個数 / 保存量に対する比 = チャーン率)": "6. Written per month (bytes / objects / ratio to stored volume = churn rate)",
        "7. 読み : 書き (バイト比。操作数の比ではない)": "7. Read : write (byte ratio, not an operation-count ratio)",
        "8. リテンション": "8. Retention",
        "書き込みがないセルの S3 Files ({threshold} KiB 以下) は、"
        "初回読み出しのストリームを計上しない。"
        "読み取りはすべて高性能ストレージの読み取りとして計上している": "In a cell with no writes, S3 Files ({threshold} KiB or smaller) books no first-read stream; every read is booked as a high-performance-storage read",
    }
)

# --- PR-A: assumptions registry, overrides notice, and validation errors ------------------------
#
# These strings are reached only through the --assume / --baseline-table / --list-assumptions paths,
# never through render(), so --translation-gaps (which renders) does not see them. They are
# translated here so the English CLI output carries no Japanese.
TRANSLATIONS.update(
    {
        # --- --list-assumptions column headers ---------------------------------------------------
        "キー": "key",
        "型": "type",
        "検証": "validation",
        "基準値の区分": "baseline tier",
        "読者が決められるか": "reader decides?",
        "説明": "description",
        "数値": "number",
        "整数": "integer",
        "列挙": "enumeration",
        # --- baseline tiers (基準値の区分) --------------------------------------------------------
        "公式": "documented",
        "観測": "observed",
        "試算前提": "modelling assumption",
        "仮置き": "placeholder",
        "定義": "definition",
        # --- ASSUMPTION_SPECS descriptions --------------------------------------------------------
        "デプロイ形態（可用性と世代）": "Deployment option (availability and generation)",
        "SSD 層のストレージ効率": "Storage efficiency on the SSD tier",
        "キャパシティプール層に残る SSD 効率の割合": "Fraction of the SSD efficiency that survives on the capacity pool tier",
        # "キャパシティプールへ落とす割合" and "SSD のプロビジョニング余裕" are already in the
        # table above (they appear as scenario labels), so they are not repeated here.
        "スループットキャパシティ（指定の段 MBps、auto でモデルが選ぶ）": "Throughput capacity (a tier in MBps; auto lets the model choose)",
        "S3 Files 高性能ストレージのアクティブ割合（auto で現行の式）": "S3 Files high-performance-storage active fraction (auto uses the current formula)",
        "S3 Files の取り込みしきい値（KiB）": "S3 Files import threshold (KiB)",
        "初回ストリームに数える個数（written: 書いた個数 / none: 0 / working_set: 作業セット）": "Objects counted on first-read stream (written: objects written / none: 0 / working_set: the working set)",
        "初回ストリームのファイル読み取り課金（none: なし / file_read: 課金する）": "File-read charge on the first-read stream (none: not charged / file_read: charged)",
        "読み取り側メタデータの操作数倍率": "Multiplier on the read-side metadata operation count",
        "月間読み取り量に掛ける倍率（1.0 = パターンの定義どおり）": "Multiplier on the monthly read volume (1.0 = as the pattern defines it)",
        "保存量（TiB）": "Stored volume (TiB)",
        "非現行バージョンの保持容量（GiB、S3 Files 側）。S3 Standard の増分として算入": "Retained noncurrent-version capacity (GiB, S3 Files side); added as extra S3 Standard storage",
        "スナップショットの保持容量（GiB、FSx for ONTAP 側）。層・課金が未確認のため式に算入せず入力のみ（open 未確認）": "Retained snapshot capacity (GiB, FSx for ONTAP side); the tier and charge are unconfirmed, so it is an input only and not put into the formula (open/unconfirmed)",
        # --- ASSUMPTION_SPECS domain text ---------------------------------------------------------
        "0 以上 1 未満": "0 or more, less than 1",
        "0 以上 1 以下": "0 to 1 inclusive",
        "0 より大きい。格子のサイズと同値は不可": "greater than 0; not equal to a grid size",
        "0 以上の有限値": "a finite value of 0 or more",
        "0 より大きい有限値": "a finite value greater than 0",
        # --- ASSUMPTION_SPECS reader-decides text -------------------------------------------------
        "決める（可用性要件）": "decide (availability requirement)",
        "決められる（データの性質）": "can decide (property of the data)",
        "データごとに測る（一般値なし）": "measure per dataset (no general value)",
        "決められる": "can decide",
        "決める（運用方針）": "decide (operational policy)",
        "決める（ピーク要件）": "decide (peak requirement)",
        "アクセスの形で決まる": "set by the access pattern",
        "決める（設定）": "decide (a setting)",
        "読み取りの時間的な偏りで決まる": "set by the temporal skew of reads",
        "課金の実際が未確認（両方で試算できる）": "the actual billing is unconfirmed (estimate both ways)",
        "マウントオプションで動く": "moves with the mount options",
        "決める（自分のワークロード）": "decide (your own workload)",
        "決める": "decide",
        "決める（バージョニングの保持方針）": "decide (versioning retention policy)",
        "決める（スナップショットの保持方針）": "decide (snapshot retention policy)",
        # --- --baseline-table framing -------------------------------------------------------------
        "基準の前提（公開文書と同じ）": "Baseline assumptions (the same as the published document)",
        "※ 必要なスループットが最大段を超える。モデルの適用範囲外": "* The required throughput exceeds the maximum tier; outside the model's range",
        "主要費目小計。月額総額ではない。試算であり実測ではない": "Major-line-item subtotals, not monthly totals; estimates, not measurements",
        # --- the file-read stream line ------------------------------------------------------------
        "S3 Files 初回ストリームのファイル読み取り ({count} 個 × {size})": "S3 Files first-read stream as a file read ({count} objects x {size})",
        # --- read-side metadata line with a non-default multiplier --------------------------------
        "S3 Files メタデータ読み取り ({ops} 操作 × 4 KiB × {m})": "S3 Files metadata reads ({ops} operations x 4 KiB x {m})",
        # --- notice -------------------------------------------------------------------------------
        "この出力は基準の前提と異なる（変更 {count} 件: {changes}）。公開文書の値ではない。{caveat}": "This output uses assumptions that differ from the baseline ({count} changed: {changes}). These are not the values in the published document. {caveat}",
        "{key}={value}（基準 {baseline}）": "{key}={value} (baseline {baseline})",
        "{key}={value}（基準と同じ値を明示）": "{key}={value} (baseline value, set explicitly)",
        "仮置きまたは未測定の前提を含む: {keys}。": "Includes placeholder or unmeasured assumptions: {keys}. ",
        "初回読み出しを数える変種は取り込み書き込みを含まない部分的な計上で、小計の増減の向きは定まらない。": "Counting the first read is a partial accounting that leaves out the import write, so the direction of the change in the subtotal is not determined. ",
        "初回ストリームにファイル読み取り課金が付くかどうかは、公式の文面が揃わず、課金の実際は未確認である。": "Whether the first-read stream carries a file-read charge is worded inconsistently in the documentation, and the actual billing is unconfirmed. ",
        "スループットは読者の指定で、モデルが選んだ段ではない。": "Throughput is the value you set, not a tier the model chose. ",
        "指定の段が平均所要を下回るセルが {n} 個ある。": "In {n} cell(s) the tier you set is below the sustained requirement. ",
        "{n} 個のセルは、必要なスループットがこの構成の最大段を超え、FSx for ONTAP の小計が最大段で頭打ちになっている（モデルの適用範囲外）。": "In {n} cell(s) the required throughput exceeds this configuration's maximum tier, so the FSx for ONTAP subtotal is capped at the maximum tier (outside the model's range). ",
        # --- validation errors (JA source is the key, per the t() convention) ---------------------
        "未知の前提 `{key}`。使えるキーは `--list-assumptions` で確認する": "Unknown assumption `{key}`. Run `--list-assumptions` for the accepted keys.",
        "`{item}` は key=value の形ではない": "`{item}` is not in key=value form.",
        "`{key}` が複数回指定されている": "`{key}` is given more than once.",
        "`{key}` の値 `{value}` を {kind} として読めない": "The value `{value}` for `{key}` cannot be read as {kind}.",
        "`{key}` は有限の数値で指定する（NaN と無限大は不可）": "`{key}` must be a finite number (NaN and infinity are not accepted).",
        "`{key}` の指定値 {value} は許容範囲 {domain} の外": "The value {value} for `{key}` is outside the accepted range {domain}.",
        "`{key}` は {choices} のいずれかで指定する（指定値 {value}）": "`{key}` must be one of {choices} (given: {value}).",
        "スループット {value} MBps は {deployment} の段 {tiers} にない": "{value} MBps is not a throughput tier of {deployment} ({tiers}).",
        "`s3files_threshold_kib` を格子のサイズ（{sizes}）と同じ値にできない。ちょうどのサイズの扱いが公式の文面で揃っていない": "`s3files_threshold_kib` cannot equal a grid size ({sizes}). The documentation words the boundary case inconsistently.",
    }
)

# --- the sensitivity section (PR-B) -----------------------------------------------------------
TRANSLATIONS.update(
    {
        # Headings.
        "### 基準の前提と感度": "### Baseline assumptions and sensitivity",
        "#### 前提の一覧": "#### List of assumptions",
        "#### 前提を 1 つずつ動かしたときの小計": "#### Subtotals when one assumption moves at a time",
        "#### 小計の高低が入れ替わる前提の値": "#### Assumption values at which the lower subtotal changes sides",
        "#### 2 つの前提の組での入れ替わり": "#### Changes of sides under two assumptions together",
        "#### 複数の前提を同時に動かしたシナリオ": "#### Scenarios that move several assumptions together",
        "#### 算入していない費目": "#### Items not included",
        "#### 自分の値での試算手順": "#### Procedure for running your own values",
        "#### 誤読を防ぐ注": "#### Notes against misreading",
        # Intro.
        "この節は、基準の前提（論理 20 TiB、capacity pool {pool}%、SSD 効率 {eff}% など）で出した小計が、前提の置き方でどう動くかを示す。表の小計はモデルの計算値で、実測ではない。いずれも**主要費目小計**であって月額総額ではない。": "This section shows how the subtotals computed under the baseline assumptions (20 TiB logical, {pool}% capacity pool, {eff}% SSD efficiency, and so on) move as the assumptions are placed differently. The subtotals in the tables are the model's computed values, not measurements, and every one is a **major-line-item subtotal**, not a monthly total.",
        "対象は、図で使う 5 パターン（{patterns}）× 2 サイズ（64 KiB、4 MiB）である。32 セル全部の格子は「共通ベースライン」の節にある。小計の低い側はセルに印を置かず、基準と低い側が入れ替わったパターンを別列に挙げる。": "The scope is the five figure patterns ({patterns}) crossed with the two figure sizes (64 KiB, 4 MiB). The full 32-cell grid is in the common-baseline section. The lower side is not marked on the cell; patterns whose lower side differs from the baseline are listed in a separate column.",
        # Direction sentences.
        "基準の前提では、図の 5 パターンのうち 64 KiB のセルは {low64} の小計が低く、4 MiB のセルは {low4m} の小計が低い。向きを分けているのはオブジェクトサイズである。": "Under the baseline assumptions, across the five figure patterns the 64 KiB cells have the lower {low64} subtotal and the 4 MiB cells have the lower {low4m} subtotal. What divides the direction is object size.",
        "基準の前提で小計が低い側は、セルごとに次のとおり: {cells}。": "Under the baseline assumptions the lower side is, cell by cell: {cells}.",
        "{pattern} {size}: {low}": "{pattern} {size}: {low}",
        "4 MiB のセルは、出典のある点で前提を 1 つずつ動かしても向きが変わらない。出典のある範囲の外では、{clauses}（詳細は損益分岐の表）。": "The 4 MiB cells do not change direction when one assumption is moved to any sourced point. Outside the sourced range, {clauses} (see the break-even table for the detail).",
        "{key} が {lo}〜{hi} の範囲で低い側が入れ替わる": "{key} changes the lower side across {lo}-{hi}",
        "4 MiB のセルは、出典のある点で前提を 1 つずつ動かしても向きが変わらない。出典のある範囲の外でも、探索範囲では向きが変わらない。": "The 4 MiB cells do not change direction when one assumption is moved to any sourced point, and do not change direction within the search range outside it either.",
        "4 MiB のセルのうち、出典のある点で向きが変わるのは次のとおり: {parts}。": "The 4 MiB cells that change direction at a sourced point are: {parts}.",
        "FSx for ONTAP の小計が下がる側へ 3 前提を同時に動かすと（J1）、{n} パターンで低い側が入れ替わる。3 前提のうち pool 層の効率の保持（1.0）には出典がない。J1 から 1 前提だけを基準に戻すと、入れ替わりが残るのは {kept}、消えるのは {removed} である。": "Moving three assumptions together toward a lower FSx for ONTAP subtotal (J1) changes the lower side in {n} pattern(s). Of the three, the pool-layer efficiency retention (1.0) has no source. Reverting one assumption of J1 to baseline, the change persists for {kept} and disappears for {removed}.",
        "J1 では 4 MiB のどのパターンでも低い側は変わらない。": "In J1 the lower side does not change for any 4 MiB pattern.",
        "64 KiB のセルの向きは、S3 Files の高性能ストレージのアクティブ割合に依存する。アクティブ割合が {parts}（それぞれ以下）で S3 Files の小計が低くなる。残りのパターンは探索範囲では入れ替わらない。基準の値は 100% で、この割合は**仮置き・未測定**である。": "The direction of the 64 KiB cells depends on the active fraction resident on S3 Files high-performance storage. At or below an active fraction of {parts} the S3 Files subtotal is the lower one; the remaining patterns do not change within the search range. The baseline value is 100%, and this fraction is a **placeholder, unmeasured**.",
        "64 KiB のセルは、アクティブ割合を 0〜100% の範囲で動かしても向きが変わらない。基準の値は 100% で、この割合は**仮置き・未測定**である。": "The 64 KiB cells do not change direction as the active fraction moves across 0-100%. The baseline value is 100%, and this fraction is a **placeholder, unmeasured**.",
        "隣接の実測では、作業セット 5% / 20% のとき `StorageBytes` の 5.47% / 21.89% が高性能ストレージの指標に載った（1 回の観測、2026-10-17、ap-northeast-1、`ON_DIRECTORY_FIRST_ACCESS`。`StorageBytes` はデータとメタデータの合計で、作業セット比は実験が設定した値。アクティブ割合そのものの測定ではない）。": "An adjacent measurement observed, for working sets of 5% / 20%, that 5.47% / 21.89% of `StorageBytes` showed up on the high-performance-storage metric (one observation, 2026-10-17, ap-northeast-1, `ON_DIRECTORY_FIRST_ACCESS`. `StorageBytes` is the sum of data and metadata, the working-set ratio is the value the experiment set, and this is not a measurement of the active fraction itself).",
        "{keys} は未測定または出典のない仮置きである。表の値はこれらを仮置きしたものである。": "{keys} are unmeasured or sourceless placeholders. The values in the tables place these as placeholders.",
        # Misreading notes.
        "1. 前提を動かす範囲には、出典のあるものと機械的なものがある。表の「範囲の根拠」列で区別する。機械的な値（0%、50%、100%、0.5 倍、2 倍など）は、振る位置を決めただけで、確率的な幅や起こりやすさを表さない。": '1. The range over which an assumption is moved is sometimes sourced and sometimes mechanical. The "range basis" column distinguishes them. A mechanical value (0%, 50%, 100%, 0.5x, 2x, and so on) only fixes where to probe; it expresses no probabilistic spread or likelihood.',
        "2. 出典の厚みが両側で違う。FSx for ONTAP 側には効率、cold:hot 比、SSD 使用率の推奨、デプロイ形態に公式の数値がある。S3 Files 側のアクティブ割合には、今回読んだ公式ページに数値の範囲がない。表で FSx for ONTAP の前提の行が出典ありで、S3 Files の前提の行が機械的な範囲に偏るのは、この差による。": "2. The weight of sources differs between the two sides. The FSx for ONTAP side has documented figures for efficiency, the cold:hot ratio, the SSD-utilization recommendation, and deployment generation. The S3 Files active fraction has no numeric range in the documentation read here. That the FSx for ONTAP assumption rows are sourced while the S3 Files assumption rows lean on mechanical ranges follows from this difference.",
        "3. 小計の動く幅を製品の性質と読まない。4 MiB のセルの S3 Files の小計は S3 Standard の保管料が大半を占める。動きが小さいのはこのセルの構成による。": "3. Do not read the size of a subtotal's movement as a property of the product. The S3 Files subtotal of a 4 MiB cell is mostly S3 Standard storage; the small movement is a property of this cell's composition.",
        "4. 「出典のある範囲」は、範囲の根拠が「出典」の点の最小〜最大の区間である。点が 1 つしかない前提は区間にならず、「出典のある値が 1 点」と書く。": '4. The "sourced range" is the interval from the lowest to the highest point whose range basis is "sourced". An assumption with only one such point is not an interval and is written as "one sourced value".',
        "5. FSx for ONTAP の小計は、必要なスループットが構成の最大段を超えると、最大段で頭打ちになる。その領域はモデルの適用範囲外である。損益分岐の算出は、探索範囲を適用範囲の上限で切り詰めてこの領域を含めない。1 つずつ動かした表・シナリオ・2 つの前提の組の表では、適用範囲外に落ちたセルの値に ※ を付けて載せ、そのセルを向きの導出から除く。": "5. The FSx for ONTAP subtotal is capped at the maximum tier once the required throughput exceeds the configuration's maximum tier. That region is outside the model's range. The break-even computation truncates the search range at the applicable upper bound and does not include it. In the one-at-a-time, scenario, and two-assumption tables, a cell that falls outside the range is shown with a ※ and excluded from the direction judgement.",
        "6. 「1 つずつ動かした表」は、他の前提を基準に固定している。複数を同時に動かした結果は「シナリオ」の節にある。1 つずつでは向きが変わらない前提でも、同時に動かすと変わりうる。": "6. The one-at-a-time table holds the other assumptions at baseline. Results of moving several together are in the scenarios section. An assumption that does not change the direction on its own can change it when moved together with others.",
        "7. 基準の値は推奨値ではない。基準は、全パターンを同じ条件で並べるために置いた値である。": "7. The baseline value is not a recommended value. The baseline is a value placed so that all patterns can be laid out under the same conditions.",
        "8. 基準の前提では、アクティブ割合は上限の 100% で、S3 Files の小計を上げる方向に動かせる余地がない。この前提は下げる方向にだけ振る。これは基準の置き方の性質で、製品の性質を述べるものではない。": "8. Under the baseline assumptions the active fraction is at its 100% ceiling, so there is no room to move it in the direction that raises the S3 Files subtotal; it is swept only downward. This is a property of how the baseline is placed, not a statement about the product.",
        # Assumption list.
        "「基準値の区分」は基準値の出どころ（公式 / 観測 / 試算前提 / 仮置き / 定義）で、次の表の「範囲の根拠」（出典 / 観測 / 再利用 / 機械的）とは別の区分である。「出典のある範囲」は、範囲の根拠が「出典」の点の最小〜最大の区間を指す。「再利用」は、このリポジトリの別の節が置いた値の再利用で、外部の根拠でも測定でもない。": 'The "baseline-value tier" is where the baseline value comes from (documented / observed / estimation premise / placeholder / definition), a different classification from the "range basis" (sourced / observed / reused / mechanical) in the next table. The "sourced range" is the interval from the lowest to the highest point whose range basis is "sourced". "Reused" is the reuse of a value placed by another section of this repository, neither an external source nor a measurement.',
        "基準の値": "Baseline value",
        "出典・根拠": "Source / basis",
        "小計が動く側": "Side the subtotal moves",
        "両側": "both sides",
        "単価の日付": "Unit-price date",
        "Price List のスナップショット日": "Price List snapshot date",
        "保存量の定義": "Definition of stored volume",
        "論理 {tib} TiB": "{tib} TiB logical",
        "全セル共通の土俵": "the common ground shared by all cells",
        "価格の作業セット比非連動": "Pricing independent of the working-set ratio",
        "連動しない": "does not depend on it",
        "金額は読み書き量とサイズで決まる": "the amount is set by read/write volume and size",
        "検証リージョン": "verification region",
        # One-at-a-time.
        "他の前提を基準に固定し、1 つの前提だけを動かしたときの小計である。セルは `FSx for ONTAP {小計} / S3 Files {小計}`（USD / 月、主要費目小計）。低い側を示す印は置かず、「向きが基準と異なるパターン」列に、基準と低い側が入れ替わったパターンを並べる（なければ —）。※ は必要なスループットが最大段を超え、モデルの適用範囲外のセル。": 'Subtotals with the other assumptions held at baseline and one assumption moved. Each cell is `FSx for ONTAP {subtotal} / S3 Files {subtotal}` (USD/month, major-line-item subtotal). No mark shows the lower side; the "patterns whose direction differs from the baseline" column lists the patterns whose lower side changed (— if none). A ※ marks a cell whose required throughput exceeds the maximum tier, outside the model\'s range.',
        "オブジェクト {size} の場合": "Object size {size}",
        "FSx for ONTAP {fsx} / S3 Files {files}{mark}": "FSx for ONTAP {fsx} / S3 Files {files}{mark}",
        "基準": "baseline",
        "向きが基準と異なるパターン": "Patterns whose direction differs from the baseline",
        "範囲の根拠": "Range basis",
        "（n>1 のパターンは再読み取りの操作数が未測定）": " (for n>1 patterns the re-read operation count is unmeasured)",
        "このサイズでは次の前提は小計を動かさない: {keys}。": "At this size the following assumptions do not move the subtotals: {keys}.",
        # Range basis / tier words ("観測" already defined above).
        "出典": "sourced",
        "再利用": "reused",
        "機械的": "mechanical",
        # Break-even.
        "連続な数値の前提について、低い側が入れ替わる値 x* を決定的な二分法で求める。探索範囲を適用範囲の上限で切り詰め、256 区間に分けて符号の変わる区間を二分する。値は有効数字 3 桁。「なし」は探索範囲内で入れ替わらないことを指し、範囲外の主張はしない。列挙の前提（`deployment`、`throughput_mbps`、`first_read_mode`、`first_read_stream_billing`）は、「前提を 1 つずつ動かしたとき」の表の「向きが基準と異なるパターン」列で扱う。`active_fraction` は 64 KiB のみ、4 MiB は「対象外」。": 'For the continuous numeric assumptions, the value x* at which the lower side changes is found by a deterministic bisection. The search range is truncated at the applicable upper bound, split into 256 intervals, and the sign-changing intervals are bisected. Values are to three significant figures. "none" means no change within the search range and makes no claim outside it. The enumerated assumptions (`deployment`, `throughput_mbps`, `first_read_mode`, `first_read_stream_billing`) are handled in the one-at-a-time table\'s "patterns whose direction differs" column. `active_fraction` is 64 KiB only; 4 MiB reads "not applicable".',
        "なし（{hi} まで）": "none (up to {hi})",
        "対象外": "not applicable",
        "{x}（{below}未満で{low_below}、以上で{low_above}{rel}{step}）": "{x} ({below}below it {low_below}, at or above {low_above}{rel}{step})",
        "、出典のある範囲内": ", inside the sourced range",
        "、出典のある範囲の外": ", outside the sourced range",
        "、出典のある値は 1 点（{value}）で x* はそれ{side}": ", one sourced value ({value}) and x* is {side} it",
        "、出典のある範囲なし（機械的な探索範囲）": ", no sourced range (mechanical search range)",
        "、段差": ", step change",
        "より小さい": "smaller than",
        "より大きい": "larger than",
        "しきい値が {size} 未満のとき入れ替わる": "changes when the threshold is below {size}",
        "`{key}`: {lo}〜{hi}": "`{key}`: {lo}-{hi}",
        "探索範囲 [lo, hi]: {ranges}。`read_scale` と `stored_tib` の上限は、必要スループットが最大段以内に収まる値（セルごと）で切り詰める。`stored_tib` の上限 {stored_hi} TiB は出典のない機械的な値である。区間内に 2 点以上の入れ替わりが 1 区間（1/256）に収まる場合は検出できない（テストの密な走査で現行の価格では見落としがないことを確かめている）。": "Search ranges [lo, hi]: {ranges}. The upper bounds of `read_scale` and `stored_tib` are truncated per cell to the value at which the required throughput stays within the maximum tier. The `stored_tib` upper bound of {stored_hi} TiB is a sourceless mechanical value. Two or more changes falling within a single interval (1/256) cannot be detected (a dense sweep in the tests confirms none are missed at the current prices).",
        # Two assumptions.
        "1 次元の損益分岐は他の前提に依存する。依存の大きい 2 つの組を同じ算出で出す。セルは入れ替わる値 x*（なければ「なし」）。": 'The one-dimensional break-even depends on the other assumptions. The two most dependent pairs are produced by the same computation. Each cell is the change value x* ("none" if there is none).',
        "固定: `pool_fraction`、動かす: `active_fraction`（64 KiB）": "Fixed: `pool_fraction`; moved: `active_fraction` (64 KiB)",
        "固定: `pool_fraction` × `pool_efficiency_retention`、動かす: `efficiency_ssd`（4 MiB）": "Fixed: `pool_fraction` x `pool_efficiency_retention`; moved: `efficiency_ssd` (4 MiB)",
        # Scenarios.
        "複数の前提を同時に動かした結果である。名前は動かす方向（その側の小計が下がる / 上がる）で付け、「有利」「不利」は使わない。J1〜J4 は 3・3・2・2 前提で、完全には揃わない。基準のアクティブ割合が上限の 100% で S3 Files の小計を上げる余地がなく、上げる側に置ける前提が`metadata_multiplier`・`first_read_stream_billing` に限られること、および向きの定まらない `first_read_mode=none` を J3 から外したことによる。同時に動かした値の組は予測でも推奨でもなく、向きが変わりうることを示す例である。": 'Results of moving several assumptions together. The names are given by the direction moved (that side\'s subtotal goes down / up), not by "favourable" or "unfavourable". J1-J4 move 3, 3, 2, and 2 assumptions and are not perfectly matched: with the baseline active fraction at its 100% ceiling there is no room to raise the S3 Files subtotal, so the assumptions that can be placed on the raising side are limited to `metadata_multiplier` and `first_read_stream_billing`, and the direction-indeterminate `first_read_mode=none` was dropped from J3. A set of simultaneously moved values is neither a prediction nor a recommendation; it is an example showing that the direction can change.',
        "{id}（{n} 前提）": "{id} ({n} assumptions)",
        "シナリオ": "Scenario",
        "{id} − {key}": "{id} - {key}",
        "J1 のような組み合わせが実在の構成として成立するか（pool 80% で SSD の最小値に当たる場合など）は確認していない。": "Whether a combination like J1 holds as a real configuration (for instance when pool 80% hits the SSD minimum) has not been confirmed.",
        # Not included.
        "非現行バージョンの保持（S3 Files 側）とスナップショットの保持（FSx for ONTAP 側）は、両側の式が未測定で、書き込みの多いパターンでは小計を大きく動かしうる。保持日数を入力にするのは PR-A2（この作業の範囲外）で、ここでは未算入として注記する。": "Noncurrent-version retention (S3 Files side) and snapshot retention (FSx for ONTAP side) have formulas that are unmeasured on both sides and can move the subtotals substantially in write-heavy patterns. Taking the retention days as an input belongs to PR-A2 (outside the scope of this work); here it is noted as not included.",
        # C1 (PR-A2): retention-days inputs. Top note after both sides became inputs.
        "非現行バージョンの保持（S3 Files 側）は `--assume noncurrent_version_gib=GiB` で入力でき、S3 Standard の増分として小計に算入する（既定 0）。スナップショットの保持（FSx for ONTAP 側）は `--assume snapshot_gib=GiB` で入力を受けるが、どの層に置かれ、どう課金されるかが公式文面で揃わず、式には算入しない（既定 0、open 未確認）。どちらも保持日数から容量を導く式は未測定なので、容量を直接与える。": "Noncurrent-version retention (S3 Files side) can be entered with `--assume noncurrent_version_gib=GiB` and is added to the subtotal as extra S3 Standard storage (default 0). Snapshot retention (FSx for ONTAP side) takes an input with `--assume snapshot_gib=GiB`, but which tier it sits on and how it is charged are not consistent across the official pages, so it is not put into the formula (default 0, open/unconfirmed). Neither has a measured formula from retention days to capacity, so capacity is given directly.",
        "保持分がどの層に置かれ、どう課金されるかで公式文面が揃わない": "the official pages are not consistent on which tier the retained data sits on or how it is charged",
        "入力あり（snapshot_gib）、式に算入しない": "input available (snapshot_gib), not put into the formula",
        "数値は書かない。「根拠の確からしさ」は documented / verified / hypothesis / open の 4 語で付ける。": 'No numbers are given. The "confidence of basis" uses the four words documented / verified / hypothesis / open.',
        "費目": "Item",
        "向き": "Direction",
        "根拠": "Basis",
        "根拠の確からしさ": "Confidence of basis",
        "状態": "Status",
        "非現行バージョンの保持（S3 Files 側）": "Noncurrent-version retention (S3 Files side)",
        "S3 Files の小計が上がる": "the S3 Files subtotal rises",
        "S3 Files の小計が上がる。書き込みの多いパターンで大きい": "the S3 Files subtotal rises; larger in write-heavy patterns",
        "S3 Files はバージョニング必須（公式の同期のページ）": "S3 Files requires versioning (documented on the sync page)",
        "documented（公式の同期のページ）。影響の大きさは hypothesis": "documented (the sync page); the size of the effect is hypothesis",
        "未算入（日数の入力は PR-A2）": "not included (days as an input is PR-A2)",
        "スナップショットの保持（FSx for ONTAP 側）": "Snapshot retention (FSx for ONTAP side)",
        "FSx for ONTAP の小計が上がる見込み": "the FSx for ONTAP subtotal is expected to rise",
        "保持分がどの層に置かれ、どう課金されるかを公式文書で読んでいない": "this design has not read in the documentation which tier the retained data sits on or how it is charged",
        "open（未確認。方向も未確認）": "open (unconfirmed; the direction too)",
        "pool 配置分のメタデータ用 SSD": "Metadata SSD for the pool-placed data",
        "FSx for ONTAP の小計が上がる": "the FSx for ONTAP subtotal rises",
        "公式の文面「ファイルのメタデータは常に SSD 層に残る」。目安は 1 点（サイジングブログ）": "the documented statement that file metadata always remains on the SSD tier; one rough figure (the sizing blog)",
        "documented（公式のボリューム容量ページ、サイジングブログ）。基準単位は open": "documented (the volume-capacity page, the sizing blog); the base unit is open",
        "未算入（PR-A2 の判断待ち）": "not included (pending the PR-A2 decision)",
        "SSD IOPS の追加、バックアップ、スナップショット予約": "Added SSD IOPS, backup, snapshot reserve",
        "単価と課金の仕組みをこの設計では公式文書で読んでいない": "this design has not read the unit price and charging mechanism in the documentation",
        "open": "open",
        "pool への書き込みリクエスト": "Write requests to the pool",
        "モデルに単価が定義済みで、式に使っていない（コードで確認）": "a unit price is defined in the model but not used in the formula (confirmed in the code)",
        "open（コードの事実は verified）": "open (the fact about the code is verified)",
        "pool 読み取りの操作数": "Pool read operation count",
        "FSx for ONTAP の小計": "the FSx for ONTAP subtotal",
        "数え方が文書内で 3 通りあり、未確認": "the documentation counts it in three ways and it is unconfirmed",
        "小計に算入しているが未確認": "included in the subtotal but unconfirmed",
        "S3 Access Points 経由の GET": "GETs through S3 Access Points",
        "モデルは経由の PUT だけを足す（コードで確認）。GET の課金は単価と経路に依存": "the model adds only the PUT through the access point (confirmed in the code); the GET charge depends on the unit price and the path",
        "open（コードの事実は verified、単価は未再取得）": "open (the fact about the code is verified; the unit price was not re-fetched)",
        "高性能ストレージ上のメタデータの保管": "Storage of metadata on high-performance storage",
        "公式は、アクセスしたディレクトリのメタデータは期限切れにならないと書く。課金の基準が文書にない": "the documentation states that metadata of an accessed directory does not expire; the charging basis is not in the documentation",
        "documented（公式の計量ページ）。課金の基準は open": "documented (the metering page); the charging basis is open",
        "未算入": "not included",
        # Procedure.
        "受け付ける前提の一覧は `--list-assumptions` で確認する。自分の環境の値は `--assume key=value` で与え、公開文書の値とは比べない。比べるのは、同じ前提を置いた 2 つの出力どうしである。小計は主要費目小計で、月額総額ではない。": "Check the list of accepted assumptions with `--list-assumptions`. Give your own environment's values with `--assume key=value`, and do not compare against the values in the published document; compare two outputs that place the same assumptions. The subtotals are major-line-item subtotals, not monthly totals.",
        "値はコマンドの書式の例で、勧める値でも結果の予測でもない。": "The values are an example of the command form, neither recommended values nor a prediction of the result.",
        "# 1. 受け付ける前提の一覧（キー、既定値、許容範囲、基準値の区分）": "# 1. The list of accepted assumptions (key, default, accepted range, baseline-value tier)",
        "# 2. 自分の環境の値で小計の表を出す（保存量 50 TiB、Multi-AZ、SSD 層の効率 65%、pool 70%）": "# 2. Print the subtotal table with your own values (50 TiB stored, Multi-AZ, 65% SSD-tier efficiency, 70% pool)",
        "# 3. 内訳まで JSON で出し、英語のラベルで保存する（アクティブ割合を測った値に置き換えた例）": "# 3. Print the breakdown as JSON with English labels (example replacing the active fraction with a measured value)",
    }
)
