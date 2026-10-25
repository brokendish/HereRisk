# Phase 2-C 公式データ取得可否調査（Official Data Source Availability Survey）

- Task: Phase 2-C Official Data Source Availability Survey
- 調査日時: 2026-10-25（UTC 05:31〜05:40頃）
- 調査者: Claude
- 基準コミット: `a4d8b39973ef33cba99aa55f92ede2f9c3cc6228`
- 成果物:
  - 取得元台帳 [docs/data-sources/official-source-ledger.json](../../docs/data-sources/official-source-ledger.json)
  - Schema案 [official-source-ledger.schema.json](../../docs/architecture/schemas/official-source-ledger.schema.json)
  - 台帳の設計 [Official Source Ledger v0.1](../../docs/architecture/official-source-ledger-v0.1.md)
  - 本書

**本工程は取得元の調査と設計であり、実データの取得・製品実装・公開の承認ではない。** 製品コード・実データ・Registry実体・VPS・Dockerは変更していない。

## 0. 調査の方法と制約

| 行ったこと | 内容 |
|---|---|
| 公式ページの閲覧 | 国土数値情報のデータページ（A31a・A40・A49・A33・N03）・利用規約、国土地理院の基盤地図情報ダウンロードサービスのヘルプ。データページのHTML（公開ページ。最大約1.9MB）は、作業用ディレクトリに保存してリンク先を読んだ（リポジトリには保存していない） |
| HTTPのHEAD（本文なし） | 東京都の最新版の配布ZIP 5件、製品仕様書PDF 4件、標高タイル1件。応答のステータス・`Content-Length`・`Last-Modified` だけを記録した |
| 既存の記録の参照 | Phase 1（標高）・Phase 2-A（A31a・N03）の取得記録、国土地理院の回答記録（問合せ番号92497） |

行っていないこと:

- 実データ（ZIP・タイルの本文）の取得
- 認証が必要なサービスへのログイン
- スクレイピング対策の迂回
- 認証情報の記録

そのため、本調査で新たに `download_verified` になったデータはない。`download_verified` の4件は、すべてPhase 2-Aの既存の取得記録による。

## 1. 5つのAPIの取得可否（要約）

| API | 主な公式データ | 取得の状態 | 利用条件の状態 | 要点 |
|---|---|---|---|---|
| 標高 | 国土地理院 地理院タイル 標高タイル DEM10B `dem_png` | `download_url_confirmed`（HEAD 200） | `review_required` | 測量法上の承認申請は不要との回答あり（92497。照会した利用形態に限る）。出典文言は未確定。実取得の結果（日時・SHA-256）はリポジトリに記録がない |
| 洪水 | 国土数値情報 A31a（2025年度）東京都2件・関東地方整備局1件、補助 N03 | A31a 3件と N03 2025年版は `download_verified`（Phase 2-A）。N03 2026年版は `download_url_confirmed` | `review_required` | ZIP内メタデータ「国土情報利用約款を参照」とデータページ「CC_BY_4.0」の不一致が未解決 |
| 津波 | 国土数値情報 A40（2024年度版。東京都は2023年データ） | `download_url_confirmed` | `review_required` | 東京都は商用利用・再配信可の区分。東京都の行はGMLだけ |
| 高潮 | 国土数値情報 A49（2024年度版。東京都は2020年データ） | `download_url_confirmed` | `review_required` | 東京都は商用利用・再配信可の区分。区分が都の公表図と異なる場合がある |
| 土砂災害 | 国土数値情報 A33（2025年度版。基準日 2025-08-01） | `download_url_confirmed` | `review_required` | 東京都は商用利用・再配信可の区分。**法的図書ではない・重要事項説明等の根拠に使えない・網羅していない**との注意事項 |

`automation_verified` のデータはない（Pipelineによる自動取得の試験は、どのデータでも行っていない）。`usage_terms.status = approved` のデータもない（OWNERの承認を代行していない）。

## 2. 公式取得元のURL一覧

