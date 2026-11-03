# Source Resolver 実装仕様 v0.1（Phase 4-N.3）

- 状態: **実装済み・製品から未使用**。`hererisk.location.source_resolver`。洪水・津波・住所Provider、Location API からは呼び出していない（テストで確認）。
- 作成: 2026-11-03（Claude）。基準コミット `cffa878af2e176b9d7ecd82c2a2a0679d7c1f0f0`
- 契約: [Location Resolver / Source Resolver / Regional Index Loader 契約 v0.1](location-resolver-contract-v0.1.md) 第3章。前提: [Location Resolver 実装仕様](location-resolver-impl-v0.1.md)、[ADR-003](../decisions/2026-11-03-n03-micro-gap-boundary.md)（O-14）
- 計測の記録: [source-resolver-4n3-summary.json](../research/nationwide-v0.1/source-resolver-4n3-summary.json)

## 1. 責務

ハザード種別と `ResolvedLocation`（Phase 4-N.2）と登録情報から、**検索すべきソース**を選ぶ。

| する | しない |
|---|---|
| 候補の都道府県とソースの対象地域（service region）からソースを選ぶ、対象地域との関係（Location Resolver の `region_relation`）、未登録（`missing`）、選択の完全性、判定不能 | Polygon・索引の読込み、内外の判定の独自実装、浸水深などの属性の解釈、ソースの統合・優先順位、原典の評価範囲の推測、Location API の `status` の決定 |

依存: `hererisk.location.resolver` だけ（shapely・sqlite3 を直接使わない。`hererisk.flood`・`hererisk.tsunami`・Polygon Engine をimportしない。テストで確認）。

## 2. 登録情報の共通の小さな契約

```python
SourceEntry(hazard, source_id, service_prefectures: tuple[str, ...], index=None)
entries_from_registrations(hazard, sources)   # load_flood_sources / load_tsunami_sources の出力 -> [SourceEntry]
SourceRegistry(entries)                       # 不変のスナップショット（ハザードごと・登録順）
```

- 変換は、各ハザードの**検査済みの登録**（`source_id` と `service_prefectures`）の2項目だけを使う。洪水・津波の登録の形式はどちらもこの2項目を持つ。新しいハザードも、この2項目を持つ登録なら Source Resolver を変えずに使える。
- 正本は当面、地域ファイルの `flood_sources`・`tsunami_sources`（各ハザードの `load_*_sources` が検査する）。Dataset Registry の公開済みエントリに移すときは、同じ `SourceEntry` を作る変換を足すだけにする。
- `index`: 呼び出し側が知っている索引の参照だけを入れる。**現在は `None`**（地域ファイルは索引のファイル・世代を指定していない）。公開世代・SHA-256 を推測して入れない。
- 検査（`SourceRegistryError`）: ハザードID（小文字英数字と `_`）、`source_id`（既存の登録と同じ形式）、同じハザードでの `source_id` の重複、`service_prefectures` が空・重複・2桁のJISコード（01〜47）以外。`SourceResolver` の作成時に、すべての対象都道府県が Location Resolver に登録されていることを確かめる（されていなければ、そのソースは選ばれえないので起動しない）。
- 都道府県コードによる分岐はない（テストで、コードに都道府県の値がないことを確認）。愛媛（38）は登録だけで選ばれる（テスト）。

## 3. API と出力

```python
sr = SourceResolver(registry, location_resolver)
sel = sr.select("tsunami", loc)    # -> SourceSelection
sel.view()
```

```json
{"hazard": "tsunami", "complete": true,
 "sources": [{"source_id": "local-a40-2023-13", "service_region_relation": "boundary",
              "service_prefectures": ["13"], "index": null}],
 "missing": [{"prefecture_code": "14", "reason": "no_source_registered"}],
 "hazard_registered": true, "coverage": "partial", "region_state": "region_boundary",
 "location_status": "near_boundary", "location_coverage": "partial"}
```

| 項目 | 意味 |
|---|---|
| `complete` | 選択を完了したか。Location Resolver が `failed`（`read_failed`・`busy`）、または `region_relation` が混雑（`ResolverBusy`）なら `false`、`sources: null`、`reason`（`location_read_failed` / `location_busy`） |
| `sources` | 選んだソース（登録順）。`[]` は「検索対象が0件」で、失敗（`null`）と区別する |
| `missing` | 候補の都道府県のうち、このハザードのソースが1件も対象にしていない県 |
| `hazard_registered` | このハザードにソースが1件でも登録されているか（「ハザードが未登録」と「県境で一部の県が未登録」を区別する） |
| `coverage` | `missing` があれば `partial`、なければ `full` |
| `region_state` | 選んだソースが全て `inside` かつ `missing` なし → `inside`、それ以外 → `region_boundary`（SR-8）。ソースがなければ `null` |
| `location_status`・`location_coverage` | Location Resolver の状態と、N03の登録が全国か一部か（`partial` のとき「行政区域外」と「未登録の県」を区別できない） |

原典の評価範囲（A31a・A40 は示さない）は、Source Resolver の出力に含めない（Provider の `assessed_extent_relation` のまま）。

## 4. 選択の規則

