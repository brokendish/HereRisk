# Polygon Engine 有効性検証・正式な内外判定 実装仕様 v0.1（Phase 4-L）

- 状態: **実装済み**。`hererisk.common.polygon`（`validity.py`・`relation.py`）。Phase 4-M から **Tsunami Provider（`hererisk.tsunami`・`location.tsunami_provider`、ローカル検証のみ）が利用**（[津波API MVP契約](tsunami-api-mvp-contract-v0.1.md)）。Flood Provider・参考解析API・採用条件・理由コード・文言・洪水の索引からは呼び出していない（テストで確認）。洪水の製品コードへの切替はまだ行わない（移行計画 Step 4）。共通部品は Phase 4-M で変更していない。
- 作成: 2026-11-03（Claude）。基準コミット `be93241a05604696627669d85a0a3884e54717f3`
- 上位: [Polygon Engine 共通契約 v0.2](polygon-engine-contract-v0.2.md)（3.1節・第4章）、[ADR-002](../decisions/2026-11-03-polygon-engine-responsibility.md)、[移行計画](../architecture/polygon-engine-migration-plan-v0.1.md) Step 2-1・2-2
- 関連: [幾何の事実の取得 v0.1](polygon-engine-facts-v0.1.md)（Phase 4-K。本書の機能とは別のモジュール）

## 1. 責務

| モジュール | 責務 | 参照した洪水の処理（変更しない） |
|---|---|---|
| `validity.py` | Polygon / MultiPolygon の構成の検査、座標の検査、構成ごとの有効性の分類 | `flood.index.classify`、`flood.a31a.check_coordinates` |
| `relation.py` | 有効なPolygonの正式な内外・境界上、無効なPolygonの判定保留、複数構成の検索 | `location.flood_provider._Source.search`（`FloodProvider.lookup` の幾何の部分） |

- **有効なPolygonだけを正式な内外判定に使う。** 無効なPolygon（`invalid_geometry`・`feature_invalid_component`・`unverified`・有効性の情報なし）は判定せず、保留する。
- **外接矩形は保留の対象を選ぶためだけに使う。** 外接矩形の中・境界上の地点を、区域内・区域外のどちらとしても確定しない。
- **`outside` は幾何学的な関係であり、「安全」を意味しない。** 該当がないことの意味（「該当なし」「登録された区域に該当しない」など）はProviderが、データの範囲・登録状況を考えて決める。
- **探索半径を使わない。** 内外はGEOSが形状全体で求める。Polygonの大小によって判定の方法・半径を変えない。
- **ハザードの属性を解釈しない。** 浸水深・区域の種類などを読まない（コードに属性のキー名を書かない。テストで確認）。
- **構成・ソースを統合しない。** 構成ごとに1件で返す。合併・最大値・代表値・順位付けをしない。重なりを解消しない（土砂災害の警戒区域と特別警戒区域のように、重なること自体に意味がある場合がある）。
- **修復しない。** `make_valid`・`buffer(0)`・頂点の削除・リングの修正・再構成を行わない（テストで禁止）。
- 依存: shapely（GEOS）と標準ライブラリだけ。`hererisk.flood`・`location`・`research` をimportしない（テストで確認）。

## 2. 公開インターフェース

```python
from hererisk.common.polygon import validity, relation

validity.polygons_of(geometry) -> list            # GeoJSON風の Polygon / MultiPolygon -> 構成Polygon（リングのリスト）の列
validity.check_coordinates(polygons) -> None      # 失敗は GeometryInputError（分類しない）
validity.classify_components(polygons) -> list[validity.Component]   # 1つのFeatureの構成。座標の検査を含む

relation.relate(geometry, validity, x, y) -> {"evaluation", "relation"}      # 1構成の純粋関数
relation.Candidate(source_id, feature_ref, geometry, validity=None, detail=None)  # geometry: Polygon または WKB
relation.ComponentIndex(candidates)               # 反復可能（行を流し込める）。候補の絞り込み（STRtree）を持つ
relation.ComponentIndex.search(x, y, *, max_features=500) -> dict
```

