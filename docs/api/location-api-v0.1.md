# Location API v0.1（Phase 3-A サービス骨格）

- 作成: 2026-10-25（Claude。Phase 3-A）
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

## 9. 未決定事項（OWNER判断）

1. 状態名を、共通API契約の暫定の名前（第4章の対応表）に統一するか、本APIの5状態を共通契約へ反映するか。
2. 入力エラーのHTTPステータス（本APIは422。標高APIは400）の統一。
3. 認証（標高APIのBearer Token方式）を本APIにも適用する時期。
