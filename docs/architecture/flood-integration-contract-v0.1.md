# Flood Integration Contract v0.1（案・監査対応改訂）

- Task: Phase 2-B Flood Normalize / Integration Contract v0.1
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は実装・実データ処理・公開・性能試験の承認ではない
- 作成: 2026-10-21（Claude）
- 改訂: 2026-10-21 Phase 2-B.2 — Codex独立設計監査（Phase 2-B.1、FAIL: HIGH 7 / MEDIUM 3 / LOW 1）の指摘 F-01・F-02・F-03・F-05・F-06・F-07・F-09・F-11 等への対応。対応の全体は [監査対応表](../../reviews/phase2/phase2b2-codex-findings-resolution.md)
- 前提: [Flood Normalize Contract v0.1（案）](flood-normalize-contract-v0.1.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** Phase 2-A.1〜A.4の調査で報告された値（対象集合を併記）、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要

根拠資料: [Phase 2-A.1](../../reviews/phase2/phase2a1-a31a-source-investigation.md)、[Phase 2-A.2](../../reviews/phase2/phase2a2-national-river-source-investigation.md)、[Phase 2-A.3](../../reviews/phase2/phase2a3-kanto-a31a-data-verification.md)、[Phase 2-A.4](../../reviews/phase2/phase2a4-n03-tokyo-coverage-verification.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[基本アーキテクチャ](basic-architecture-v0.1.md)、[本番実行認可設計](production-authorization-v0.1.md)

## 1. 目的・適用範囲

複数のSource Validate合格のNormalize成果物から、対象地域のFlood APIが使う**統合検索データ**（Integration成果物）を、入力を変更せずに再生成可能な形で作る。原典属性・ランク・重複関係を失わず、APIが地域の内外を判定するための行政区域の形状も同じ公開世代に固定する。

| 項目 | 初期値 | 区分 |
|---|---|---|
| 入力 | **A31aのNormalize成果物3つ**（東京都管理河川 `_13_10`・`_13_20`、関東地方整備局 `_83_10`［想定最大規模48成果品］）**＋N03のNormalize成果物1つ** | ［提案］ |
| 対象地域 | 東京都本土（N03の行政区域コード13101〜13308と東京湾内の所属未定地3ポリゴン） | ［実測: Phase 2-A.4で定義］。地域の規則は版管理された設定で与え、東京都に固定しない［提案］ |
| シナリオ | 想定最大規模 | ［提案］ |
| 将来 | 埼玉県・神奈川県のA31a、他の地域 | ［未決定］ |

本書で扱わないこと: Flood APIの最終的な応答Schema、Data Publishの手順（既存契約）、Registryのフィールド変更（Flood用プロファイルの改訂案を第9.3節に示すが、採用はOWNER判断）。

## 2. 工程の契約

| 工程 | 責務 | 入力 | 出力 | 成功条件 | 失敗条件 | 証跡 | 再実行の単位 | 中断後の再開 |
|---|---|---|---|---|---|---|---|---|
| Integration | Manifestに固定した入力から、地域の選別・原典情報と重複関係の保持・地域形状・空間索引を含む統合成果物を作る | Integration Manifest（第3章）と、それが指すNormalize成果物・Source Validate Record | `work/integrated/<run_id>/` の統合成果物（第6.6節の手順で確定したSQLiteファイル） | 第6.6節の確定手順を完了し、Integration Recordを最後に新規作成 | Manifestと入力・検証記録の不一致、地域選別の判定保留、書込み失敗、確定手順の失敗 | Integration Record（第7.1節） | 1つのManifest | 確定前の出力は不採用。同じManifestから新しい `run_id` で作り直す |
| Integrated Validate | 統合成果物を入力と照合して合否を決める | 統合成果物（ファイルのSHA-256で指定）、Manifest、入力のNormalize成果物 | Integrated Validate Record（第8.2節） | 第8章の全項目に合格 | いずれかに不合格 | 対象DBのSHA-256を含む記録 | 1つの統合成果物 | 読取専用で、何度でも同じ結果 |
| Data Publish | 既存の契約どおり、検証済みの統合成果物を不変の公開実体にし、Registryを原子的に切り替える | Integrated Validate合格の統合成果物 | `rel/versions/…`、Registry | 既存契約［確定］＋第9.2節の再確認 | 既存契約、ハッシュの不一致 | 既存のPublish記録 | 既存契約 | 既存契約（切替前の失敗では旧公開世代を維持） |

**Integration・Integrated Validateが失敗した場合、部分的に作った統合成果物は公開しない。既存の公開世代を保持する**（既存のData Publishの原則［確定］）。

## 3. Integration Manifest［提案］

Integrationの入力は、実行前に作るManifestで完全に固定する。Integration中に入力を変更したり、新しいNormalize成果物へ暗黙に差し替えたりしない。

```json
{
  "schema": "hererisk-flood-integration-manifest-v0.1",
  "processing": {"id": "<未採番>", "version": "<未採番>", "dependencies": {"python": "<版>", "sqlite": "<版>"}},
  "scenario": "maximum",
  "region": {
    "rule": {"ref": "<地域定義（版管理された設定）の参照>", "content_sha256": "<地域定義の内容ハッシュ>"},
    "boundary_input": {
      "content_sha256": "<N03のNormalize成果物の内容ハッシュ>",
      "source_validation": {"ref": "<N03のSource Validate Recordの参照>", "record_sha256": "<…>"},
      "source_zip_sha256": "<N03原典ZIPのSHA-256>"}
  },
  "inputs": [
    {"source_ref": "<取得設定ID>",
     "content_sha256": "<A31aのNormalize成果物の内容ハッシュ>",
     "source_validation": {"ref": "<Source Validate Recordの参照>", "record_sha256": "<…>"},
     "source_zip_sha256": "<…>",
     "products": "all"}
  ],
  "parameters": {"selection_unit": "feature", "selection_predicate": "area_intersection",
                 "geometry_unit": "nano_degree_integer"},
  "manifest_content_sha256": "<自身を除く正規化表現のSHA-256（Normalize契約 第9.1節の規則）>"
}
```

- 入力は**内容ハッシュ**で指定する（run_idは来歴に記録するが、同一性の判定に使わない）。
- Integrationは開始時に、各入力について**Source Validate Recordの内容を読み、`status` が合格で、`target.content_sha256` がManifestの `content_sha256` と一致し、`record_sha256` がManifestの値と一致する**ことを確認する。N03（`boundary_input`）にも同じ確認を行う。合格記録の流用・差し替えを禁止する。
- `inputs[].products` は原則 `all`。成果品を除外する場合は、除外の理由と根拠をManifestに記録する。
- Manifestの作成は、OWNERまたは承認された設定に基づく。最新の成果物を自動で選ぶ処理は設けない。**Manifestのハッシュの一致は、OWNERの実行承認の代用にはならない**（Flood用の認可プロファイルは［未決定］。成立まで実データの処理はBLOCKED）。
- 値は例示であり、実在するIDではない。

## 4. 地域の選別［提案］

### 4.1 選別の単位と判定器

**選別の単位は原典Featureとする。** 1つの原典Featureについて、その**いずれかの構成Polygon**が対象地域と面積を持って交差する場合、**Feature全体**（全構成Polygon、原典の形状のまま）を統合成果物に採用する。原則として行政境界で切断しない。

| 構成Polygonの判定結果 | 扱い |
|---|---|
| 面積を持つ内部交差あり（area） | そのFeatureを採用する |
| 交差なし（none） | （他の構成Polygonがareaでなければ）採用しない |
| 境界の線・点で接するだけ（touch） | （同上）採用しない |
| **判定保留（undecided）** | **Integrationを失敗させる**。暗黙に採用・不採用にしない |

- 構成Polygonごとの判定結果は `polygon_index` 付きで別に記録する（第6.2節 `feature_polygon_selection`）。**Feature件数とPolygon件数は分けて集計する**（Phase 2-A.1でMultiPolygonが96 Feature確認されている［実測。対象: 東京都15成果品］）。
- **判定器の要件（Phase 2-A.4の調査用判定器は継承しない）**:
  - Phase 2-A.4で使った調査用の判定器は、頂点・辺の真の交差・辺の中点で内部の交差を見つけられない場合に、無条件で「接するだけ（touch）」に分類する分岐を持ち、判定保留を返す分岐がない。中点が格子に乗らない（半整数になる）辺も検査しない。完全に一致する2つのポリゴンなどでは、面積を共有していても「接するだけ」と誤分類しうる（Codex監査F-01、静的な推論。監査の対応表で同じ分岐を確認）。したがって、**Phase 2-A.4と同じ判定方式を採用するという v0.1 初版の記述を撤回する**。
  - 製品用の判定器は、次の性質を満たすことを必須とする: (1) 面積を持つ交差を「接するだけ」「交差なし」に分類しない、(2) 決められない場合は必ず判定保留を返す、(3) 第8章 IV-9 の受入ケースにすべて合格する。
  - 判定の方式（整数演算の厳密な判定、有理数による残余ケースの処理、GEOSとの組合せ等）は、**独立した検証と小規模な性能評価の後に確定する**［未決定: OI-3］。
- **Phase 2-A.4の26成果品の選別結果（面積交差の有無・区市町村の一覧・件数）は、製品用の判定器で再検証していない。** 調査の観測値（「接するだけ」「判定保留」0件）は、判定器の一般的な正しさを裏付けない。
- 選別の結果（成果品ごとのFeature数・Polygon数、交差した区市町村）は、統合成果物とIntegration Recordに残す。
- 「面積交差あり」で採用したFeatureは地域外の部分も含む。APIは地域外の地点を地域外として扱う（第10章）。

**N03は行政区域であり、A31aの洪水の評価済み範囲を証明しない。** 選別は「どの原典Featureを索引に入れるか」を決めるだけで、地域内で区域に該当しない地点の意味（区域外か、未整備か）は決めない。

### 4.2 切り取り方式との比較

| 観点 | 選別のみ（第一候補） | 行政境界で切り取る |
|---|---|---|
| 原典の形状 | 保持（ハッシュで照合可能） | 加工される（加工の表示が必要） |
| データ量 | 採用したFeatureだけ | さらに小さい |
| 境界付近 | 判定は原典の形状に対して行う | 切り口が新しい境界になり、境界上の扱いが二重になる |
| N03の改版 | 選別だけをやり直す | 形状の再生成が必要 |
| 出典 | そのまま | 切り取った形状への付け直しが必要 |

### 4.3 検索用の派生ジオメトリ（性能対策）［未決定］

巨大なポリゴン（荒川の1リング130,885頂点［実測］）は、点の内外判定と選別が遅い（Phase 2-A.4の調査で、26成果品の選別に約47分、うち荒川が約43分、ピークRSS約328MB［実測。調査用の判定器による値］）。検索用の**派生ジオメトリ**（格子での分割、辺の格子索引など）を別に生成する方式を、小規模な性能測定の後で比較する。派生ジオメトリを使う場合も、原典のFeature（`key`）・構成Polygon（`polygon_index`）・形状のハッシュと必ず関連付け、判定結果は原典の形状に対する結果と一致しなければならない（IV-9）。

## 5. 重複の保持［提案］

前提となる事実［実測。対象: 国11成果品＋都15成果品、調査用の判定器と標本による値］:

- 異なる成果品の浸水区域が重なる。東京都本土の標本（7,121点）で、区域に該当した1,942点のうち858点が複数の成果品に該当し、595点はランクが異なる。最大6成果品。
- 東京都本土と面積交差すると判定されたポリゴンのうち、17,331の形状が複数の成果品に同一の形で含まれる（大部分は多摩川・大栗川・浅川の間）。同一形状で成果品によりランクが異なるものが223ある。
- 同一成果品の内部では、重なりは見つかっていない（標本調査）。

契約原則:

1. **原典の各区域の情報（Feature単位）を失わない。** 採用した原典Featureのすべてを、`key`・`product_id`・原典属性（型付き）・派生列（管理者・河川コード・代表河川名・ランク）とともに保持する。
2. **形状だけを根拠とした無条件の重複排除は禁止する。** 同一形状でもランク・出典が異なる。
3. 同一形状を内部で1つの形状として共有する最適化は認める。形状は内容アドレス（`geometry_sha256`）で識別し、その形状に関連する全原典レコードを `zone_record` から追跡できること。
4. 代表ランク（例: 最大ランク）は統合成果物に格納しない（APIで全区域から計算できる）。**最大ランク方式は候補であり、管理者間の優先関係が原典で確認できていないため、OWNER承認待ち**［未決定］。

## 6. 統合成果物と空間検索［提案］

### 6.1 形式

第一候補: **SQLite**（標準ライブラリの `sqlite3`、RTreeモジュール）［実測: Macと既存APIのベースイメージで利用可能］。公開後は読取専用で開く。**APIが地域の判定に必要な行政区域の形状も、この統合成果物に格納する**（第6.4節）。同一公開世代の不変なsidecarファイルに分ける案は［未決定: OI-14］。

### 6.2 論理構造

座標・外接矩形の正本は**64ビット整数（10⁻⁹度）**で保持する。

```text
zone_record                原典Feature 1件 = 1行（採用したFeatureの全件）
  record_key (PK)          = Normalizeの key（原典ZIPのSHA-256・正規化メンバー名・feature_index）の正規化表現
  source_ref, product_id, source_properties (型付き原典属性の正規化JSON),
  river_code, river_name_in_source, manager_code, manager_name, rank,
  source_geometry_sha256, geometry_sha256 (FK)

feature_polygon_selection  構成Polygonごとの選別結果
  record_key, polygon_index, result (area|none|touch), municipalities (該当した区市町村コードの一覧)

geometry                   形状（内容アドレス。同一形状は1行を共有）
  geometry_sha256 (PK), type, n_polygons, n_rings, n_vertices,
  min_x, min_y, max_x, max_y (int64、正確な外接矩形),
  coords (BLOB: 整数座標。符号化は未決定。復号した結果が論理表現として一意であること)

geometry_rtree             RTree（id, min_x, max_x, min_y, max_y）＋ 補助表 geometry_rtree_map(id → geometry_sha256)
                           ※ 候補抽出専用。外接矩形の正本ではない（第6.3節）

search_piece               （派生。第4.3節で採用した場合のみ）原典形状・polygon_indexと関連付け

region_polygon             地域の判定に使う行政区域の形状（第6.4節）
  n03_key (N03 Normalizeの key), administrative_area_code, municipality_name, gml_id,
  geometry (int64), in_service_region (bool)

region_rtree               region_polygon の候補抽出用RTree

selection_summary          成果品×区市町村のFeature数・Polygon数
metadata                   Manifestの内容ハッシュ、処理ID/版、地域定義の内容ハッシュ、N03の内容ハッシュ
run_info                   run_id・作成日時など実行固有の値（論理ハッシュの対象外。第7.2節）
```

### 6.3 RTree（候補抽出）の契約

- **正本**: 形状と正確な外接矩形は `geometry` のint64列。RTreeは候補を絞るだけで、**RTreeだけで判定は完了しない**。
- **通常のRTree（`rtree`）の場合**: SQLiteは座標を32ビット浮動小数で格納し、下限を下向き・上限を上向きに丸める（[SQLite公式仕様](https://www.sqlite.org/rtree.html)）。nano-degreeの整数は地理座標の範囲で `2^53` 未満なので、**整数のまま（Pythonのint、またはfloat64）で渡し、事前にfloat32へ変換しない**。外向きの丸めにより、索引の矩形は正確な外接矩形を包含する。
- **代替案（`rtree_i32`）**: `rtree_i32` は符号付き32ビット整数でnano-degreeを直接保持できない。使う場合は検索専用の10⁻⁷度の格子とし、整数nano-degreeから**下限は床関数、上限は天井関数**で変換する（負数で切り捨て除算と床関数を混同しない）。世界全体でも経度±18億で収まる。採否は［未決定: OI-4］。
- **検索条件**: 候補抽出は、地点（qx, qy）について `min_x <= qx AND max_x >= qx AND min_y <= qy AND max_y >= qy`（境界を含む）とする。
- **入力地点**: 最終の点の内外判定には、**丸めない入力地点**を使う。検索のために地点を近似表現へ変換する場合は、その誤差を包含する検索区間を使い、候補の取りこぼしを防ぐ。入力の座標表現（桁数、WGS84/JGD2011）は［未決定: Normalize契約 ON-11］。
- 精度の損失自体は通常のRTreeを採用しない理由ではない（139°付近のfloat32の刻みは約1.53×10⁻⁵度で、影響は主に余分な候補の増加）。

### 6.4 地域の判定（APIの `not_covered` 等のため）

- 採用した地域の行政区域の形状（N03のNormalize成果物から、地域定義で選んだPolygon）、地域定義の内容ハッシュ、CRS、N03の内容ハッシュを、統合成果物（または同一公開世代のsidecar）に格納する。**APIは `work/` 領域を読まない**［確定: 公開APIは公開実体だけを読む］。
- **地域は行政区域Polygonの集合の和集合として扱う。** 地点の判定結果は3状態とする:
  - `inside`（和集合の内部。区市町村どうしの**内部の境界上**の地点も含む）
  - `outside`（和集合の外部）
  - `region_boundary`（和集合の**外縁上**。内部・外部のどちらにも分類しない）
- 内部の境界と外縁の区別の方法（例: 地点を含む境界辺が地域内の2つのPolygonで共有されているか）は、判定器の決定とともに確定する［未決定］。N03の境界の一部は暫定である［実測: 公式の注意事項］。
- **世代の固定**: APIは起動時に、`metadata` の地域定義・N03の内容ハッシュと、`region_polygon` の内容が一致することを確認し、不一致なら起動しない。区域データと地域形状が別の世代になる組合せ（例: 新しいsidecarと古いDB）を拒否する。

### 6.5 性能設計の方針（Codex監査の推奨を反映。性能値はすべて未測定）

| 用途 | 方針 |
|---|---|
| Normalize | 標準ライブラリ中心のストリーミング処理。数値トークンから整数へ直接変換し、原典順で出力。全データを表形式（GeoDataFrame等）へ載せない |
| Integration（Mac） | まず巨大な形状の**辺の候補抽出**を改善する（成果品単位の並列化だけでは、荒川の支配的な処理時間が残る［実測からの推論］）。N03の面・辺の外接矩形索引を用意し、全辺どうしの照合を避ける。高速化の候補として Shapely 2.x / STRtree（述語なしの候補抽出の後に、正確性の基準となる整数判定を行う構成）を評価する |
| GEOS | 有限精度の平面幾何エンジンである（[GEOS FAQ](https://libgeos.org/usage/faq/)）。整数のnano-degreeをdoubleで渡すと入力頂点は正確に表せるが、交点・中間演算が整数演算と一致する保証はない。**GEOSの結果だけで候補を除外しない**。厳密性を要件とする間は、整数判定または根拠のある厳密なフォールバックを維持する。GEOSを使う場合は別の判定プロファイルとして、整数判定との独立した比較で評価する（差分試験だけで全入力の一致を保証したことにしない） |
| 初期の依存 | Dask・Dask-GeoPandasは初期の必須依存にしない。GeoPandas・pandasは分析・報告用に限る |
| VPS | 読取専用のSQLiteと、必要な点の内外判定のコードだけを置く。巨大な形状の復号・キャッシュ量に上限を設ける |
| 並列化 | 測定の後。索引改善の後も、OWNERが定める生成時間を超え、CPUが支配的で、同時実行時のRSSが予算内の場合に追加する。SQLiteの書込みは一系統に集約し、完了順に依存せず原典キーで整列する |
| 証跡 | Python・Shapely・GEOS・SQLite・符号化方式の版を記録し、障害の位置を原典ZIP／メンバー／Feature／構成Polygonまで特定できるようにする |
| 測定 | **本格実装の前に、小規模な正確性・性能試験を行う**。測定項目: 生成時間・RSS（Mac）、検索時間・RSS（VPS）、DBサイズ、RTreeの候補数、巨大ポリゴンの判定時間。受入の上限値はOWNERが定める［未決定: OI-15］ |

### 6.6 SQLiteの確定手順と障害

1. 実行専用の領域（`work/integrated/<run_id>/`）に新規ファイルとして作る（上書き禁止）。
2. ジャーナルモードは `DELETE`（ロールバックジャーナル）を基本とする。WALを使う場合は、全トランザクションの完了後に `PRAGMA wal_checkpoint(TRUNCATE)` を行い、ジャーナルモードを `DELETE` に戻す。
3. 全トランザクションをコミットし、**全接続を閉じる**。`-wal`・`-shm`・`-journal` ファイルが残っていないことを確認する（DBファイル単体で自己完結していること）。
4. 読取専用で開き直し、`PRAGMA integrity_check` と論理ハッシュの計算を行い、閉じる。
5. ファイルのSHA-256を計算する。
6. **Integration Recordを最後に新規作成する（確定点）**。Recordのない `run_id` の領域は未完了として扱い、再利用しない。

障害時: 公開前のIntegrated Validateで完全性を検査する。API起動時の検証に失敗した場合は起動しない（標高APIと同じ方針［確定: 標高APIの実装方針］）。稼働中の読込失敗は、該当なしとして扱わず、取得失敗としてAPIが報告する（空の正常結果に変換しない）。

## 7. 来歴と再生成性［提案］

### 7.1 Integration Record（実行証跡）

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約［確定］ |
| `manifest` | Manifestの参照と `manifest_content_sha256` |
| `inputs[]` | 各入力の `content_sha256`・Source Validate Recordの参照と `record_sha256`（開始時に照合した値）、来歴としてのNormalizeの `run_id` |
| `processing`・`configuration` | 処理ID/版・依存の版と、設定の内容ハッシュ |
| `output` | 統合成果物の参照、**ファイルのSHA-256**、**論理ハッシュ**（第7.2節） |
| `selection_summary` | 成果品ごとのFeature数・Polygon数（採用・不採用）、区市町村ごとの件数 |
| `started_at`・`completed_at` | UTC |
| `record_sha256` | 実行証跡ハッシュ |

### 7.2 再生成性

**同じManifest（入力の内容ハッシュ・処理版・設定・地域定義・N03版）から、論理的に等価な統合成果物を再生成できることを必須とする。**

| 区別 | 定義 | v0.1の要件 |
|---|---|---|
| 論理的に等価 | 論理ハッシュの一致 | **必須** |
| バイト単位で一致 | SQLiteファイルのSHA-256の一致 | 必須にしない。決定的な挿入順と `VACUUM INTO` 等で一致するかを、次工程で検証する［未決定: OI-5］ |

**論理ハッシュの対象（明示列挙）**:

| 対象 | 正規化表現 |
|---|---|
| `zone_record` | `record_key` の昇順。全列（`source_properties` は正規化JSON） |
| `feature_polygon_selection` | （`record_key`, `polygon_index`）の昇順。区市町村一覧は昇順 |
| `geometry` | `geometry_sha256` の昇順。`coords` は**復号した論理表現**（整数座標の正規化JSON）。BLOBのバイト列そのものは対象にしない（復号結果が一意であることを検証する） |
| `region_polygon` | `n03_key` の昇順。形状は論理表現 |
| `selection_summary` | キーの昇順 |
| `metadata` | Manifestの内容ハッシュ、処理ID/版、地域定義・N03の内容ハッシュ |

**対象外**: `run_info`（run_id・作成日時・パス）、RTreeの内部テーブル（`geometry_rtree*`・`region_rtree*`。ただし第8章 IV-7で整合を検証する）、SQLiteのページ配置・空き領域・`sqlite_stat` 等の内部情報。

- IDは安定した原典キーから決める（`record_key`、内容アドレスの `geometry_sha256`）。自動採番の主キーや、形状共有時の「代表レコード」の選択に依存しない。
- 正規化表現の規則は、Normalize契約 第9.1節と同じ。

来歴の連鎖: 原典ZIP（SHA-256）→ Acquisition Record → Normalize成果物（`content_sha256`）→ Source Validate Record（対象の `content_sha256`）→ Integration Manifest（`manifest_content_sha256`）→ Integration Record（ファイルSHA-256・論理ハッシュ）→ Integrated Validate Record（対象DBのSHA-256）→ Publish記録 → 公開Registry。

## 8. Integrated Validate［提案］

### 8.1 検証項目

| No | 項目 | 方法 |
|---|---|---|
| IV-1 | Manifestとの一致 | 統合成果物の `metadata` が、Integration Record・Manifestと一致 |
| IV-2 | 入力の合格 | すべての入力（N03を含む）のSource Validate Recordが合格で、対象の `content_sha256` がManifestと一致 |
| IV-3 | 成果品の過不足 | 入力の全成果品について、選別の結果（採用0件を含む）が記録されている |
| IV-4 | 地域の選別（Feature単位） | 採用した各Featureは、少なくとも1つの構成Polygonが「面積交差あり」。採用しなかった各Featureは、全構成Polygonが「交差なし」または「接するだけ」。判定保留の構成Polygonが0。これらを製品用の判定器とは**独立した方法**で再計算して確認する（独立した方法の選定は［未決定］） |
| IV-5 | 原典情報の保持 | 採用した原典Featureの件数・`source_properties`・派生列・ランクが、入力のNormalize成果物と一致（全件）。Feature数とPolygon数をそれぞれ照合 |
| IV-6 | 重複関係の保持 | 同一形状を共有する `zone_record` の数・ランクの組合せが、入力から再計算した値と一致 |
| IV-7 | 索引の参照整合 | (a) `geometry` の全行と `geometry_rtree_map` の全行の**ID集合が双方向に一致**（索引のない形状、形状のない索引行がない）。(b) 各索引行の矩形が、`geometry` の正確な外接矩形（int64）を**包含**する（等値は要求しない）。`region_rtree` にも同じ |
| IV-8 | 代表地点の判定 | 固定の検証地点（例: 東京駅）で、期待する区域の一覧が返る。期待値には、原典ZIPのSHA-256・対象成果品・処理版を結び付ける（参考: Phase 2-A.4の調査では、東京駅は荒川（国）ランク1と隅田川の成果品（都）ランク1［実測。調査用の判定器による値］） |
| IV-9 | 特殊な形状（合成データ。地域の選別と点の判定の両方） | 下記の受入ケースの全件 |
| IV-10 | 再生成 | 同じManifestから再生成した成果物の論理ハッシュが一致 |
| IV-11 | DBの完全性 | `PRAGMA integrity_check` が ok、`-wal`・`-journal` が残っていない、読取専用で開ける |
| IV-12 | API互換 | APIの読取モジュールで開き、IV-8の地点と地域の3状態（第6.4節）を判定できる |
| IV-13 | 地域形状の世代 | `region_polygon` の内容とN03の内容ハッシュ・地域定義の内容ハッシュが `metadata` と一致 |

**IV-9 受入ケース（地域の選別）**: (1) 地域のPolygonと完全に一致するポリゴン → 面積交差あり、(2) 地域のPolygonに包含され、境界の辺の一部を共有するポリゴン → 面積交差あり、(3) 地域のPolygonを包含し、辺を共有するポリゴン → 面積交差あり、(4) 頂点の分割が異なる共通辺（同じ線分を、一方は2辺、他方は3辺で表す）を持つ一致・包含 → 面積交差あり、(5) 中点が格子に乗らない（半整数になる）辺だけで接触する一致 → 面積交差あり、(6) 穴を含むPolygonどうしの一致 → 面積交差あり、(7) 地域のPolygonの穴と完全に一致するポリゴン → 交差なし（または接するだけ）、(8) 外側で1点だけ接する → 接するだけ、(9) 外側で1辺を共有するだけ → 接するだけ、(10) MultiPolygonの1構成Polygonだけが交差 → Feature全体を採用し、`polygon_index` ごとの結果が正しい、(11) 判定器が決められないように作った縮退ケース → 判定保留でIntegrationが失敗。

**IV-9 受入ケース（点の判定）**: 穴の内部（区域外）、穴の境界上（判定保留）、外周の境界上（判定保留）、MultiPolygonの各構成Polygonの内部、巨大ポリゴンの内部、地域の内部の境界上（inside）、地域の外縁上（region_boundary）。派生ジオメトリを使う場合は、原典の形状での判定と一致すること。

不合格の場合はFAILED。公開しない。

### 8.2 Integrated Validate Record（必須項目）

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約 |
| `target` | **検証対象のDBファイルのSHA-256**、論理ハッシュ、Integration Recordの参照と `record_sha256` |
| `inputs` | Manifestの `manifest_content_sha256`、各入力の `content_sha256` と Source Validate Record の `record_sha256` |
| `configuration` | 設定の内容ハッシュ |
| `validator` | 検証器のID・版、依存の版 |
| `profile` | 検証プロファイルのID・版 |
| `results` | 各項目の合否・件数。不合格の場合は位置（成果品ID・`record_key`・`polygon_index`）。座標の値そのものは記録しない |
| `record_sha256` | 実行証跡ハッシュ |

## 9. Dataset Registry / Publishとの接続

### 9.1 原則［確定］

- 公開Registryは、公開資格を持つデータだけの正本である。取得中・Normalize済み・Integration失敗などの状態を記録しない（Dataset Registry §3.8: 公開Registryの `validation.status` は `passed` だけ）。
- 取得・正規化・検証・公開の状態は、それぞれの記録で確認する（データソース定義 §4）。
- Publishの要件は、Integrated Validateの合格に加え、**利用条件の確認とOWNERの公開承認**である。

### 9.2 Publish直前の再確認［提案］

Publishは、公開候補のDBファイルのSHA-256が、Integrated Validate Record の `target` のSHA-256と一致することを、**公開の直前に**再確認する。一致しない場合は公開しない。合格記録だけを流用して別の実体を公開することを禁止する。地域形状をsidecarにする場合は、その内容ハッシュも同じ手順で再確認する。

### 9.3 Flood用Registryプロファイルの最小改訂案［未決定: OWNER判断］

既存の標高の実装は `hazard=elevation`、PNG、XYZのcoverage、JSONの公開実体に固定され、未知のキーを拒否する（`src/hererisk/elevation/publish/registry.py` の Schema）。そのSchemaをそのままfloodへ使うことはできない。**既存の標高の契約・実装は変更せず、flood用のプロファイルを別に定義する**ことを提案する。

| 項目 | 改訂案 |
|---|---|
| `source.filename` | **配列や連結した文字列を導入しない**。flood の統合成果物は `acquisition.method = generated` とし、その場合に `source.filename` を省略できる条件をプロファイルで明文化する |
| 来歴 | 全原典のZIP名・SHA-256・Acquisition Record・Normalizeの内容ハッシュと版・検証記録を持つ、**版付きのLineage Manifest**への参照（`ref`）と `sha256` を追加する。Lineage Manifestは非公開の証跡として保存し、APIが必要とする公開実体への参照とは分ける |
| `acquisition.input_dataset_ids` | **実在するDataset IDだけ**に使う。Manifest IDやNormalizeの `run_id` を代入しない |
| `pipeline.id`・`pipeline.version` | 採用したIntegrationの処理定義を指す。Normalizeを含む全工程の版はLineage Manifestで追跡する |
| `coverage` | flood用の意味を定義する。**対象行政区域はサービス対象地域であって、洪水の評価済み範囲ではない**ことを、項目の名前・値で機械的に区別する（例: `service_region` の参照と、`assessed_extent: unknown`） |
| 世代 | 公開実体（DB）・地域形状・Lineage Manifestを同一の公開世代に固定する。ロールバック時も対応する組を復元する |
| `attribution` | 原典はA31a・N03（いずれも国土交通省）。利用規約は出典と**加工の表示**を求める［実測］。文言は［未決定］ |
| 公開単位 | 統合成果物1つ＝1データセットが候補［未決定］ |

### 9.4 既存Elevation APIへの影響

本書の内容は `api/flood` の領域に閉じる。標高のRegistry・公開実体・API・Schemaは変更しない。Flood用プロファイルを採用する場合は、標高のSchemaの検証（未知キーの拒否など）が影響を受けないことを改訂案の中で確認する。

### 9.5 公開の可否

**現在のA31a・N03は、利用条件の未解決事項がある（ZIP内メタデータの「国土情報利用約款を参照」とデータページの「CC_BY_4.0」の差異など［実測］）。実データの一般公開を許可済みとして扱わない。** Flood用の認可プロファイルが成立するまで、実データの処理・公開はBLOCKEDとする。

## 10. Flood APIとの境界

最終的な応答Schemaは別工程で決める。統合成果物は、APIが次を返せるようにする［提案］:

- 指定地点に該当する全区域（`zone_record` の一覧）
- 各区域の原典ランク、河川コード、成果品の代表河川名（原因河川ではない）、管理者（コード・名称）、成果品ID
- データの出典と公開版
- 境界上の判定状態（判定保留の区域の一覧）
- 地点の地域判定（`inside` / `outside` / `region_boundary`）

安全上の原則:

- **区域のポリゴンが見つからない地点を、洪水リスクなし・評価済みの区域外と判定しない。** A31aは評価済みの範囲を持たない［実測］。
- `outside_inundation_zone` は、評価済み範囲が分からない制約により、A31aだけでは成立しない。地域の内部で区域に該当しない地点は `unknown` に相当する扱い（名称・定義はAPI契約で決める）。
- 地域の外部は `not_covered` に相当する扱い。地域の外縁上は第三の状態として扱う。
- Phase 2-A.1で未解決の「洪水による浸水なし（内水のみ）」と記載された成果品（旧中川等）の表示・分類は［未決定: OI-16］。

## 11. 障害・更新時の契約［提案］

| ケース | 扱い |
|---|---|
| Download成功後のNormalize失敗 | 後続を停止する。成功した取得記録・ZIPは保持する |
| Normalize成功後のSource Validate失敗 | Integrationを禁止する。失敗の証跡を対象の内容ハッシュに固定する |
| Integrationの中断・入力不一致 | 部分的な成果物は不採用。確定点（Integration Record）がない領域は再利用しない。旧公開世代を維持する |
| DBの破損 | 公開前の検査で検出。API起動を拒否。稼働中は取得失敗として報告し、空の正常結果に変換しない |
| N03だけ更新 | A31aのNormalize成果物は再利用し、N03・地域定義を固定した新しいManifestで選別と検証をやり直す |
| A31aの一部（1つのZIP）だけ更新 | そのZIPだけNormalizeを作り直し、他の入力の内容ハッシュを明示的に固定して再統合する |
| 旧世代へのロールバック | 既存のRestore → Publishの契約を継承する。DB・地域形状・Lineage Manifestを同一世代として戻す |
| Publish途中の障害 | 切替前は旧世代、切替後の応答不明は現行Registryを確認する（既存契約） |
| 複数の実行 | Publishの排他は既存契約。前処理は実行専用の領域・上書き禁止で衝突を避ける |
| 無承認の公開 | 禁止。Flood用の認可プロファイルが成立するまでBLOCKED |

## 12. テストケース（設計のみ。いずれも実行していない）

「期待」は将来の検証目標であり、成功を確認したものではない。

| ID | 入力・条件 | 期待 |
|---|---|---|
| I-01 | 合格した**A31aのNormalize成果物3つ＋N03のNormalize成果物1つ**でManifestを作成 | Integration・Integrated Validate SUCCESS予定 |
| I-02 | Manifestの内容ハッシュと異なる入力（入力の差し替え） | FAILED（入力を変更・自動選択しない） |
| I-03 | Source Validateが不合格の入力、または別成果物の合格記録の流用 | FAILED |
| I-04 | IV-9の受入ケース（地域の選別）(1)〜(11) | それぞれの期待どおり |
| I-05 | IV-9の受入ケース（点の判定） | それぞれの期待どおり |
| I-06 | 同一形状でランクが異なる2つの原典Feature | 両方の `zone_record` が残り、形状は共有されうる |
| I-07 | 東京駅（Phase 2-A.4の入力版） | 製品用の判定器で、荒川（国）ランク1と隅田川の成果品（都）ランク1の2区域（調査値の再現を確認） |
| I-08 | 荒川の巨大ポリゴンの内部の地点 | 該当。判定時間を記録 |
| I-09 | 同じManifestで2回生成 | 論理ハッシュが一致（`run_info` の違いは影響しない） |
| I-10 | 統合成果物の1行を改変 | Integrated Validate FAILED |
| I-11 | RTreeの行を削除・孤立した索引行を追加 | IV-7でFAILED |
| I-12 | 索引の矩形が正確な外接矩形を包含しない（内側に丸めた）場合 | IV-7でFAILED。外向きに丸めた矩形は合格 |
| I-13 | Integrationの途中で中断、WALが残った状態 | 確定されず、公開されない。既存の公開世代が残る |
| I-14 | 地域の外部・外縁上・内部の境界上の地点 | `outside` / `region_boundary` / `inside` |
| I-15 | 地域の内部で区域に該当しない地点 | 「区域外」とせず、該当なし（評価済み範囲は不明）として返る |
| I-16 | Integrated Validate合格後にDBファイルを差し替えてPublish | Publish直前の再確認でFAILED |
| I-17 | 地域形状（sidecar）とDBの世代が異なる組合せ | API起動を拒否 |
| I-18 | 関東地方整備局の残り37成果品 | 製品用の判定器で選別の結果（採用0件を含む）が記録される（調査では未判定） |
| I-19 | Phase 2-A.4の26成果品 | 製品用の判定器で選別をやり直し、調査値との差異を記録する（調査値は未再検証） |

## 13. 未決定事項とOWNER判断事項

| No | 事項 | 選択肢・推奨 |
|---|---|---|
| OI-1 | 地域の選別方式 | 原典Feature単位で採用し、構成Polygon単位の結果を別記録（推奨）。切り取らない |
| OI-2 | 判定保留の扱い | Integrationを失敗させる（推奨） |
| OI-3 | 製品用の交差判定器 | 独立した検証と性能評価の後に確定。調査用の判定器は継承しない |
| OI-4 | RTreeの方式 | 通常の `rtree`（整数をそのまま渡す）を第一候補、`rtree_i32` の10⁻⁷度格子は代替 |
| OI-5 | バイト単位の再現性 | v0.1では論理ハッシュの一致を必須、バイト一致は検証して判断 |
| OI-6 | 代表ランクの方式 | 最大ランク方式は候補。管理者間の優先関係の確認後に決定 |
| OI-7 | 同一形状の共有 | 内容アドレスで共有可（全原典レコードの追跡を条件） |
| OI-8 | Flood用Registryプロファイル（第9.3節） | 改訂案の採否 |
| OI-9 | 公開単位 | 統合成果物1つ＝1データセットが候補。地域形状・Lineageを同一世代に含める |
| OI-10 | 出典・加工の表示文言 | 未決定 |
| OI-11 | 利用条件の照会 | 国土情報提供サイト運営事務局への照会の要否 |
| OI-12 | 隣接県（埼玉県・神奈川県）の追加 | 取得の承認後、Normalize成果物を追加してManifestに含める |
| OI-13 | 地域定義 | 東京都本土の規則（コード範囲・東京湾の所属未定地・島しょ部の除外）、外縁上の状態、暫定の行政界の説明 |
| OI-14 | 地域形状の格納先 | 統合DB内（推奨）／同一世代のsidecar |
| OI-15 | 性能目標 | Macの生成時間・RSS、VPSの検索時間・RSSの受入上限。並列化の採否は測定後 |
| OI-16 | 「洪水による浸水なし（内水のみ）」の成果品 | 表示・分類の方針 |
| OI-17 | Flood用の認可プロファイル | 工程・ZIP・N03と承認範囲の結び付け。成立までBLOCKED |
| OI-18 | 座標の扱い | WGS84とJGD2011、API入力の桁数、格子外の地点の厳密な表現（未決定のまま地点を丸めない） |

本書の採用は、Integrationの実装・統合成果物の生成・公開・性能試験の承認ではない。