| API | データページ・資料 | 取得先（東京都の最新版） |
|---|---|---|
| 標高 | [地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html)、[標高タイルの詳細仕様](https://maps.gsi.go.jp/development/demtile.html)、[国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html) | テンプレート `https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png`（確認したタイル: `/14/14552/6451.png`） |
| 標高（代替） | [基盤地図情報ダウンロードサービス](https://service.gsi.go.jp/kiban/)、[ヘルプ](https://service.gsi.go.jp/kiban/app/help/) | 利用者登録・ログインが必要（URLは未確認） |
| 洪水 | [A31a データページ（2025）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31a-2025.html)、[製品仕様書 4.3版](https://nlftp.mlit.go.jp/ksj/gml/product_spec/KS-PS-A31a-v4_3.pdf) | `https://nlftp.mlit.go.jp/ksj/gml/data/A31a/A31a-25/A31a-25_13_10_GEOJSON.zip`、`…/A31a-25_13_20_GEOJSON.zip`、`…/A31a-25_83_10_GEOJSON.zip` |
| 洪水（補助） | [N03 データページ（2026）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html)、[製品仕様書 4.1版](https://nlftp.mlit.go.jp/ksj/gml/product_spec/KS-PS-N03-v4_1.pdf) | `https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip`（2025年版: `…/N03-2025/N03-20250101_13_GML.zip`） |
| 津波 | [A40 データページ（2024）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html)、[製品仕様書 2.2版](https://nlftp.mlit.go.jp/ksj/gml/product_spec/KS-PS-A40-v2_2.pdf) | `https://nlftp.mlit.go.jp/ksj/gml/data/A40/A40-23/A40-23_13_GML.zip` |
| 高潮 | [A49 データページ（2024）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A49-2024.html)、[製品仕様書 1.2版](https://nlftp.mlit.go.jp/ksj/gml/product_spec/KS-PS-A49-v1_2.pdf) | `https://nlftp.mlit.go.jp/ksj/gml/data/A49/A49-20/A49-20_13_GML.zip` |
| 土砂災害 | [A33 データページ（2025）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A33-2025.html)、[製品仕様書 2.2版](https://nlftp.mlit.go.jp/ksj/gml/product_spec/KS-PS-A33-v2_2.pdf) | `https://nlftp.mlit.go.jp/ksj/gml/data/A33/A33-25/A33-25_13_GEOJSON.zip`（GML・Shapefileもあり） |
| 共通（国土数値情報） | [利用規約（政府標準利用規約準拠版）](https://nlftp.mlit.go.jp/ksj/other/agreement_01.html) | — |

製品仕様書PDF 4件（A40・A49・A33・N03）は、HEADでHTTP 200を確認した（本文は取得していない）。

## 3. データ形式・最新版・提供範囲

| データ | 最新版（データページ） | 東京都のファイル | 形式（東京都） | 公式の容量 / Content-Length | 提供範囲・配布単位 |
|---|---|---|---|---|---|
| DEM10B `dem_png` | （版の表記なし。DEM10Bは2006年度末時点の地図データ等が基［Phase 1記録］） | タイル（Z1〜14） | PNG | — / 50,651 B（1タイル） | 全国・タイル単位 |
| A31a | 2025年度 | `A31a-25_13_10_GEOJSON.zip`、`A31a-25_13_20_GEOJSON.zip` | GeoJSON・GML・Shapefile | 11.45MB / 12,009,145 B、19.55MB | 都道府県・地方整備局単位（例: 関東地方整備局 507.39MB） |
| N03 | 2026年（令和8年）版 | `N03-20260101_13_GML.zip` | GML（2025年版はGML・GeoJSON・Shapefileを同梱［Phase 2-A.4］） | 12.54MB / 13,153,227 B | 都道府県単位 |
| A40 | 2024年度版（2025年5月更新） | `A40-23_13_GML.zip`（2023年データ） | GML | 8.31MB / 8,710,803 B | 都道府県単位。津波防災地域づくり法に基づく浸水想定を設定した都道府県（データページの記載では2024年1月30日時点で40） |
| A49 | 2024年度版（2025年5月更新） | `A49-20_13_GML.zip`（2020年データ） | GML | 26.5MB / 31,712,745 B | 都道府県単位。整備済み15都府県（データページの一覧） |
| A33 | 2025年度版（2026年5月更新。基準日 2025年8月1日） | `A33-25_13_GEOJSON.zip` | GeoJSON・GML・Shapefile | 6.69MB / 7,011,838 B | 全国・地方・都道府県単位。ポリゴンとライン |

ZIPの中身（メタデータの利用制限・属性・区分のコードリスト）は、A31a・N03（Phase 2-A）以外は未確認である。

## 4. 取得方法・自動化可否

| データ | 認証 | 取得方式 | URLの永続性 | 自動化 |
|---|---|---|---|---|
| `dem_png` | 不要 | HTTPS GET（タイルのURLテンプレート） | テンプレート | 技術的には可能（Phase 1-D.1の取得PoCのコードあり）。**自動取得の試験の結果は未記録**（`not_tested`） |
| 基盤地図情報 DEM | **必要**（利用者登録・ID・パスワード） | ダウンロードサービス（JPGIS（GML）形式） | 不明 | 認証の自動化はしない（`unknown`）。手動取得も試していない |
| A31a・N03・A40・A49・A33 | 不要 | HTTPS GET（ZIP。サーバーは `accept-ranges: bytes` を返す） | 版を含むパス（例: `A33-25/A33-25_13_…`） | `not_tested`。HEADでは `Last-Modified`・`ETag` を返し、更新の確認に使える見込み |

- 国土数値情報・地理院タイルのホストに `robots.txt` はなかった（404・NoSuchKey）。国土数値情報の利用規約にも、自動取得・大量取得の制限の記載はなかった。ただし、**記載がないことを「制限がない」とは扱わない**。大量・定期の取得の可否は未確認事項とする。
- 取得の代替: 国土数値情報の各データは、都道府県・国の機関の公表資料が原典である。代替の公式配布元（東京都の浸水予想区域図・高潮浸水想定区域図・土砂災害警戒区域等の公表）は、**本調査では調べていない**（台帳の `alternatives` に `unknown` として記録した）。

## 5. 利用条件・公開条件の確認状況

| データ | 規約・表記 | 商用 | 加工 | 再配信 | API提供 | 出典・加工表示 | 未解決 |
|---|---|---|---|---|---|---|---|
| `dem_png` | 国土地理院コンテンツ利用規約（PDL1.0） | 可 | 可 | 条件付き | 条件付き（照会した1地点APIは測量法の申請不要: 92497） | 必要（加工の表示を含む） | 出典文言、第三者の権利、公開資格・OWNER承認、配布形態の再照会 |
| A31a | 国土数値情報の利用規約（CC BY 4.0互換）、データページ「CC_BY_4.0」 | 可 | 可 | 可 | 記載なし | 必要 | **ZIP内メタデータ「国土情報利用約款を参照」との不一致**（Phase 2-A.1 U-5） |
| N03 | 同上 | 可 | 可 | 可 | 記載なし | 必要 | N03のデータページの表記の個別確認 |
| A40 | 同上、データページ「CC_BY_4.0（一部制限）」。東京都は「商用利用可・再配信可」の区分 | 可 | 可 | 可 | 記載なし | 必要 | ZIP内メタデータ未確認。宮城・千葉・三重・京都・島根・長崎・大分は条件付き、香川は国土数値情報から提供なし |
| A49 | 同上、「CC_BY_4.0（一部制限）」。東京都は「商用利用可・再配信可」 | 可 | 可 | 可 | 記載なし | 必要 | ZIP内メタデータ未確認。千葉は条件付き |
| A33 | 同上、「CC_BY_4.0（一部制限）」。東京都は「商用利用可・再配信可」 | 可 | 可 | 可 | 記載なし | 必要 | **利用の制限**: 法的図書ではない、重要事項説明・申請資料の根拠に使えない、網羅していない、指定・解除が直ちに反映されない。神奈川・京都・和歌山・広島・長崎・鳥取は条件付き |

「API提供」は、国土数値情報の利用規約が複製・公衆送信・翻案を認める一方で、API提供を名指ししていないため `not_stated` とした。公衆送信・翻案に含まれるかの判断はOWNERが行う。

**すべて `review_required` であり、承認済みのものはない。**

## 6. Data Managerへの接続方針

[Official Source Ledger v0.1](../../docs/architecture/official-source-ledger-v0.1.md) 第2章・第5章のとおり。要点:

- 台帳は「公式の配布についての調査事実」の正本。Source Definition（取得予定）・Acquisition Record（取得実績）・Registry（公開）とは責務を分け、互いに複製しない。
- Data Managerは、配布元・取得の可否・利用条件の確認状況・更新の確認を台帳から、実行状態を各Recordから、公開状態をRegistryから表示する。
- 既存契約への提案（未決定）: Source Definitionに `survey_ref` を追加（OL-C1）、Data Managerの表示の対象に台帳を追加（OL-C2）、利用条件の承認記録への参照（OL-C3）。

## 7. APIごとの実装可否の判断材料

| API | 取得の見通し | 利用条件の見通し | 契約・設計の状況 | 実装前に必要なこと |
|---|---|---|---|---|
| 標高 | タイルのURLは確認済み。取得PoC・Fixture・Pipelineの実装あり | 測量法の申請不要の回答あり。出典文言が未確定 | 契約・実装あり（Phase 1）。公開はBLOCKED | 出典文言の確定、第三者の権利、公開資格の判定、OWNERの公開承認 |
| 洪水 | 取得済み（調査用）。全国展開では関東地方整備局のように500MB超のZIPがある | ライセンス表記の不一致が未解決 | 契約案あり（Normalize・Integration・提示・Catalog）。Phase 2-B.8のBlockingが残る | 利用条件の照会、Phase 2-B.8のBlocking、認可プロファイル |
| 津波 | URL確認済み（東京都 8.31MB。GMLだけ） | 東京都はオープンデータの区分。ZIP内メタデータ未確認 | **個別契約なし** | 小規模な取得試験（OWNER承認）、メタデータ・区分のコードリストの確認、個別契約の作成 |
| 高潮 | URL確認済み（東京都 26.5MB。GMLだけ。2020年データ） | 同上。区分が都の公表図と異なる場合がある | **個別契約なし** | 同上。都の公表図との違いの提示方法 |
| 土砂災害 | URL確認済み（東京都 6.69MB。GeoJSONあり） | 同上。**利用の制限**（法的図書ではない等）を応答・説明でどう伝えるか | **個別契約なし** | 同上。利用の制限と網羅性の注意の提示方法、区域種別のコードリスト |

津波・高潮・土砂災害は、データの取得の見通しは立った。しかし、取得試験・メタデータの確認・個別契約がないため、**実装に進める状態ではない**。いずれもADR-001（複数の公式情報を独立して提示）を適用する。

## 8. OWNER承認事項（小規模な取得試験）

`download_verified` にするための小規模な取得試験を行う場合の候補である。**本工程では実施していない。** 実施にはOWNERの承認が必要である。

| 対象ファイル | 容量（Content-Length） | 取得方法 | 確認すること | 利用条件 |
|---|---|---|---|---|
| `A40-23_13_GML.zip` | 8,710,803 B | HTTPS GET 1回（curl `--proto '=https'`）。リポジトリ外の調査用ディレクトリに保存し、SHA-256・サイズを記録 | ZIPの完全性、メンバー構成、メタデータの利用制限、区分のコード | 東京都はオープンデータの区分（ZIP内の記載は未確認） |
| `A49-20_13_GML.zip` | 31,712,745 B | 同上 | 同上 | 同上 |
| `A33-25_13_GEOJSON.zip` | 7,011,838 B | 同上 | 同上、区域種別のコード | 同上。利用の制限あり |
| `N03-20260101_13_GML.zip` | 13,153,227 B | 同上 | 2025年版との差分（Integration契約 第4.5節のN03の入力資格の対象） | 同上 |

合計約60.6MB。いずれも調査用であり、Pipeline・Registry・公開に使わない前提とする。

## 9. 未確認事項・OWNER判断事項

**未確認事項**

1. A40・A49・A33・N03 2026年版のZIP内メタデータの利用制限の記載（A31aでは表記の不一致があった）。
2. 標高タイルの実取得の結果の記録（Phase 1-D.1のOWNERによる取得の日時・SHA-256）。
3. 大量・定期の自動取得の可否・負荷の制限（規約・robots.txtに記載なし）。
4. 代替の公式配布元（東京都等）の配布形式・利用条件。
5. 基盤地図情報DEMの利用条件（利用者登録の規約・測量法上の手続）。
6. 各データのデータ基準日の公式の記載（A33以外）。
7. 各データの区分のコードリストと版（A40・A49・A33）。

**OWNER判断事項**

1. 第8章の小規模な取得試験の実施の可否と範囲。
2. 「API提供」が国土数値情報の利用規約の公衆送信・翻案に含まれるかの判断と、利用条件の照会の要否（国土情報提供サイト運営事務局）。A31aのライセンス表記の不一致の照会を含む。
3. A33の利用の制限（法的図書ではない等）を、HereRiskの応答・説明でどう扱うか。
4. 台帳の採用と、既存契約への提案（OL-C1〜OL-C3）の採否。
5. 標高で、標高タイル以外（基盤地図情報DEM。ログインが必要）を使う必要があるか。
6. 津波・高潮・土砂災害の個別契約の作成の順序。

## 10. 本工程で確認していないこと・意味しないこと

- 実データの取得・変換・公開は行っていない。新たな `download_verified` はない。
- `automation_verified` の試験は行っていない。
- 利用条件の承認は行っていない（すべて `review_required` または `unverified`）。
- 既存のFlood実データ処理のBlocking（Flood用の認可プロファイル・利用条件の未解決等）は維持している。
- 本調査は取得可否の調査であり、実データの取得の正式承認ではない。
