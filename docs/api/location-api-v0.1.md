# Location API v0.1（Phase 3-A サービス骨格）

- 作成: 2026-10-25（Claude。Phase 3-A）
- 改訂: 2026-10-25 Phase 3-B — `elevation` を既存の標高APIに接続するProviderを追加（第8.1節）。`mode: "local"` を追加
- 改訂: 2026-10-25 Phase 3-C — `address` を国土交通省「大字・町丁目レベル位置参照情報」に接続するProviderを追加（第8.2節）
- 改訂: 2026-10-25 Phase 3-D — N03 行政区域Polygonで市区町村を判定してから代表点を検索する方式を追加（第8.3節）
- 状態: **契約案（OWNERレビュー待ち）**。実装はローカルのサービス骨格のみ。公式データの製品利用・一般公開の承認ではない
- 上位: [Design Principles](../architecture/design-principles-v1.0.md)、[共通API契約 v0.1](common-contract-v0.1.md)
- 実装: `src/hererisk/location/`、テスト: `tests/contract/test_location_api.py`

緯度・経度の1地点について、住所・標高・洪水・津波・高潮・土砂災害を1つのJSONで返す。各情報はProviderが独立して取得し、APIはそれを並べるだけである。ハザードの分類を解釈・比較・集約しない。安全・危険を判定しない。

## 1. エンドポイント

`GET /api/v1/location?lat={緯度}&lon={経度}`

## 2. 入力

| パラメータ | 必須 | 規則 |
|---|---|---|
| `lat` | ○ | 緯度。十進数（例 `35.681236`）。−90〜90 |
| `lon` | ○ | 経度。十進数。−180〜180 |

- 軸は名前で指定する（`lat` が緯度、`lon` が経度）。値を入れ替えない・丸めない・範囲に収めない。
- 拒否するもの: パラメータの欠落・重複・未知のパラメータ、空文字、`nan`・`inf`、指数表記、`+` 付き、16進、範囲外、256文字を超える問合せ。
- 小数は15桁まで。
- 入力エラーは **HTTP 422**（`invalid_input`）。
- 他のパスは404、GET以外のメソッドは405（`Allow: GET`）。

## 3. レスポンスの構成（HTTP 200）

```json
{
  "schema_version": "location-v0.1",
  "mode": "mock",
  "location": {"lat": 35.681236, "lon": 139.767125},
  "address":   {"status": "...", "provider": "...", "synthetic": false, "notice": "..."},
  "elevation": {"status": "...", "provider": "...", "synthetic": false, "notice": "..."},
  "hazards": {
    "flood": {...}, "tsunami": {...}, "storm_surge": {...}, "landslide": {...}
  },
  "notice": "公式情報の提示です。HereRiskは安全・危険を判定しません。",
  "evaluated_at": "2026-10-25T10:16:38Z"
}
```

- `mode` は次のいずれか。
  - `mock`: 既定。全Providerが未接続
  - `sample`: 開発用の合成データ
  - `local`: 一部のProviderをローカルのAPIに接続した検証用の構成（Phase 3-B: 標高）
  - `live`: 将来、実データのProviderを接続したとき
- 一部のProviderが失敗しても、レスポンスはHTTP 200のままである。失敗はそのセクションの `error` で表す。

## 4. 状態（各セクションの `status`）

| 状態 | 意味 | ハザードの `results` |
|---|---|---|
| `available` | 使用資格のあるデータから情報を得た | 1件以上の配列 |
| `no_match` | 対象のデータを検索でき、該当する地物がない | `[]`。検索したデータを `searched_sources` に必ず入れる |
| `unknown` | 判定に必要な情報が不足し、結果を確定できない | `null` |
| `not_available` | データ・Providerが未接続、または利用できない | `null`（または省略） |
| `error` | 呼出し・処理に失敗した | `null`（または省略）。`error.code` を持つ |

- **`no_match` は安全を意味しない。** 各セクションの `notice` にその旨を必ず入れる。
- `unknown` と `not_available` を、空の配列だけで表さない。
- Orchestratorは、Providerの応答が上の形でなければ、`error`（`invalid_provider_result`）に置き換える。例えば次の場合である。
  - `available` なのに中身が空
  - `no_match` なのに検索したデータが書かれていない
  - 定義にない状態（`safe` 等）

