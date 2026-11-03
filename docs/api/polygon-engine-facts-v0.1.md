# Polygon Engine 幾何の事実の取得 実装仕様 v0.1（Phase 4-K）

- 状態: **実装済み・製品から未使用**。`hererisk.common.polygon`（`facts.py`・`sqlite_reader.py`）。Flood Provider・Location API・参考解析API・採用条件・理由コード・文言・索引からは呼び出していない（テストで確認）。組み込みは別工程。
- 作成: 2026-11-03（Claude）。基準コミット `45157d159ce82b9e111568fb59e529cb75a5e20b`
- 上位: [Polygon Engine 共通契約 v0.2](polygon-engine-contract-v0.2.md)（3.3節の `far_reading`）、[ADR-002](../decisions/2026-11-03-polygon-engine-responsibility.md)
- 根拠: [Phase 4-J 研究](../architecture/polygon-point-determination-study-v0.1.md)、[Phase 4-J.1 Codex監査](../reviews/polygon-point-determination-codex-review-v0.1.md)

## 1. 責務

地点 p と、1つの構成Polygonのリング（外周1つ＋穴）について、**幾何の事実だけ**を返す。

| 返す | 返さない |
|---|---|
| リングごとの回転数、面積の符号、役割、正規化した回転数、偶奇、H・H2 の成否、境界上か、近傍の境界までの距離、処理の状態 | 正式な内外、参考解析の採用（`candidate`）、浸水深などの属性の意味、利用者への文言、作成者の意図 |

- **無効なPolygonの解析は、正式な防災判定ではない。** `parity_inside`・`winding_normalised` は、それぞれ偶奇・正規化した回転数という**選んだ規則による読み**である。
- **原典作成者の意図との一致は保証しない。**
- 依存: 標準ライブラリと numpy だけ。`hererisk.flood`・`location`・`research`・shapely をimportしない（テストで確認）。

## 2. 公開インターフェース

```python
from hererisk.common.polygon.facts import facts_from_rings, RayCounter, ray_direction
from hererisk.common.polygon.sqlite_reader import Reader, ReaderError

facts_from_rings(rings, lat, lon, *, holes=None, boundary_search_m=1.0) -> dict   # メモリ上の閉じたリング
Reader(path)                                      # 既存の診断索引を読取専用で開く（ReaderError で拒否）
Reader.point_facts(zone_ref, lat, lon, *, boundary_search_m=1.0, max_chunks=200000, budget_s=1.0) -> dict
Reader.close()
```

- `RayCounter` はリングの断片（連続する頂点）を1つずつ受け取り、リングごとの交差の数と最寄りの境界の距離だけを保持する。断片の数・Polygonの大きさに比例してメモリが増えない。
- `Reader` は1本の接続と1つの期限を持つ。**スレッドごとに1つ**使う。

## 3. 出力

```json
{
  "zone_ref": "loc-zn-…", "index_format": "hererisk-flood-diag-v0.1", "index_built_at": "…",
  "status": "complete", "complete": true,
  "method": "ray-crossing-per-ring-v1", "ray": "west",
  "ring_role": ["shell", "hole", "hole"], "area_sign_per_ring": [1, -1, -1],
  "raw_winding_per_ring": [1, 0, 0], "winding_normalised": 1, "parity_inside": true,
  "h_winding_parity": true, "h2_per_ring_unit": true, "zero_area_ring_around_point": false,
  "h2_scope": "even-odd and normalised nonzero agree at the point; not every interpretation, not an official relation, not the author's intent",
  "on_boundary": false, "boundary_distance_m": null, "boundary_search_m": 1.0,
  "component_defect_kinds": {"touch": 13},
  "ray_read": {"pieces": 1, "segments": 64}, "chunks_read": 1, "seconds": 0.00031
}
```