`validity.Component`: `polygon_index`・`geometry`（原典の座標のまま作ったPolygon）・`validity`・`detail`・`kind`・`related`、`usable`（`validity == "valid"`）、`state()`（`geometry_state` の辞書: `validity`・`validator`・`detail`・`kind`・`related_components`）。

座標は経度 `x`・緯度 `y`（GeoJSONの順）。変換・丸めをしない。

## 3. 有効性の分類（`validity.py`）

### 3.1 入力の拒否（分類しない）

次の場合は `GeometryInputError`（固定の文言、座標を含まない）。**無効（`invalid_geometry`）としても扱わない。** 呼び出し側（索引の構築）は停止する。洪水の `a31a.check_coordinates` が拒否する入力と同じ。

| 検査 | 内容 |
|---|---|
| 構成 | `type` が `Polygon` / `MultiPolygon`、`coordinates` がリスト、MultiPolygon が空でない、Polygon にリングがある |
| 位置 | 2次元の数（`int` / `float`。`bool`・文字列・3次元を拒否） |
| 非有限値 | NaN・無限大を拒否 |
| 範囲 | −180 < 経度 < 180、−90 ≦ 緯度 ≦ 90 |
| リング | 閉じている（最初と最後が同じ）、4点以上 |
| 辺 | 経度の差が180度を超える辺（日付変更線をまたぐ）を拒否 |
| 構築 | GEOSでPolygonを作れない |

### 3.2 分類

| `validity` | 条件 | `detail` / `kind` |
|---|---|---|
| `valid` | GEOS `is_valid` が真で、Feature内の重なりに関わらない | なし |
| `invalid_geometry` | GEOS `is_valid` が偽（自己交差・自己接触・点が少ない・穴が外周の外・内部が非連結など） | `detail`: GEOSの理由（`shapely.is_valid_reason`。洪水の索引の `invalid_detail` と同じ文字列）。`kind`: 位置を除いた理由（例 `ring_self_intersection`・`self_intersection`・`interior_is_disconnected`・`hole_lies_outside_shell`・`too_few_points_in_geometry_component`） |
| `feature_invalid_component` | 単独では有効だが、同じFeatureの別の有効な構成と内部が重なる（DE-9IM `T********`）、または辺を共有する（`****1****`） | `kind`: `interiors_overlap` / `shared_edge`（両方なら `+` で連結）、`related`: 関わる構成の番号 |
| `unverified` | 検査が完了しなかった（GEOSが例外を返した、またはFeature内の不整合に関わる構成を特定できない） | `kind`: `validator_error` / `feature_level_unresolved` |

- `unverified` は `valid` として扱わない（`relation` では保留）。
- 規則は `flood.index.classify` と同じ（全構成の MultiPolygon が無効な場合だけ、有効な構成の組を STRtree で調べる）。違いは、洪水の構築が停止する「関わる構成を特定できない」場合に、例外の代わりに `unverified` を返すことだけ。
- 比べるのは**同じFeatureの構成どうしだけ**。別のFeatureどうしの重なりは調べない（意味のある重なりがありうる）。
- GEOSは自己接触も `Ring Self-intersection` と報告する。接触と交差の区別（`touch` / `crossing`）は、本モジュールでは行わない（診断索引の `defects` の範囲）。
- 連続する重複頂点は有効（GEOSと同じ）。往復する辺（スパイク）・面積0のリングは無効。

## 4. 正式な内外判定（`relation.py`）

### 4.1 1構成（`relate`）

| 有効性 | 条件 | `evaluation` | `relation` |
|---|---|---|---|
| `valid` | GEOS `contains` | `evaluated` | `inside` |
| `valid` | `contains` でなく `intersects`（辺・頂点の上） | `evaluated` | `on_boundary` |
| `valid` | それ以外（穴の中を含む） | `evaluated` | `outside` |
| それ以外・なし | 外接矩形の中または境界上 | `pending_geometry` | `null` |
| それ以外・なし | 外接矩形の外 | `outside_bounding_box` | `null` |

- `outside` を返すのは有効な構成だけ。無効な構成には、外接矩形の外でも `outside` を付けない（その構成が検索の対象外であることだけを表す）。
- `on_boundary` はデータの形状の上の事実（浮動小数の座標でGEOSが判定）で、測位誤差は含まない。