**共通API契約 §3.1（暫定）との対応**: 本APIは、指示書の5状態を採用した。共通API契約の暫定の状態との対応は次のとおり。

| 本API | 共通API契約 |
|---|---|
| `available` | `success`（該当あり） |
| `no_match` | `success` で非該当 |
| `unknown` | `indeterminate` |
| `not_available` | `no_data`（データ未整備。未接続を含む） |
| `error` | `retrieval_failed` |

共通API契約の状態名は暫定（PROVISIONAL）であるため、統一するかどうかはOWNER判断とする（第9章）。

## 5. セクションごとの内容

**住所（`address`）**

`result` は、`available` のときだけオブジェクト、それ以外は `null`。

| 項目 | 内容 |
|---|---|
| `display_name` | 表示用の住所 |
| `precision` | 精度。`chome`（町丁目）・`block`（街区）・`estimated`（推定）等 |
| `method` | 推定の方式。例 `nearest_representative_point`（最寄りの代表点） |
| `is_confirmed_address` | 正式な住所の確定かどうか。最寄りの代表点による住所は `false` |

ほかに、出典 `source` を持つ。

**標高（`elevation`）**

- `result`: `{"elevation_m": <数値>, "unit": "m"}`。
- 0mや負の値は有効な値である。
- 未取得は `result: null`（または `elevation_m: null`）であり、**0mにしない**。
- `available` で数値がない応答は `error` に置き換える。
- ほかに、出典 `source` を持つ。

**ハザード（`hazards.flood` / `tsunami` / `storm_surge` / `landslide`）**

`results[]` の各要素は、公式の結果1件である。

| 項目 | 内容 |
|---|---|
| `source` | 出典（`source_id`・`organization`・`title`・`data_version`） |
| `feature_ref` | 地物の識別情報 |
| `original_class` | 原典の分類（`code`・`label`） |

- 複数の公式の結果は、すべて別々の要素として返す。共通の危険度への変換、代表値・最大値・最小値の選択はしない。
- 各ハザードの詳細（例: 洪水の区域・unknown・境界接触）は、各ハザードの個別契約に従う（洪水は [Flood API MVP契約](flood-api-mvp-contract-v0.1.md)）。本APIは、その結果を `results` 等に入れて並べるだけである。

## 6. 合成データ（`--sample-data`）

- 画面の確認のためだけに、各状態の例を1つずつ返す。地点に関係なく同じ内容である。
- 有効になるのは、起動時に明示的に `--sample-data` を指定した場合だけである。ループバックでのみ起動できる。
- 合成データには、次の印を付ける。
  - `mode: "sample"`
  - 各セクションの `synthetic: true`
  - `sample_note`
  - `notice` の先頭の「【合成データ】」
  - 名称の「（架空）」「（合成データ）」
- 既定のモードでProviderが `synthetic: true` を返した場合は、`error`（`synthetic_not_allowed`）に置き換える。

## 7. エラー・タイムアウト・プライバシー

- Providerの例外・タイムアウト（全体で2秒）は、そのセクションの `error`（`provider_failed` / `timeout`）になる。ほかのセクションは残る。
- 例外の文字列・ファイルパス・認証情報・スタックトレースは返さない。メッセージは公開用の固定文である。
- 位置を含むリクエストはログに残さない（アクセスログは無効）。
- サーバーはループバックのアドレスでのみ起動できる。

## 8. 実データへの接続点

Providerは、`id`（文字列）と `lookup(lat, lon) -> dict`（第4・5章の形の1セクション）を持つオブジェクトである（`hererisk.location.providers.Provider`）。

実データを接続するときは、次のようにする。

1. 対象のProviderを `lookup` を持つクラスとして実装し、第4・5章の形で返す。
2. `default_providers()` の該当する項目（`NotConnected`）を、そのProviderに差し替える。
3. 実データを使う構成では `mode` を `live` にする。

各Providerの将来の接続先:

| Provider | 将来の接続先 | 注意 |
|---|---|---|
| `address` | 国土交通省「位置参照情報」 | 最寄りの代表点は `is_confirmed_address: false`、`precision`・`method` を必ず入れる |
| `elevation` | 公開済みの標高API（Phase 1。`hererisk.elevation`）または同等の公開データの読取り | 公開済みのRegistryだけを読む（共通API契約 §5） |
| `flood` | Flood API MVP契約の検索 | 区域・unknown・境界接触の扱いは個別契約に従う |
| `tsunami` / `storm_surge` / `landslide` | 各ハザードの個別契約（未作成） | 個別契約・利用条件・認可が先に必要 |