| フィールド | 意味 |
|---|---|
| `raw_winding_per_ring` | 地点から構成の外接矩形の外へ最短の方向（東・西・北・南）に引いた半直線と、各リングの辺の符号付きの交差数（保存された向き）。半直線と交わらないリングは0。半開区間の規則と計算は Phase 4-D の診断索引と同じ |
| `area_sign_per_ring`・`ring_role` | 索引の `comps.rings`（穴の印・符号付き面積の符号）から |
| `winding_normalised` | Σ（外周 +1・穴 −1）×面積の符号×raw |
| `parity_inside` | 全リングの交差の数が奇数 |
| `h_winding_parity` | 正規化した回転数が0か1で、偶奇と一致 |
| `h2_per_ring_unit` | H かつ、各リングの 面積の符号×raw が0か1（面積0の環は raw が0） |
| `on_boundary` | 丸めていない最寄りの距離が `ON_BOUNDARY_M`（1mm、Phase 4-C から変更なし）**未満**。境界上では半直線の読みが定義されないため、回転数・偶奇・H・H2 は `null` |
| `boundary_distance_m` | 地点から `boundary_search_m` 以内にある断片の中での最寄りの距離（m、丸めない）。その範囲に断片がなければ `null`。**構成全体への最短距離ではない**。0や推定値で埋めない。表示のための丸めは呼び出し側が行う |
| `component_defect_kinds` | 構成の問題箇所の種類ごとの件数（索引の `defects`）。構成全体の事実で、地点との関係は示さない |
| `ray_read`・`chunks_read` | 読んだ半直線上の断片・線分の数、読んだ塊（chunk）の行数（境界の近傍の分を含む） |

距離は地点の緯度での局所の平面（1度 = 111,320m、経度は cos(lat) 倍）。座標は原典の経度・緯度のまま変換しない。境界の閾値は座標の精度・GPSの測位精度とは別の値である。

## 4. H2 の扱い（Phase 4-J.1 B1 を反映）

- **H2 は幾何の検査結果の1つであり、内外の確定条件ではない。**
- H2 が保証するのは、**その地点で偶奇の読みと正規化した回転数の読みが一致すること**だけである。修復・解釈方式のすべてが一致すること、正式な内外、作成者の意図は保証しない（`h2_scope`）。
- 反例 B1（Codex）: 正方形を往復してから別の三角形を回るリングでは、正方形の辺の交差が相殺されて raw = 0、H2 が成り立つが、`make_valid(linework)` は地点を内側と読む。共通Engineはこのとき `raw_winding_per_ring: [0]`・`h2_per_ring_unit: true` を事実として返し、**内外・一致・区域外を返さない**（回帰テスト）。
- B1 の構成は、問題箇所の種類として `overlap` を持つ（`component_defect_kinds`）。これを保留の根拠に使うかは採用方針の判断で、本Engineは判断しない。`overlap` を除けば H2 が常に十分だとは確認していない。
- H2 の真偽だけで、すべての不整合を分類できるとは仮定しない。

## 5. SQLite索引の利用

- 対応形式: `hererisk-flood-diag-v0.1`（Phase 4-D）。形式は変更しない。読取専用（`mode=ro`）で開く。`meta.status` が `complete` でない・形式が違う・読めない場合は `ReaderError`。
- 索引の世代（`meta.derived_from`）が、Providerの使うデータと一致するかの確認は、Providerの責務とする（本Readerは `index_built_at` を返すだけ）。
- 読み方:
  1. `comps` から構成の外接矩形と `rings`（リングごとの穴の印・面積の符号・線分数）を読む。
  2. 地点の周り ±`boundary_search_m` の箱で `chunk_rtree` を引き、該当する塊を1行ずつ読んで最寄りの距離を更新する。
  3. 半直線の箱で `chunk_rtree` を引き、該当する塊を1行ずつ読んで、リングごとに交差を数える。塊は「連続する頂点」で、隣の塊と端点を共有するため、線分を二重に数えない。リングの番号（`chunks.ring`）を保つ。
  4. 全線分を1つの配列に結合しない（作業メモリは、リングの数＋塊1つ分）。