1. Location Resolver が `failed` → `complete: false`。
2. `outside_admin_area` / `outside_registered_area` → `complete: true`、`sources: []`、`missing: []`（候補の県がない）。
3. それ以外: ハザードのソースを登録順に見て、対象都道府県のどれかが候補の県なら、`region_relation(loc, 対象都道府県)` を求めて選ぶ（`None` なら選ばない）。複数県のソースは1件。集合の内部の県境は外縁ではない（Location Resolver の規則）。
4. `missing`・`coverage`・`region_state` を付ける。

Location API の状態への対応（契約 3.4節 S-1〜S-5、INV-1〜INV-5）は Provider の責務で、本部品は決めない。テストでは参照用の対応関数で、`missing` がある地点・一部のソースが失敗した地点が `no_match` にならないことを確かめた。

## 5. 検証

### 5.1 合成（`tests/contract/test_source_resolver.py`、13件）

1県の内側と県境、複数県のソース（内部の県境は `inside`、外縁は `boundary`）、両側の県のソース・登録順・同じ県の別ソース、片方の県のソースが未登録（`missing`）、県にソースがない、ハザードが未登録、登録範囲外、任意の県（38）、Location Resolver の失敗・混雑、登録の異常値（重複・空・範囲外の県・型・ID）、Location Resolver に N03 がない県、16スレッドの並列（逐次と全件一致）、契約 3.4節の状態対応、**既存の FloodProvider（Bの対象 `{13}` と `{13,14}`）・TsunamiProvider の合成Fixtureの全格子点で、選ばれたソース・順序・`service_region_relation`・`region_state`・該当なし（`not_available`）が完全一致**、依存の向き。

### 5.2 実データ（東京・神奈川のN03、東京の洪水2ソース・津波1ソース。読取専用。`python -m hererisk.research.source_compare`）

地点: 洪水601地点、津波の区域の頂点・外接矩形の中心（各1,000）、N03の辺の頂点と両側5m・9.9m・10.1m・15m（県境の辺・それ以外の辺を各2,000本）、一様乱数2,000点、**N03の微小な隙間（181か所）の中心と、東へ5m・9.9m・10.1m・15m**。計41,506点。比較の相手は、現在の `FloodProvider.lookup`・`TsunamiProvider.lookup`（変更なし）。

| ハザード | 一致 | 差異 | 差異の分類 | `missing` がある地点 |
|---|---|---|---|---|
| 洪水 | 41,421 | 85 | すべて `o14_source_micro_gap`（ADR-003） | 21,146（神奈川に洪水のソースがない県境・神奈川側） |
| 津波 | 41,421 | 85 | すべて `o14_source_micro_gap` | 21,146 |

- 選ばれた `source_id`・順序・候補なし（`not_available`）は全点一致。差異はすべて、隙間の周り10mで Source Resolver が `boundary`、既存が `inside`（`region_state` も同じ理由で違う）。未分類の差異は0件。
- `sr8_missing_forces_boundary`（`missing` があるのに既存が `inside`）は0件だった（県境の地点では既存も `boundary` になるため）。
- 微小な隙間の判定は、Location Resolver を使わない原典の形状の事実で行う: 地点の周り（許容距離の3倍の矩形）で、登録したN03のFeatureに覆われていない部分のうち、地点から許容距離以内のものがすべて1m²未満（Phase 4-N.3 で規則を一般化した。千代田区・新宿区の境界に沿う細長い隙間は、2区域の結合の穴にならず、遠くの3つ目の区域のところで外側につながっていたため）。

## 6. メモリ・同時検索

- 保持するのは登録のスナップショット（ソースの数×数十バイト）と Location Resolver への参照だけ。Polygon・STRtree・索引を持たない。
- 選択はリクエストごとに新しい不変のオブジェクトを作る。16スレッドで逐次と全件一致（合成・実データ）。
- 計測（第7章）: 選択（洪水と津波の2回）の時間は Location Resolver の判定の時間とは別に記録した。

## 7. 計測（1GBのコンテナ、東京＋神奈川のN03、60,601点）

| 項目 | 値 |
|---|---|
| RSS（Location Resolver＋Source Resolver） | 作成前 70.8MiB、作成後 71.6MiB、逐次の選択の後 90.8MiB、16スレッドの後 164.5MiB |
| Location Resolver の判定 | 中央値 0.32ms、p95 1.73ms、最大 35ms |
| 選択（洪水と津波の2回の合計） | 中央値 0.05ms、p95 1.32ms、最大 52ms（大半は `region_relation` の結合） |
| 16スレッドの並列（8,000点） | 計算された結果は逐次と全件一致。96点（1.2%）は明示的な `complete: false`（混雑: `location_busy` / Location Resolver の `busy`）。飽和の負荷 |

- 登録のスナップショットは3件（洪水2・津波1）。Source Resolver の作成でRSSはほぼ増えない。
- 並列時のRSSの増加は Location Resolver の判定と glibc の arena による（[Location Resolver 実装仕様](location-resolver-impl-v0.1.md) 7章）。

## 8. 未解決事項

1. `index` は `None`（索引の参照・世代は 4-N.4 の Regional Index Loader と Registry で決める）。
2. 登録の正本を Dataset Registry に移す時期（設計 O-8）。
3. `missing` の詳細を Location API の応答に出すか（設計 O-6）。
4. 選択の時間の大半は `region_relation` の結合（原典の形状の結合を毎回行う）。同じ地点で複数のハザードが同じ都道府県の集合を問う場合の再利用は、必要になってから考える。