Phase 2-Cで残ったBlocking（利用条件、認可、派生形状、精度プロファイル等）は、実データProviderの接続の前提として維持する。

### 8.1 ElevationProvider（Phase 3-B）

`hererisk.location.elevation_provider.ElevationProvider` は、既存の標高APIの `POST /api/v1/elevation`（[標高API契約](elevation-contract-v0.1.md)）を呼び出す。

**接続の条件**

- 有効になるのは、起動時に `--elevation-api http://127.0.0.1:<port>` を指定した場合だけである。既定は未接続のまま。
- 接続先は `127.0.0.1` だけに限る。`localhost`・他のアドレス・https・パス付きのURLは拒否する。
- Bearer Tokenは、リポジトリの外にある0600のファイル（`--elevation-token-file`）から、起動時に1回だけ読む。
  - Tokenはログ・エラー・応答に出さない。
  - 権限が緩いファイルは拒否する。
- タイムアウトは1.5秒。応答は64KiBまで読む。

**状態の変換**

| 標高APIの `status` | Location APIの `status` | 補足 |
|---|---|---|
| `success` | `available` | `result.elevation_m` をそのまま返す。0m・負の値も有効な値 |
| `no_data` | `not_available` | `reason` に標高APIのエラーコードを入れる（`no_coverage`: 対象のデータの範囲外、`elevation_nodata`: NoData画素）。`no_match` にはしない |
| `indeterminate` | `unknown` | `reason` に標高APIのエラーコードを入れる（例 `dataset_integrity_error`） |
| `retrieval_failed` | `error` | `upstream_retrieval_failed` |
| `invalid_request`（認証の不一致等） | `error` | `upstream_rejected` |
| 接続できない / タイムアウト | `error` | `upstream_unreachable` / `timeout` |

次の応答は `error`（`invalid_provider_result`）にする。標高の値は作らない。

- 未知のstatus
- 壊れたJSON
- 数値でない、または欠けている標高の値
- 要求した地点と異なる `location`
- 出典の情報が不足している
- `no_data` なのに値が入っている

**出典（`source`）への写像**

標高APIが公開する `dataset` の項目だけを写す。標高APIにない項目（`title` 等）は作らない。

| `source` の項目 | 標高APIの `dataset` |
|---|---|
| `source_id` | `id` |
| `organization` | `source.provider` |
| `data_version` | `publication_version` |
| `published_at` | `published_at` |
| `attribution.text` / `license` / `url` | `attribution.text` / `license` / `url` |
| `page_url` | `source.page_url`（値がある場合のみ） |
| `data_reference_date` | `data_reference_date`（値がある場合のみ） |

**Fixtureのデータ**

- Fixtureの値は実際の標高ではない。
- 起動時に `--elevation-fixture` を指定した場合だけ、`synthetic: true`（`notice` の先頭に「【合成データ】」）として返す。
- 指定しないままFixtureのデータ（`source_id` が `fixture` で始まる）が返った場合は、`error`（`synthetic_not_allowed`）にする。

### 8.2 MlitAddressProvider（Phase 3-C）

`hererisk.location.address_provider.MlitAddressProvider` は、国土交通省「大字・町丁目レベル位置参照情報」の都道府県単位のファイルを使う。

**データと読込み**

- 入力は、公式のZIP、またはその中のCSVである（Shift-JIS、10列）。起動時に `--address-isj <パス>` で指定し、起動時に1回だけ読む。実行ごとにダウンロードしない。
- データはGitの管理外に置く。
- 次の場合は起動しない（終了コード3）。エラーを架空の住所に変えない。
  - ファイルがない
  - 文字コードがShift-JISでない
  - 見出しが違う
  - 列数・緯度経度・名称・区分コードが不正な行が1行でもある
- 読込みは約0.3秒、検索は1回あたり約0.06ミリ秒（東京都5,390点、Mac）。単純な走査で足りるため、検索索引は導入していない（緯度の順に並べ、外側へ走査して打ち切るだけ）。

**検索と結果**

- 入力地点から最も近い代表点を、Haversineの距離（地球半径6,371,008.8m）で探す。
- 結果の項目は次のとおり。