- 上限: 塊の行数 `max_chunks`（既定 200,000）、時間 `budget_s`（既定 1秒。この接続の SQLite 進行ハンドラでも中断する）。上限・時間切れ・読取りの失敗・存在しない `zone_ref` では、`complete: false` と状態（`limit_exceeded` / `timeout` / `failed` / `not_found`）だけを返し、**途中までの数・事実を返さない。区域外に変換しない。**
- R-tree の候補は塊単位（交差する辺そのものではない）。SQL の検索の費用には、構成内の塊の走査や R-tree の候補の確認が加わる（Codex監査 第7章）。

## 6. 検証結果（Phase 4-K）

| 検証 | 結果 |
|---|---|
| 合成形状 11種（正方形・穴・5km四方・細長い形・U字・自己接触・自己交差・2回巻き・B1・複数の穴・面積0の環）の回転数 | 角度の積分（半直線とは別の方式）とリングごとに一致 |
| リングの順序・向きの反転 | raw は符号が反転し、正規化した回転数・偶奇・H2 は不変 |
| 境界の扱い | 0・±0.5mm・0.96mm は境界上、1.04mm は境界上でない（丸めない値で判定。研究コードでは 0.96mm が丸めにより境界上でなかった: Codex NOTE 1） |
| 索引（塊3線分で、塊の境目をまたぐ線分・同じリングの複数の塊・複数のリング） | メモリ上の計算と全フィールド一致。既存の `DiagIndex.winding`（正規化した回転数・交差の偶奇）と格子上の全点で一致 |
| R-tree | 600頂点の円で、読む塊は全体の1/4未満。外接矩形の外の地点は0塊 |
| 上限・失敗 | 塊の上限・時間切れ・読取りの失敗・存在しない構成で、事実を含まない `complete: false`。不完全・形式違い・壊れた索引は `ReaderError`。読取専用（書込みは失敗し、ファイルは変わらない） |
| **東京都・洪水の固定検証セット 2,113組**（既存の診断索引、読取専用。[集計](../research/polygon-engine-v0.1/tokyo-flood-compare-summary.json)、`python -m hererisk.research.engine_compare`） | 全組 `complete`。境界上の判定が Phase 4-J と全組一致。境界上でない2,063組で、既存の `DiagIndex.winding` と全組一致、Phase 4-J（原典の形状から計算）のリングごとの回転数・H・H2 と全組一致。H2 は2,063組すべてで成立 |

## 7. 性能・メモリ（Mac上の Docker、aarch64 Linux）

| 項目 | 値 |
|---|---|
| 1地点×1構成（東京都 2,113組） | 中央値 0.30ms、p95 2.6ms、最大 4.0ms |
| 読んだ塊の行数 | 中央値 1、p95 9、最大 50 |
| 読んだ半直線上の線分 | 中央値 64、p95 402、最大 2,533（最大の構成は 354,115 線分） |
| プロセスのピークRSS（Python＋numpy＋Engine、2,113組を処理） | 33.5MB（Engine の import 後 31.2MB → 処理後 33.5MB）。メモリ上限 256MB のコンテナで実行 |
| 索引ファイル | 148MB（読取専用、メモリに常駐させない） |

- 未測定: 全国規模の索引、同時アクセス時の性能、VPS（x86_64・低速ディスク）での性能、`max_chunks`・`budget_s` の既定値の妥当性。
- 東京都の結果は、全国・他のハザードでの性能・正しさを示さない。

## 8. 次工程に残すこと

1. 採用方針（H2・`overlap`・境界の近く・Feature内の重なり）の判断と、`flood-diagnosis-adoption-v2` の要否（OWNER）。
2. Provider への組み込み（参考解析APIの `far_reading` として事実を返すか）。
3. 構成全体への最短距離（必要なら、拡大検索の実装と計測）。
4. ~~正式な有効性の分類（`validity.py`）と、使える形状の内外（`relation.py`）の共通化（移行計画 Step 2-1・2-2）。~~ Phase 4-L で実装（[実装仕様](polygon-engine-validity-relation-v0.1.md)）。
5. 他の都道府県・他のハザードの索引での検証、VPS での計測。