### 4.2 複数構成の検索（`ComponentIndex.search`）

```json
{"status": "complete", "complete": true, "features": [
  {"source_id": "example-source", "feature_ref": "polygon-001", "evaluation": "evaluated", "relation": "inside",
   "geometry_state": {"validity": "valid"}},
  {"source_id": "example-source", "feature_ref": "polygon-002", "evaluation": "pending_geometry", "relation": null,
   "geometry_state": {"validity": "invalid_geometry", "detail": "Ring Self-intersection[…]"}}
]}
```

- 列挙するのは `inside`・`on_boundary`・`pending_geometry` だけ。**`outside` の構成は列挙しない**（契約 v0.2 3.1節）。
- 候補の絞り込み（有効な構成の STRtree、保留の構成の外接矩形の STRtree）と、関係の判定（GEOS）を分ける。保留の構成は外接矩形だけを保持し、形状は保持しない（洪水と同じ）。
- 順序: ソースの登録順（候補を渡した順で最初に現れた順）、その中で `feature_ref` の順。
- 同じ地点で、内側の構成と保留の構成、複数の有効な構成、同じ形の別ソースの構成が同時に返る。それぞれ独立の1件。
- `features: []` は「列挙する構成がない」という幾何の事実で、安全・該当なしの判断ではない。

### 4.3 不完全な状態（一部を返さない）

| 状態 | 返り値 |
|---|---|
| 列挙する構成が `max_features`（既定500。洪水の `MAX_ITEMS` と同じ）を超えた | `{"status": "limit_exceeded", "complete": false, "features": null, "limit": {...}}` |
| 処理中の例外（GEOSの例外など） | `{"status": "failed", "complete": false, "features": null}`（例外の内容・座標は出さない） |
| 地点が有限の数の組でない | `RelationInputError`（呼び出しの誤り） |
| 形状が読めない（壊れたWKB）・Polygonでない・空 | `RelationInputError`（索引を開けない。Providerは起動しない） |
| 有効性が未知の値 | `RelationInputError` |
| 有効性の情報がない（`None`） | `unverified` として保留（正式判定しない） |

不完全な状態を `outside`・`features: []` に変換しない。

## 5. 既存洪水との比較（Phase 4-L）

### 5.1 合成Geometry（`tests/contract/test_polygon_validity_relation.py`）

| 検証 | 結果 |
|---|---|
| 有効性 20種（正方形・穴・穴の1点接触・2点接触・自己接触・蝶ネクタイ・重複頂点・スパイク・面積0・潰れたリング・外周の外の穴・B1・U字・MultiPolygonの離れ／頂点接触／重なり／辺共有／内包／穴の中の島／無効と有効の重なり） | `flood.index.classify` と構成ごとに（使えるか・理由・GEOSの詳細）完全一致。形状は原典の座標のまま（WKBが同一） |
| 座標の拒否 11種（NaN・無限大・閉じていない・短い・経度180・緯度91・日付変更線・3次元・文字列・bool・リングなし） | `a31a.check_coordinates` が拒否するものをすべて拒否（分類しない） |
| 内外 13地点（内部・外部・辺上・頂点上・穴の中・5km四方の中央・幅30mの細長い形・U字の切れ込み／腕／底など） | GEOS `contains` / `intersects` と一致。一辺1m〜50kmで内外が変わらない |
| 無効Polygonの外接矩形の内部・辺・角／外 | `pending_geometry` / `outside_bounding_box`。`outside` にならない |
| **洪水の合成索引（2種）での `FloodProvider` との差分** | 格子（0.0002度）・全頂点・全辺の中点・保留の構成の外接矩形の角と辺上の全地点で、ソースごとの `zones`・`boundary_contacts`・`unknowns` の zone_ref の集合が完全一致。2種目は、約5km四方・幅30mの細長い形・U字・穴・B1・自己接触・辺共有のMultiPolygon・無効と有効の重なり、同じ形の別ソース |
| 上限・失敗 | 上限超過は `limit_exceeded`、例外は `failed`。どちらも `features: null` |