| 項目 | 内容 |
|---|---|
| `display_name` | 「都道府県名＋市区町村名＋大字町丁目名＋付近」 |
| `prefecture`・`municipality`・`area`・`area_code` | 住所の各要素とコード |
| `precision` | CSVの「大字・字・丁目区分コード」による。`3` → `chome`、`1` → `oaza`、`2` → `aza`、`0` → `oaza_or_common_name` |
| `method` | `nearest_representative_point` |
| `is_confirmed_address` | 常に `false` |
| `distance_m` | 代表点までの距離 |
| `max_distance_m` | その代表点に適用した許容距離 |

- `notice` は「最寄りの代表点による推定です。正式な住所の確定ではありません。」である。
- **代表点の検索は、その町丁目・都道府県の区域への所属の判定ではない。**

**許容距離（MVPの値）**

- 代表点ごとに `max(500m, その代表点から最も近い別の代表点までの距離)` を許容距離とする。上限は10kmとする。
- 許容距離を超えたら、`status: "not_available"`、`reason: "out_of_coverage"` を返し、住所を返さない。
- 東京都のデータでの根拠
  - 代表点の間隔は、中央値332m、95パーセンタイル598m、99パーセンタイル1,766mである。山間部・島しょ部の大字は数kmの間隔になる。
  - 固定の距離では、都市部で隣県の地点を受け入れるか、山間部の地点を落とすかのどちらかになる。
  - 2025年版のデータで、東京都の周辺の無作為な4,000地点を評価した（行政区域のポリゴンは評価だけに使用。製品では使っていない）。

| 規則 | 都内の地点で住所を返さない割合 | 都外の地点に都内の住所を返す割合 |
|---|---:|---:|
| 固定1,000m | 19.1% | 3.9% |
| 固定2,000m | 7.4% | 9.5% |
| **代表点の間隔×1.0（最小500m、最大10km）** | **7.9%** | **3.1%** |
| 代表点の間隔×1.5（最小500m、最大10km） | 2.7% | 7.9% |

- 誤った他県の住所よりも「住所なし」の方が安全なため、都外への誤りが最も少ない規則を採った。
- 実測の例は次のとおり。
  - 川崎駅・和光市駅・松戸駅・東京湾の中央・大阪・ソウル: 住所を返さない
  - 東京駅: 丸の内一丁目（37m）
  - 奥多摩駅: 白丸（1,634m）
  - 八丈島空港: 三根（1,656m）
- **距離の制限は、行政区域の厳密な判定の代わりではない。** 都県境のすぐ外側（例: 多摩川の対岸の数百m）では、都内の住所を返すことがある。
- 境界の付近では、東京都のデータだけを接続していても、他県の地点に東京都の住所を返さないことを保証できない。

**出典（`source`）と利用条件**

- `organization`: 国土交通省
- `title`: 大字・町丁目レベル位置参照情報
- `data_version`: 年（例 `2025`）
- `edition`: 版数（例 `19.0b`）
- `page_url`: ダウンロードサービスのURL
- `attribution.text`: 「位置参照情報 国土交通省（2025年、13_2025.csv）」

出典の表記は、利用約款の要求に合わせて「位置参照情報 国土交通省」とし、整備年とファイル名を併記した。

利用約款（ダウンロード時に表示・同意。2026-10-25に確認）の要点:

- 無償で利用できる。
- 転載・引用の際は「位置参照情報 国土交通省」のように出典を明記し、整備年・ファイル名・加工者をできる限り併記する。
- 公共測量等の高度な精度が要求される測量・各種証明には使えない。
- 地名は国内の標準的な地名を指定するものではない。
- 利用による損害について国は責任を負わない。

一般公開の可否は、別途OWNERが判断する。

### 8.3 N03行政区域Polygonによる市区町村判定（Phase 3-D）

起動時に `--address-isj` と一緒に `--address-n03 <N03のZIP>` を指定すると、住所の推定は次の順になる。

1. 国土数値情報 N03（行政区域データ）のPolygonで、地点が属する市区町村を判定する（shapely／GEOSを利用。`pip install -e '.[address]'`）。
2. 位置参照情報の代表点を、その市区町村のコードに限定して、最寄りを探す。

**データ**