### 5.2 実データ（東京都・洪水の正式索引、読取専用。[集計](../research/polygon-engine-v0.1/tokyo-flood-validity-relation-summary.json)、`python -m hererisk.research.validity_relation_compare`）

| 検証 | 結果 |
|---|---|
| 有効性（387,754 Feature・388,148構成） | 索引に記録された分類、`flood.index.classify` の再計算の両方と全構成一致（`valid` 383,078、`invalid_geometry` 5,070。`feature_invalid_component` は実データに0件）。形状は全構成で不変 |
| 内外（4,601地点のうち対象地域内の4,153地点: Phase 4-C の601地点、有効な構成の頂点1,995、保留の構成の外接矩形の角・辺上1,649） | ソースごとの zone_ref の集合が `FloodProvider.lookup` と全地点一致（延べ `inside` 1,324、`on_boundary` 4,161、`pending_geometry` 17,658）。`relate` の結果も検索の結果と全件一致 |

- 実データに `feature_invalid_component`・自己交差（`crossing`）・同一直線上の重なりは現れない。これらは合成Geometryでのみ確認した。
- 共通部品を通した Location API の応答は作っていない（組み込みは別工程）。正式判定の比較は、Providerの検索結果（zone_ref の集合）の単位で行った。

### 5.3 Codex反例 B1

正方形を往復してから三角形を回るリング（Phase 4-J.1）は GEOS で `invalid_geometry`（`Ring Self-intersection`）。`relate`・`search` とも `pending_geometry`（`relation: null`）を返し、正式な内外判定に流さない。GEOS `contains` は偽、`make_valid(linework)` は内側と読む（解釈が分かれる）ことをテストで確認している。

## 6. 性能・メモリ（Mac上の Docker、aarch64 Linux、東京都・洪水）

| 項目 | 共通部品 | 洪水（参考） |
|---|---|---|
| 有効性の分類（1 Feature） | 中央値 0.008ms、p95 0.032ms、最大 542ms | `classify` 中央値 0.005ms、p95 0.015ms、最大 505ms |
| 有効性の分類（頂点数別の中央値） | 100未満 0.008ms、1,000未満 0.10ms、1万未満 1.2ms、10万未満 16ms、10万以上（8件）94ms | — |
| 検索（1地点、全ソース） | 中央値 0.017ms、p95 0.046ms | `_Source.search` 中央値 0.029ms、p95 0.061ms（属性の行の読取を含む） |
| `relate`（1構成） | 中央値 0.0036ms、p95 0.0063ms。頂点数1万〜10万未満でも中央値 0.024ms | — |
| 索引の作成（388,148構成） | 0.27秒（形状が読込み済みの場合）。WKBの行から流し込むと1.4秒 | Provider起動 3.5秒（N03の対象地域の結合を含む） |
| ピークRSS（別プロセスで計測） | 482MB（共通索引を索引の行から作成） | 465MB（`FloodProvider`。N03の対象地域を含む） |

- 共通の有効性の分類は、洪水より構成ごとの理由（`kind`・`related`）を作る分だけ遅い。索引の構築時に1回だけ行う処理で、検索の時間には影響しない。
- 正式判定の時間は探索半径に依存しない。Polygonの頂点数が増えると GEOS の `contains` の時間がゆるやかに増える。
- 全件をメモリに置く方式は洪水と同じ。大規模データ向けの SQLite / R-tree による正式検索は、必要性を計測してから判断する（Phase 4-K の診断用 SQLite Reader とは別のもの）。
- 未測定: 全国規模、VPS（x86_64）、同時アクセス、頂点10万以上の構成の `relate`（実データの地点が当たらなかった）。

## 7. 次工程に残すこと

1. Providerへの組み込み（次のハザード、または洪水の切替: 移行計画 Step 3・4）。洪水を切り替える場合は回帰基準 RG-1〜RG-14 を満たすこと。
2. Codexによる差分テストの十分性の確認（移行計画 V-2）。
3. 大規模データでの正式検索（SQLite / R-tree）の要否の判断と計測。
4. 2つの検証器（Normalize契約の要求）・座標の精度プロファイル（整数・8桁）の採用は未決定のまま。本書は GEOS 1つ・浮動小数の座標（洪水の現状）に合わせた。