- N03 2026年版（令和8年1月1日時点）東京都、`N03-20260101_13_GML.zip`（Phase 2-C.3で取得済み、SHA-256 `94f10b26…`）のGeoJSON。座標系はJGD2011（EPSG:6668）の経度・緯度である。
- 6,904地物、63の行政区域コード。すべてMultiPolygonで、穴のある部分は3つ。
- 市区町村の結合は、行政区域コードで行う。名称の一致には頼らない。
  - N03の `N03_007` と、位置参照情報の「市区町村コード」は、同じ5桁の全国地方公共団体コードである。
  - 位置参照情報の62コードは、すべてN03にあった。名称も「`N03_003`＋`N03_004`」と一致した（例 `13308` 西多摩郡奥多摩町）。
- N03にだけある `13000`（所属未定地）は、都道府県までの結果にする。
- 同じ市区町村の地物（島・飛び地）は、起動時に1つにまとめる。地物どうしの継ぎ目は境界として扱わない。
- 読込みは約1秒、検索は1回あたり約0.02ミリ秒（Mac）。

**判定と応答**

境界の許容幅は10m（MVPの値）である。この値は、データ上の境界の位置の精度を考えたものである。

| 判定 | 条件 | 応答 |
|---|---|---|
| 市区町村が確定 | 1つの市区町村の内側で、その境界から10mより離れている | 下の2行のどちらか |
| ― 町丁目も推定 | その市区町村の代表点が許容距離（第8.2節）以内にある | `available`、`precision` は区分コードによる（`chome` 等）、`method: "municipality_polygon_and_nearest_point"` |
| ― 市区町村まで | その市区町村の代表点が許容距離以内にない | `available`、`precision: "municipality"`、`area: null`、`area_reason: "no_representative_point_within_limit"`、`method: "municipality_polygon"`、`display_name` は「東京都狛江市」の形 |
| 所属未定地 | `13000` の内側 | `available`、`precision: "prefecture"`、`municipality: null` |
| 境界の付近 | どれかの市区町村の境界から10m以内（内側・外側とも） | `unknown`、`reason: "municipality_boundary_ambiguous"`、`candidates` に候補の市区町村（コード・名称）を列挙し、1つに決めない |
| 区域外 | 読み込んだPolygonから10mより遠い | `not_available`、`reason: "out_of_coverage"` |

- **都県境**: 隣の県のPolygonは読み込んでいない。そのため、都県境の内側10m以内も「境界の付近」とする。
- **フォールバックしない**: 区域外・境界の付近で、距離だけの検索（第8.2節）に切り替えて住所を返すことはしない。
- 穴の内側は、その市区町村の区域外として扱う。
- 出典の `boundary_source` に、N03の出典を「「国土数値情報（行政区域データ）」（国土交通省）（ファイル名）を加工して作成」の形で入れる（国土数値情報の利用規約は、出典と加工の旨の記載を求める）。
- **N03による判定は行政区域のデータ上の判定であり、法的な境界の確定ではない。**

**改善の確認（2025年版の位置参照情報・N03 2026、東京都の周辺の無作為な4,000地点）**

| 項目 | 距離だけ（第8.2節） | Polygonで判定（本節） |
|---|---:|---:|
| 都外の地点に都内の住所を返した | 84 | **0** |
| 都内の地点で、別の市区町村の住所を返した | 35 | **0** |
| 都内の地点で、何も返さなかった | 97 | 0（市区町村までの結果を返す） |
| 境界の付近（`unknown`） | ― | 12 |

**N03の利用条件**

- 国土数値情報の利用規約では、複製・加工・商用利用ができ、出典と加工の旨の記載が必要である。
- ただし、ZIPの中のメタデータに「測量法に基づく国土地理院長承認（複製）」「本製品を複製する場合には、国土地理院の長の承認を得なければならない」との記載がある。
- この扱いは未確認である（取得元台帳 `ksj-n03-2026-13` は `review_required`）。
- そのため、本機能はローカルでの検証に限る。一般公開の前にOWNERの判断が必要である（既存のBlockingを継続する）。

## 9. 未決定事項（OWNER判断）

1. 状態名を、共通API契約の暫定の名前（第4章の対応表）に統一するか、本APIの5状態を共通契約へ反映するか。
2. 入力エラーのHTTPステータス（本APIは422。標高APIは400）の統一。
3. 認証（標高APIのBearer Token方式）を本APIにも適用する時期。
