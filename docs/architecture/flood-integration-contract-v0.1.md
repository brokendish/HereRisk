# Flood Integration Contract v0.1（案・監査対応改訂・無効形状方針改訂）

- Task: Phase 2-B Flood Normalize / Integration Contract v0.1
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は実装・実データ処理・派生形状の製品採用・公開・性能試験の承認ではない
- 作成: 2026-10-21（Claude）
- 改訂: 2026-10-21 Phase 2-B.2 — Codex独立設計監査（Phase 2-B.1、FAIL: HIGH 7 / MEDIUM 3 / LOW 1）の指摘 F-01・F-02・F-03・F-05・F-06・F-07・F-09・F-11 等への対応。対応の全体は [監査対応表](../../reviews/phase2/phase2b2-codex-findings-resolution.md)
- 改訂: 2026-10-23 Phase 2-B.6 — 無効形状の取扱方針。主な変更は次のとおり。全体は [方針決定書](../../reviews/phase2/phase2b6-invalid-geometry-policy-decision.md)
  - 入力資格（第2.1節・第3章）
  - 無効形状の選別と判定保留の範囲（第4.1節・第4.4節）
  - 統合成果物の項目（第6.2節）、公開準備状態（第7.3節）
  - 検証項目（第8章）、Flood APIとの境界（第10章）、停止条件（第11.1節）
- 前提: [Flood Normalize Contract v0.1（案）](flood-normalize-contract-v0.1.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** Phase 2-A.1〜A.4・Phase 2-B.3〜B.5の調査で報告された値（対象集合を併記）、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要

根拠資料: [Phase 2-A.1](../../reviews/phase2/phase2a1-a31a-source-investigation.md)、[Phase 2-A.2](../../reviews/phase2/phase2a2-national-river-source-investigation.md)、[Phase 2-A.3](../../reviews/phase2/phase2a3-kanto-a31a-data-verification.md)、[Phase 2-A.4](../../reviews/phase2/phase2a4-n03-tokyo-coverage-verification.md)、[Phase 2-B.3](../../reviews/phase2/phase2b3-geometry-accuracy-performance-poc.md)、[Phase 2-B.4](../../reviews/phase2/phase2b4-invalid-geometry-classification.md)、[Phase 2-B.5](../../reviews/phase2/phase2b5-remaining-invalid-geometry-survey.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[基本アーキテクチャ](basic-architecture-v0.1.md)、[本番実行認可設計](production-authorization-v0.1.md)

## 1. 目的・適用範囲

複数のNormalize成果物から、対象地域のFlood APIが使う**統合検索データ**（Integration成果物）を、入力を変更せずに再生成可能な形で作る。入力は、Source Fidelity Validateと Geometry Validity Assessmentを完了したNormalize成果物である。

統合成果物は次を満たす。

- 原典属性・ランク・重複関係を失わない。
- **無効形状による判定保留を、有効な形状と混同せず、判定不能の範囲（unknown）として保持する。**
- APIが地域の内外を判定するための行政区域の形状も、同じ公開世代に固定する。

| 項目 | 初期値 | 区分 |
|---|---|---|
| 入力 | **A31aのNormalize成果物3つ**（東京都管理河川 `_13_10`・`_13_20`、関東地方整備局 `_83_10`［想定最大規模48成果品］）**＋N03のNormalize成果物1つ**。それぞれの評価成果物（Geometry Validity Assessment）。派生成果物は利用ポリシーの承認後だけ | ［提案］ |
| 対象地域 | 東京都本土（N03の行政区域コード13101〜13308と東京湾内の所属未定地3ポリゴン） | ［実測: Phase 2-A.4で定義］。地域の規則は版管理された設定で与え、東京都に固定しない［提案］ |
| シナリオ | 想定最大規模 | ［提案］ |
| 将来 | 埼玉県・神奈川県のA31a、他の地域 | ［未決定］ |

本書で扱わないこと: Flood APIの最終的な応答Schema、Data Publishの手順（既存契約）、Registryのフィールド変更（Flood用プロファイルの改訂案を第9.3節に示すが、採用はOWNER判断）。

## 2. 工程の契約

| 工程 | 責務 | 入力 | 出力 | 成功条件 | 失敗条件 | 証跡 | 再実行の単位 | 中断後の再開 |
|---|---|---|---|---|---|---|---|---|
| Integration | Manifestに固定した入力から、次を含む統合成果物を作る: 地域の選別、原典情報と重複関係の保持、**妥当性の状態と判定保留の範囲**、地域形状、空間索引 | Integration Manifest（第3章）と、それが指すNormalize成果物・Source Fidelity Validate Record・Geometry Validity Assessment Record（・承認済みの派生成果物とDerived Geometry Validate Record） | `work/integrated/<run_id>/` の統合成果物（第6.6節の手順で確定したSQLiteファイル） | 第6.6節の確定手順を完了し、Integration Recordを最後に新規作成 | 第11.1節の停止条件 | Integration Record（第7.1節） | 1つのManifest | 確定前の出力は不採用。同じManifestから新しい `run_id` で作り直す |
| Integrated Validate | 統合成果物を入力と照合して合否を決める | 統合成果物（ファイルのSHA-256で指定）、Manifest、入力の各成果物 | Integrated Validate Record（第8.2節） | 第8章の全項目に合格 | いずれかに不合格 | 対象DBのSHA-256を含む記録 | 1つの統合成果物 | 読取専用で、何度でも同じ結果 |
| Data Publish | 既存の契約どおり、検証済みの統合成果物を不変の公開実体にし、Registryを原子的に切り替える | Integrated Validate合格で、**公開準備状態が `ready`**（第7.3節）の統合成果物 | `rel/versions/…`、Registry | 既存契約［確定］＋第9.2節の再確認 | 既存契約、ハッシュの不一致、公開準備状態が `ready` でない | 既存のPublish記録 | 既存契約 | 既存契約（切替前の失敗では旧公開世代を維持） |

**Integration・Integrated Validateが失敗した場合、部分的に作った統合成果物は公開しない。既存の公開世代を保持する**（既存のData Publishの原則［確定］）。**部分成功を無断で公開しない。**

### 2.1 入力資格［提案］

Integrationの各A31a・N03入力は、次の証跡を持たなければならない。

1. Source Fidelity Validate Record が PASS で、対象の `content_sha256` がManifestと一致する。
2. Geometry Validity Assessment Record が SUCCESS（完了）で、対象の `content_sha256` がManifestと一致する。評価したPolygon数がNormalize成果物のPolygon数と一致する（`completeness`）。
3. 全Polygonの妥当性の状態（`valid`・`invalid_classified`・`invalid_unclassified`）と分類が、評価成果物にある。`validation_error` は0件。
4. 派生形状を使う場合は、さらに次が必要である。
   - Derived Geometry Validate Record が PASS である。
   - その利用ポリシーが**OWNERに承認されている**。
   - OWNER承認記録への参照がある（Normalize契約 第10.6節）。

**未分類・未検証の無効形状を、正常な形状として扱わない。** 現時点では派生形状の利用ポリシーは未承認であり、派生形状は入力にできない。

## 3. Integration Manifest［提案］

Integrationの入力は、実行前に作るManifestで完全に固定する。Integration中に入力を変更したり、新しい成果物へ暗黙に差し替えたりしない。

```json
{
  "schema": "hererisk-flood-integration-manifest-v0.2",
  "processing": {"id": "<未採番>", "version": "<未採番>", "dependencies": {"python": "<版>", "sqlite": "<版>", "shapely": "<版>", "geos": "<版>"}},
  "scenario": "maximum",
  "region": {
    "rule": {"ref": "<地域定義（版管理された設定）の参照>", "content_sha256": "<地域定義の内容ハッシュ>"},
    "boundary_input": {
      "content_sha256": "<N03のNormalize成果物の内容ハッシュ>",
      "source_fidelity_validation": {"ref": "<…>", "record_sha256": "<…>"},
      "geometry_assessment": {"ref": "<…>", "record_sha256": "<…>", "content_sha256": "<評価成果物の内容ハッシュ>"},
      "source_zip_sha256": "<N03原典ZIPのSHA-256>"}
  },
  "inputs": [
    {"source_ref": "<取得設定ID>",
     "content_sha256": "<A31aのNormalize成果物の内容ハッシュ>",
     "source_fidelity_validation": {"ref": "<…>", "record_sha256": "<…>"},
     "geometry_assessment": {"ref": "<…>", "record_sha256": "<…>", "content_sha256": "<評価成果物の内容ハッシュ>"},
     "derived_geometry": null,
     "source_zip_sha256": "<…>",
     "products": "all"}
  ],
  "derived_geometry_policy": null,
  "unknown_region_policy": {"level": "L1", "ref": "<判定保留の範囲の方針の参照（未承認）>"},
  "parameters": {"selection_unit": "feature", "selection_predicate": "area_intersection",
                 "geometry_unit": "nano_degree_integer"},
  "manifest_content_sha256": "<自身を除く正規化表現のSHA-256（Normalize契約 第11.1節の規則）>"
}
```

- 入力は**内容ハッシュ**で指定する（run_idは来歴に記録するが、同一性の判定に使わない）。
- Integrationは開始時に、各入力（N03を含む）について次を確認する。合格記録の流用・差し替えを禁止する。
  - Source Fidelity Validate Recordが合格で、`target.content_sha256` がManifestと一致し、`record_sha256` がManifestの値と一致する。
  - Geometry Validity Assessment Recordが完了で、対象と評価成果物の内容ハッシュがManifestと一致する。
- `derived_geometry`（入力ごと）と `derived_geometry_policy` は、利用ポリシーが承認されるまで `null` とする。値がある場合は、次の4つを持つ:
  - 派生成果物の内容ハッシュ
  - Derived Geometry Validate Recordの参照と `record_sha256`
  - 承認された利用ポリシーのID・版
  - OWNER承認記録の参照
- `unknown_region_policy` は判定保留の範囲の方針（第4.4節）。`L2` は承認されるまで指定できない。
- `inputs[].products` は原則 `all`。成果品を除外する場合は、除外の理由と根拠をManifestに記録する。
- Manifestの作成は、OWNERまたは承認された設定に基づく。最新の成果物を自動で選ぶ処理は設けない。**Manifestのハッシュの一致は、OWNERの実行承認の代用にはならない**（Flood用の認可プロファイルは［未決定］。成立まで実データの処理はBLOCKED）。
- 値は例示であり、実在するIDではない。

## 4. 地域の選別［提案］

### 4.1 選別の単位と判定器

**選別の単位は原典Featureとする。** 1つの原典Featureについて、その**いずれかの構成Polygon**が対象地域と面積を持って交差する場合、**Feature全体**（全構成Polygon、原典の形状のまま）を統合成果物に採用する。原則として行政境界で切断しない。

構成Polygonの判定に使う形状は、妥当性の状態で決まる。

| 構成Polygonの状態 | 判定に使う形状 | 判定結果の扱い |
|---|---|---|
| `valid` | 原典の形状 | 下表のとおり |
| `invalid_classified` で、承認された派生形状がある | 派生形状（来歴を記録） | 下表のとおり。統合成果物に「派生形状による判定」と記録 |
| `invalid_classified` で、承認された派生形状がない／`invalid_unclassified` | **判定に使わない** | 第4.4節の判定保留 |

| 構成Polygonの判定結果（有効な形状・承認された派生形状） | 扱い |
|---|---|
| 面積を持つ内部交差あり（area） | そのFeatureを採用する |
| 交差なし（none） | （他の構成Polygonがareaでなく、判定保留でもなければ）採用しない |
| 境界の線・点で接するだけ（touch） | （同上）採用しない |
| **判定器の判定保留（undecided）** | **Integrationを失敗させる**。暗黙に採用・不採用にしない |

- **判定器の判定保留と、無効形状による判定保留は別の概念である**。
  - 判定器の判定保留: 有効な形状について、判定器が決められなかったこと。Integrationを失敗させる。
  - 無効形状による判定保留: 原典の形状を判定に使えないこと。第4.4節の手順で保持する。
- **無効形状に対して、原典では定義されないGEOSの述語（`relate`・`intersects` 等）を、単独の正解として使わない。**
- 構成Polygonごとの判定結果は `polygon_index` 付きで別に記録する（第6.2節 `feature_polygon_selection`）。**Feature件数とPolygon件数は分けて集計する**（Phase 2-A.1でMultiPolygonが96 Feature確認されている［実測。対象: 東京都15成果品］）。
- **判定器の要件（Phase 2-A.4の調査用の判定器は継承しない）**:
  - Phase 2-A.4の調査用の判定器は、面積を持つ交差を「接するだけ」と誤分類する分岐を持つ（Codex監査F-01）。この欠陥は合成ケースで再現した［実測: Phase 2-B.3］。
  - 製品用の判定器は、次の性質を満たすことを必須とする:
    - (1) 面積を持つ交差を「接するだけ」「交差なし」に分類しない
    - (2) 決められない場合は必ず判定保留を返す
    - (3) 第8章 IV-9 の受入ケースにすべて合格する
    - (4) 有効な形状だけを入力とする（無効形状は入力前に第4.4節へ振り分ける）
  - 判定の方式は、Phase 2-B.3の推奨構成（STRtreeで候補抽出、GEOSの `relate` で判定、整数の参照判定器で全件を照合して一致を要求）を候補とする［未決定: OI-3］。
- **Phase 2-A.4の26成果品の選別結果の再検証は未完了である**:
  - 再検証済み: 4成果品の全件は、2つの独立した判定器で件数が一致した［実測: Phase 2-B.3］。22成果品の無効ポリゴンは派生形状で照合した［実測: Phase 2-B.5］。
  - 未検証: 22成果品の有効なポリゴンは再検証していない。
- 選別の結果（成果品ごとのFeature数・Polygon数、交差した区市町村、判定保留の件数）は、統合成果物とIntegration Recordに残す。
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
| 無効形状 | 原典のまま保持し、判定保留の範囲を別に持てる | 切り取りの演算が無効形状で定義されない |

### 4.3 検索用の派生ジオメトリ（性能対策）［未決定］

巨大なポリゴン（荒川の1リング130,885頂点、1ポリゴン558,747頂点・20,681リング［実測］）は、点の内外判定と選別が遅い。

- 調査用の判定器では、26成果品の選別に約47分（うち荒川が約43分）かかった［実測］。
- Phase 2-B.3の推奨構成では、荒川全件の判定（核）は約1.3秒だった［実測］。

検索用の**派生ジオメトリ**（格子での分割、辺の格子索引など）を別に生成する方式は、APIの性能測定の後で比較する。

- 検索用の派生ジオメトリは、Normalize契約第10章の「無効形状の派生ジオメトリ」とは別の概念である。
- 使う場合も、原典のFeature（`key`）・構成Polygon（`polygon_index`）・形状のハッシュと必ず関連付ける。
- 判定結果は、元の形状に対する結果と一致しなければならない（IV-9）。

### 4.4 無効形状による判定保留と、判定不能の範囲（unknown）［提案］

**判定保留のFeatureを、正常な「交差なし」として除外してはならない。** 無効形状の構成Polygonは、次の手順で扱う。

1. **外接矩形による確定的な除外**: 構成Polygonの全頂点の外接矩形が、対象地域のどの行政区域Polygonの外接矩形とも重ならない場合、そのPolygonは対象地域と関係しないと確定してよい。どの解釈（偶奇規則・非ゼロ巻き数規則・GeoJSONの構造・派生形状）でも、区域は元の辺で囲まれ、頂点の外接矩形の中にあるためである［構成上の性質］。
2. **判定保留として保持**: 外接矩形が重なる場合は、そのFeatureを統合成果物に**保持**する（`selection = undetermined_invalid_geometry`）。原典の形状・属性・ランク・来歴をそのまま格納し、検索用の判定には使わない。
3. **判定不能の範囲の記録**: 保持した判定保留のPolygonごとに、判定不能の範囲（unknown）を記録する。

| レベル | 範囲 | 使用の条件 |
|---|---|---|
| **L1（保守的）** | 原典Polygonの全頂点の外接矩形 | 既定。影響を確実に包含する［構成上の性質］ |
| **L2（精密）** | 解釈が異なる領域（Normalize契約 第10.2節(c)の厳密な比較で特定した領域）に限定し、それ以外の領域は解釈が一致する部分として扱う | **次の3つがすべて成立した場合だけ**: (1) 条件(a)(b)を満たし、(c)の比較で解釈が異なる領域を厳密に特定できた、(2) その計算が独立に検証された、(3) L2の採用がOWNERに承認された［未決定: OI-22］。**本改訂では承認していない** |

- **unknownの範囲を過小評価してはならない。** 範囲を保証できない場合（計算できない、検証されていない、未承認）は、L1またはそれより広い範囲を使う。
- 2つの不確実性を区別する:
  - (1) **原典の解釈そのものの不確実性**: 作成者がどの領域を浸水区域としたか。L2でも消えない。L2で範囲を狭めても、解釈が一致する部分は「解釈規則が一致する」というだけで、作成者の意図を確認したものではない。
  - (2) **数学的に異なる解釈の領域**: 解釈規則で内外が異なる点の集合。
- 解釈不一致の型（Normalize契約 第10.3節。調査では46件）は、派生形状の自動採用の対象外であり、判定保留として保持する。GeoJSONの構造や偶奇規則を、OWNER判断なしに他の解釈より優先しない。
- 判定保留のFeatureが地域と面積交差しているかは決まらないため、選別の集計では「採用」「不採用」と別に「判定保留」として数える。

## 5. 重複の保持［提案］

前提となる事実［実測。対象: 国11成果品＋都15成果品、調査用の判定器と標本による値］:

- 異なる成果品の浸水区域が重なる。
  - 東京都本土の標本（7,121点）では、区域に該当した1,942点のうち858点が複数の成果品に該当し、595点はランクが異なる。最大6成果品が重なる。
- 東京都本土と面積交差すると判定されたポリゴンのうち、17,331の形状が複数の成果品に同一の形で含まれる。
  - 大部分は多摩川・大栗川・浅川の間。
  - 同一形状で成果品によりランクが異なるものが223ある。
- 同一成果品の内部では、重なりは見つかっていない（標本調査）。
- 無効ポリゴンについては、成果品をまたいで同一の座標列を持つものはなかった［実測: Phase 2-B.4・B.5］。

契約原則:

1. **原典の各区域の情報（Feature単位）を失わない。** 採用した原典Featureと判定保留として保持した原典Featureのすべてを、次とともに保持する: `key`・`product_id`・原典属性（型付き）・派生列（管理者・河川コード・代表河川名・ランク）・妥当性の状態。
2. **形状だけを根拠とした無条件の重複排除は禁止する。** 同一形状でもランク・出典が異なる。派生形状を使う場合も、原典Feature・ランク・来歴ごとに別に保持する。
3. 同一形状を内部で1つの形状として共有する最適化は認める。形状は内容アドレス（`geometry_sha256`）で識別し、その形状に関連する全原典レコードを `zone_record` から追跡できること。
4. 代表ランク（例: 最大ランク）は統合成果物に格納しない（APIで全区域から計算できる）。**最大ランク方式は候補であり、管理者間の優先関係が原典で確認できていないため、OWNER承認待ち**［未決定］。

## 6. 統合成果物と空間検索［提案］

### 6.1 形式

第一候補: **SQLite**（標準ライブラリの `sqlite3`、RTreeモジュール）［実測: Macと既存APIのベースイメージで利用可能］。公開後は読取専用で開く。**APIが地域の判定に必要な行政区域の形状も、この統合成果物に格納する**（第6.4節）。同一公開世代の不変なsidecarファイルに分ける案は［未決定: OI-14］。

### 6.2 論理構造

座標・外接矩形の正本は**64ビット整数（10⁻⁹度）**で保持する。

```text
zone_record                原典Feature 1件 = 1行（採用したFeatureと判定保留として保持したFeatureの全件）
  record_key (PK)          = Normalizeの key（原典ZIPのSHA-256・正規化メンバー名・feature_index）の正規化表現
  source_ref, product_id, source_properties (型付き原典属性の正規化JSON),
  river_code, river_name_in_source, manager_code, manager_name, rank,
  source_geometry_sha256, geometry_sha256 (FK),
  selection (selected | undetermined_invalid_geometry)

feature_polygon_selection  構成Polygonごとの状態と選別結果
  record_key, polygon_index,
  geometry_status (valid | invalid_classified | invalid_unclassified),
  geometry_basis (original | derived | none),     ← 判定に使った形状（none = 判定に使わない）
  derived_ref (派生成果物の行の参照・derived_geometry_sha256。geometry_basis = derived の場合だけ),
  result (area | none | touch | undetermined_invalid_geometry),
  municipalities (該当した区市町村コードの一覧)

geometry_assessment_ref    構成Polygonごとの評価成果物への参照
  record_key, polygon_index, classes (分類コードの一覧), assessment_content_sha256

geometry                   原典の形状（内容アドレス。同一形状は1行を共有）
  geometry_sha256 (PK), type, n_polygons, n_rings, n_vertices,
  min_x, min_y, max_x, max_y (int64、正確な外接矩形),
  coords (BLOB: 整数座標。符号化は未決定。復号した結果が論理表現として一意であること)

derived_geometry           承認された派生形状（利用ポリシーの承認後だけ。原典の geometry を置き換えない）
  derived_geometry_sha256 (PK), source_record_key, source_polygon_index, source_geometry_sha256,
  policy_id, policy_version, derived_validation_record_sha256, coords (BLOB)

unknown_region             判定不能の範囲（判定保留の構成Polygonごと）
  record_key, polygon_index, level (L1 | L2), reason (分類コード等),
  min_x, min_y, max_x, max_y (int64。L1は原典の全頂点の外接矩形),
  region_coords (BLOB。L2の場合だけ), evidence_ref

geometry_rtree             RTree（id, min_x, max_x, min_y, max_y）＋ 補助表 geometry_rtree_map(id → geometry_sha256)
                           ※ 候補抽出専用。外接矩形の正本ではない（第6.3節）。判定に使う形状だけを登録する
unknown_rtree              unknown_region の候補抽出用RTree

search_piece               （検索用の派生。第4.3節で採用した場合のみ）原典形状・polygon_indexと関連付け

region_polygon             地域の判定に使う行政区域の形状（第6.4節）
  n03_key (N03 Normalizeの key), administrative_area_code, municipality_name, gml_id,
  geometry (int64), in_service_region (bool), geometry_status

region_rtree               region_polygon の候補抽出用RTree

selection_summary          成果品×区市町村のFeature数・Polygon数。採用・不採用・判定保留を分けて集計
metadata                   Manifestの内容ハッシュ、処理ID/版、地域定義の内容ハッシュ、N03の内容ハッシュ、
                           入力ごとの評価成果物の内容ハッシュ、派生形状の利用ポリシー（null または ID・版）、
                           unknownの範囲の方針（レベル・参照）
run_info                   run_id・作成日時など実行固有の値（論理ハッシュの対象外。第7.2節）
```

### 6.3 RTree（候補抽出）の契約

- **正本**: 形状と正確な外接矩形は `geometry`（および `derived_geometry`・`unknown_region`）のint64列。RTreeは候補を絞るだけで、**RTreeだけで判定は完了しない**。
- **通常のRTree（`rtree`）の場合**:
  - SQLiteは座標を32ビット浮動小数で格納し、下限を下向き・上限を上向きに丸める（[SQLite公式仕様](https://www.sqlite.org/rtree.html)）。
  - nano-degreeの整数は地理座標の範囲で `2^53` 未満なので、**整数のまま（Pythonのint、またはfloat64）で渡し、事前にfloat32へ変換しない**。
  - 外向きの丸めにより、索引の矩形は正確な外接矩形を包含する。
- **代替案（`rtree_i32`）**:
  - `rtree_i32` は符号付き32ビット整数で、nano-degreeを直接保持できない。
  - 使う場合は検索専用の10⁻⁷度の格子とし、整数nano-degreeから**下限は床関数、上限は天井関数**で変換する（負数で切り捨て除算と床関数を混同しない）。世界全体でも経度±18億で収まる。
  - 採否は［未決定: OI-4］。
- **検索条件**: 候補抽出は、地点（qx, qy）について `min_x <= qx AND max_x >= qx AND min_y <= qy AND max_y >= qy`（境界を含む）とする。`unknown_rtree` も同じ条件で検索し、**地点がunknownの範囲に入るかを必ず確認する**。
- **入力地点**: 最終の点の内外判定には、**丸めない入力地点**を使う。検索のために地点を近似表現へ変換する場合は、その誤差を包含する検索区間を使い、候補の取りこぼしを防ぐ。入力の座標表現（桁数、WGS84/JGD2011）は［未決定: Normalize契約 ON-11］。
- 精度の損失自体は通常のRTreeを採用しない理由ではない（139°付近のfloat32の刻みは約1.53×10⁻⁵度で、影響は主に余分な候補の増加）。

### 6.4 地域の判定（APIの `not_covered` 等のため）

- 採用した地域の行政区域の形状（N03のNormalize成果物から、地域定義で選んだPolygon）、地域定義の内容ハッシュ、CRS、N03の内容ハッシュを、統合成果物（または同一公開世代のsidecar）に格納する。**APIは `work/` 領域を読まない**［確定: 公開APIは公開実体だけを読む］。
- 行政区域の形状にも妥当性の状態を付ける。無効な行政区域Polygonがある場合の扱いは［未決定: Normalize契約 ON-21］。東京都本土の154ポリゴンは全件有効［実測: Phase 2-B.3］。
- **地域は行政区域Polygonの集合の和集合として扱う。** 地点の判定結果は3状態とする:
  - `inside`（和集合の内部。区市町村どうしの**内部の境界上**の地点も含む）
  - `outside`（和集合の外部）
  - `region_boundary`（和集合の**外縁上**。内部・外部のどちらにも分類しない）
- 内部の境界と外縁の区別の方法（例: 地点を含む境界辺が地域内の2つのPolygonで共有されているか）は、判定器の決定とともに確定する［未決定］。N03の境界の一部は暫定である［実測: 公式の注意事項］。
- **世代の固定**: APIは起動時に、`metadata` の地域定義・N03の内容ハッシュと、`region_polygon` の内容が一致することを確認し、不一致なら起動しない。区域データと地域形状が別の世代になる組合せ（例: 新しいsidecarと古いDB）を拒否する。

### 6.5 性能設計の方針（Codex監査の推奨を反映）

| 用途 | 方針 |
|---|---|
| Normalize | 標準ライブラリ中心のストリーミング処理。数値トークンから整数へ直接変換し、原典順で出力。全データを表形式（GeoDataFrame等）へ載せない |
| Geometry Validity Assessment | 整数の参照判定器とGEOSの2系統。22成果品・約112万ポリゴンの妥当性検査で、合計約152秒［実測: Phase 2-B.5］。巨大な形状では、ループの包含判定・穴の組の判定に索引による候補の絞り込みが必要［実測: Phase 2-B.4で総当たりが1件5分を超えた］ |
| Integration（Mac） | 巨大な形状の**辺の候補抽出**を改善する。N03の面・辺の外接矩形索引を用意し、全辺どうしの照合を避ける。Shapely 2.x / STRtreeで候補を抽出し、GEOSの `relate` と整数の参照判定器の両方で判定する構成を候補とする［実測: Phase 2-B.3。荒川全件で判定の核は約1.3秒（GEOS）・約18秒（整数）］ |
| GEOS | 有限精度の平面幾何エンジンである（[GEOS FAQ](https://libgeos.org/usage/faq/)）。**GEOSの結果だけで候補を除外しない**。無効形状に対するGEOSの述語の結果は定義されないため使わない（第4.1節）。「交差面積 > 0」は面積交差の判定に使わない［実測: 微小な交差を見落とす］ |
| 初期の依存 | Dask・Dask-GeoPandasは初期の必須依存にしない。GeoPandas・pandasは分析・報告用に限る |
| VPS | 読取専用のSQLiteと、必要な点の内外判定のコードだけを置く。巨大な形状の復号・キャッシュ量に上限を設ける |
| 並列化 | 測定の後。SQLiteの書込みは一系統に集約し、完了順に依存せず原典キーで整列する |
| 証跡 | Python・Shapely・GEOS・SQLite・符号化方式の版を記録し、障害の位置を原典ZIP／メンバー／Feature／構成Polygonまで特定できるようにする |
| 測定 | 受入の上限値はOWNERが定める［未決定: OI-15］ |

### 6.6 SQLiteの確定手順と障害

1. 実行専用の領域（`work/integrated/<run_id>/`）に新規ファイルとして作る（上書き禁止）。
2. ジャーナルモードは `DELETE`（ロールバックジャーナル）を基本とする。WALを使う場合は、全トランザクションの完了後に `PRAGMA wal_checkpoint(TRUNCATE)` を行い、ジャーナルモードを `DELETE` に戻す。
3. 全トランザクションをコミットし、**全接続を閉じる**。`-wal`・`-shm`・`-journal` ファイルが残っていないことを確認する（DBファイル単体で自己完結していること）。
4. 読取専用で開き直し、`PRAGMA integrity_check` と論理ハッシュの計算を行い、閉じる。
5. ファイルのSHA-256を計算する。
6. **Integration Recordを最後に新規作成する（確定点）**。Recordのない `run_id` の領域は未完了として扱い、再利用しない。

障害時の扱いは次のとおり。

- 公開前のIntegrated Validateで完全性を検査する。
- API起動時の検証に失敗した場合は起動しない（標高APIと同じ方針［確定: 標高APIの実装方針］）。
- 稼働中の読込失敗は、該当なしとして扱わず、取得失敗としてAPIが報告する（空の正常結果に変換しない）。

## 7. 来歴と再生成性［提案］

### 7.1 Integration Record（実行証跡）

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約［確定］ |
| `manifest` | Manifestの参照と `manifest_content_sha256` |
| `inputs[]` | 各入力の `content_sha256`、Source Fidelity Validate Recordの参照と `record_sha256`、Geometry Validity Assessment Recordの参照と `record_sha256`・評価成果物の内容ハッシュ（開始時に照合した値）、来歴としてのNormalizeの `run_id` |
| `derived_geometry` | 使った場合: 派生成果物の内容ハッシュ、Derived Geometry Validate Recordの `record_sha256`、利用ポリシーのID・版、OWNER承認記録の参照。使わない場合は `null` |
| `processing`・`configuration` | 処理ID/版・依存の版と、設定の内容ハッシュ |
| `output` | 統合成果物の参照、**ファイルのSHA-256**、**論理ハッシュ**（第7.2節） |
| `selection_summary` | 成果品ごとのFeature数・Polygon数（採用・不採用・**判定保留**）、区市町村ごとの件数 |
| `unknown_summary` | 判定保留の構成Polygon数、unknownの範囲のレベル別の件数、地域と重なるunknownの範囲の件数 |
| `publication_readiness` | 第7.3節 |
| `started_at`・`completed_at` | UTC |
| `record_sha256` | 実行証跡ハッシュ |

### 7.2 再生成性

**同じManifestから、論理的に等価な統合成果物を再生成できることを必須とする。** Manifestは、入力の内容ハッシュ・評価成果物・派生成果物・処理版・設定・地域定義・N03版を固定する。

| 区別 | 定義 | v0.1の要件 |
|---|---|---|
| 論理的に等価 | 論理ハッシュの一致 | **必須** |
| バイト単位で一致 | SQLiteファイルのSHA-256の一致 | 必須にしない。決定的な挿入順と `VACUUM INTO` 等で一致するかを、次工程で検証する［未決定: OI-5］ |

**論理ハッシュの対象（明示列挙）**:

| 対象 | 正規化表現 |
|---|---|
| `zone_record` | `record_key` の昇順。全列（`source_properties` は正規化JSON） |
| `feature_polygon_selection` | （`record_key`, `polygon_index`）の昇順。区市町村一覧は昇順 |
| `geometry_assessment_ref` | （`record_key`, `polygon_index`）の昇順。分類コードは昇順 |
| `geometry` | `geometry_sha256` の昇順。`coords` は**復号した論理表現**（整数座標の正規化JSON）。BLOBのバイト列そのものは対象にしない（復号結果が一意であることを検証する） |
| `derived_geometry` | `derived_geometry_sha256` の昇順。`coords` は論理表現 |
| `unknown_region` | （`record_key`, `polygon_index`）の昇順。`region_coords` は論理表現 |
| `region_polygon` | `n03_key` の昇順。形状は論理表現 |
| `selection_summary` | キーの昇順 |
| `metadata` | Manifestの内容ハッシュ、処理ID/版、地域定義・N03・評価成果物の内容ハッシュ、派生形状の利用ポリシー、unknownの範囲の方針 |

**対象外**: `run_info`（run_id・作成日時・パス）、RTreeの内部テーブル（`geometry_rtree*`・`unknown_rtree*`・`region_rtree*`。ただし第8章 IV-7で整合を検証する）、SQLiteのページ配置・空き領域・`sqlite_stat` 等の内部情報。

- IDは安定した原典キーから決める（`record_key`、内容アドレスの `geometry_sha256`）。自動採番の主キーや、形状共有時の「代表レコード」の選択に依存しない。
- 正規化表現の規則は、Normalize契約 第11.1節と同じ。

来歴の連鎖は次のとおり。

1. 原典ZIP（SHA-256）
2. Acquisition Record
3. Normalize成果物（`content_sha256`）
4. Source Fidelity Validate Record（対象の `content_sha256`）
5. Geometry Validity Assessment Record（対象・評価成果物の内容ハッシュ）
6. （派生成果物・Derived Geometry Validate Record・利用ポリシー・OWNER承認）
7. Integration Manifest（`manifest_content_sha256`）
8. Integration Record（ファイルSHA-256・論理ハッシュ）
9. Integrated Validate Record（対象DBのSHA-256）
10. Publish記録
11. 公開Registry

### 7.3 公開準備状態（publication_readiness）［提案］

Integrationの成功（統合成果物ができたこと）と、公開できることは別である。Integration Recordに次のどれかを記録する。

| 値 | 条件 |
|---|---|
| `ready` | Integrated Validateの全項目の合格を前提に、次のどちらかが成り立つ: (1) 地域と重なる判定保留のFeatureが0件、(2) 判定保留とunknownの範囲をAPIで扱う方針がOWNERに承認され、その方針の参照が `metadata` にある |
| `blocked_unknown_policy` | 地域と重なる判定保留のFeatureがあり、その扱いの方針が未承認 |
| `blocked_other` | 利用条件の未解決、Flood用の認可プロファイルの未成立、その他（理由を記録） |

- `ready` 以外の統合成果物は、Data Publishの入力にできない。
- **現時点では、26成果品の調査で地域と重なる判定保留が存在しうる**（解釈不一致の46件、および派生形状の利用ポリシーが未承認のため無効形状のすべて）。利用条件も未解決であるため、`ready` にはならない。

## 8. Integrated Validate［提案］

### 8.1 検証項目

| No | 項目 | 方法 |
|---|---|---|
| IV-1 | Manifestとの一致 | 統合成果物の `metadata` が、Integration Record・Manifestと一致 |
| IV-2 | 入力の合格 | すべての入力（N03を含む）について、次の3つを確認する: Source Fidelity Validate RecordがPASS、Geometry Validity Assessment Recordが完了、対象の内容ハッシュがManifestと一致 |
| IV-3 | 成果品の過不足 | 入力の全成果品について、選別の結果（採用0件を含む）が記録されている |
| IV-4 | 地域の選別（Feature単位） | 製品用の判定器とは**独立した方法**で再計算して確認する（独立した方法の選定は［未決定］）。次のすべてを確認する: (1) 採用した各Featureは、少なくとも1つの構成Polygonが「面積交差あり」、(2) 採用しなかった各Featureは、全構成Polygonが「交差なし」または「接するだけ」で判定保留を含まない、(3) 判定器の判定保留が0 |
| IV-5 | 原典情報の保持 | 保持した原典Feature（採用と判定保留）の件数・`source_properties`・派生列・ランクが、入力のNormalize成果物と一致（全件）。Feature数とPolygon数をそれぞれ照合 |
| IV-6 | 重複関係の保持 | 同一形状を共有する `zone_record` の数・ランクの組合せが、入力から再計算した値と一致 |
| IV-7 | 索引の参照整合 | 次の2点を確認する。`unknown_rtree`・`region_rtree` にも同じ条件を適用する。 (a) 判定に使う形状の全行と `geometry_rtree_map` の全行の**ID集合が双方向に一致**（索引のない形状、形状のない索引行がない）。(b) 各索引行の矩形が正確な外接矩形（int64）を**包含**する（等値は要求しない） |
| IV-8 | 代表地点の判定 | 固定の検証地点（例: 東京駅）で、期待する区域の一覧が返る。期待値には、原典ZIPのSHA-256・対象成果品・処理版を結び付ける（参考: Phase 2-B.3では、東京駅は荒川（国）ランク1の区域に該当［実測］） |
| IV-9 | 特殊な形状（合成データ） | 下記の受入ケースの全件 |
| IV-10 | 再生成 | 同じManifestから再生成した成果物の論理ハッシュが一致 |
| IV-11 | DBの完全性 | `PRAGMA integrity_check` が ok、`-wal`・`-journal` が残っていない、読取専用で開ける |
| IV-12 | API互換 | APIの読取モジュールで開き、IV-8の地点と地域の3状態（第6.4節）、unknownの範囲の判定（第10章）ができる |
| IV-13 | 地域形状の世代 | `region_polygon` の内容とN03の内容ハッシュ・地域定義の内容ハッシュが `metadata` と一致 |
| IV-14 | 妥当性の状態の整合 | 全構成Polygonの `geometry_status`・分類が、入力の評価成果物と一致（全件）。`valid` 以外が `geometry_basis = original` で判定に使われていない |
| IV-15 | 原典と派生形状の参照整合 | `geometry_basis = derived` の全行で、派生形状が承認された派生成果物に存在し、`source_record_key`・`source_polygon_index`・`source_geometry_sha256` が原典と一致。原典 → 派生形状・派生形状 → 原典の双方向で対応が欠けない |
| IV-16 | 形状のハッシュ | `geometry`・`derived_geometry` の全行で、復号した論理表現のSHA-256がキーと一致 |
| IV-17 | 来歴の完全性 | 全 `zone_record` から、原典ZIP・メンバー・Feature・評価成果物の行（・派生形状とその検証記録・利用ポリシー・OWNER承認）まで辿れる |
| IV-18 | 条件(a)〜(e)の証跡 | 派生形状を使う全行で、Derived Geometry Validate Recordの条件(a)〜(e)の結果が `eligible` |
| IV-19 | 判定保留のFeatureの保持 | 外接矩形が地域と重なる判定保留の全構成Polygonについて、Featureが保持され、`unknown_region` がある。判定保留のFeatureが「不採用」として除外されていない |
| IV-20 | unknownの範囲の過小評価がない | 全 `unknown_region` について、範囲が方針どおりであることを再計算する。L1は原典の全頂点の外接矩形を包含すること。L2は承認された場合だけ使用され、その証跡があること |
| IV-21 | 未承認の派生形状の不使用 | `metadata` の利用ポリシーが `null` の場合は、`derived_geometry` が0行で、`geometry_basis = derived` が0行。ポリシーがある場合は、使われた全派生形状がそのポリシーと承認の範囲に含まれる |
| IV-22 | 公開準備状態 | `publication_readiness` が第7.3節の条件と一致 |

**IV-9 受入ケース（地域の選別）**:

- (1) 地域のPolygonと完全に一致するポリゴン → 面積交差あり
- (2) 地域のPolygonに包含され、境界の辺の一部を共有するポリゴン → 面積交差あり
- (3) 地域のPolygonを包含し、辺を共有するポリゴン → 面積交差あり
- (4) 頂点の分割が異なる共通辺（同じ線分を、一方は2辺、他方は3辺で表す）を持つ一致・包含 → 面積交差あり
- (5) 中点が格子に乗らない（半整数になる）辺だけで接触する一致 → 面積交差あり
- (6) 穴を含むPolygonどうしの一致 → 面積交差あり
- (7) 地域のPolygonの穴と完全に一致するポリゴン → 交差なし（または接するだけ）
- (8) 外側で1点だけ接する → 接するだけ
- (9) 外側で1辺を共有するだけ → 接するだけ
- (10) MultiPolygonの1構成Polygonだけが交差 → Feature全体を採用し、`polygon_index` ごとの結果が正しい
- (11) 判定器が決められないように作った縮退ケース → 判定保留でIntegrationが失敗
- (12) 頂点同士の自己接触の無効形状で、外接矩形が地域と重なる（派生形状の利用ポリシーが未承認） → Featureを判定保留として保持し、L1のunknownの範囲を記録
- (13) 無効形状で、外接矩形が地域と重ならない → 関係しないとして不採用（確定）
- (14) 解釈不一致の型（島を含む同じ向きの穴） → 判定保留として保持（派生形状の利用ポリシーがあっても対象外）

Phase 2-B.3の合成37ケース・点11ケース（`intersects` と交差面積の不使用、度の浮動小数の不使用を含む）を受入ケースの初期集合とする。

**IV-9 受入ケース（点の判定）**:

- 穴の内部（区域外）
- 穴の境界上（判定保留）
- 外周の境界上（判定保留）
- MultiPolygonの各構成Polygonの内部
- 巨大ポリゴンの内部
- 地域の内部の境界上（inside）
- 地域の外縁上（region_boundary）
- 判定保留のFeatureのunknownの範囲の内部（「判定保留の区域に該当する可能性」として返る）

検索用の派生ジオメトリを使う場合は、元の形状での判定と一致すること。

不合格の場合はFAILED。公開しない。

### 8.2 Integrated Validate Record（必須項目）

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約 |
| `target` | **検証対象のDBファイルのSHA-256**、論理ハッシュ、Integration Recordの参照と `record_sha256` |
| `inputs` | Manifestの `manifest_content_sha256`、各入力の `content_sha256`、Source Fidelity Validate Record・Geometry Validity Assessment Recordの `record_sha256`、（派生形状を使う場合）Derived Geometry Validate Recordの `record_sha256` と利用ポリシー |
| `configuration` | 設定の内容ハッシュ |
| `validator` | 検証器のID・版、依存の版 |
| `profile` | 検証プロファイルのID・版 |
| `results` | 各項目の合否・件数。不合格の場合は位置（成果品ID・`record_key`・`polygon_index`）。座標の値そのものは記録しない |
| `publication_readiness` | 検証した公開準備状態 |
| `record_sha256` | 実行証跡ハッシュ |

## 9. Dataset Registry / Publishとの接続

### 9.1 原則［確定］

- 公開Registryは、公開資格を持つデータだけの正本である。取得中・Normalize済み・Integration失敗などの状態を記録しない（Dataset Registry §3.8: 公開Registryの `validation.status` は `passed` だけ）。
- 取得・正規化・検証・公開の状態は、それぞれの記録で確認する（データソース定義 §4）。
- Publishの要件は、Integrated Validateの合格に加え、**利用条件の確認とOWNERの公開承認**である。

### 9.2 Publish直前の再確認［提案］

Publishは公開の直前に、次を再確認する。一致しない場合は公開しない。合格記録だけを流用して別の実体を公開することを禁止する。

- 公開候補のDBファイルのSHA-256が、Integrated Validate Record の `target` のSHA-256と一致する。
- 公開準備状態が `ready` である。
- 地域形状をsidecarにする場合は、その内容ハッシュも同じ手順で確認する。

### 9.3 Flood用Registryプロファイルの最小改訂案［未決定: OWNER判断］

既存の標高の実装は `hazard=elevation`、PNG、XYZのcoverage、JSONの公開実体に固定され、未知のキーを拒否する（`src/hererisk/elevation/publish/registry.py` の Schema）。そのSchemaをそのままfloodへ使うことはできない。**既存の標高の契約・実装は変更せず、flood用のプロファイルを別に定義する**ことを提案する。

| 項目 | 改訂案 |
|---|---|
| `source.filename` | **配列や連結した文字列を導入しない**。flood の統合成果物は `acquisition.method = generated` とし、その場合に `source.filename` を省略できる条件をプロファイルで明文化する |
| 来歴 | 全原典のZIP名・SHA-256・Acquisition Record・Normalizeの内容ハッシュと版・検証記録・**評価成果物・派生成果物と利用ポリシー**を持つ、**版付きのLineage Manifest**への参照（`ref`）と `sha256` を追加する。Lineage Manifestは非公開の証跡として保存し、APIが必要とする公開実体への参照とは分ける |
| `acquisition.input_dataset_ids` | **実在するDataset IDだけ**に使う。Manifest IDやNormalizeの `run_id` を代入しない |
| `pipeline.id`・`pipeline.version` | 採用したIntegrationの処理定義を指す。Normalizeを含む全工程の版はLineage Manifestで追跡する |
| `coverage` | flood用の意味を定義する。**対象行政区域はサービス対象地域であって、洪水の評価済み範囲ではない**ことを、項目の名前・値で機械的に区別する（例: `service_region` の参照と、`assessed_extent: unknown`） |
| 世代 | 公開実体（DB）・地域形状・Lineage Manifestを同一の公開世代に固定する。ロールバック時も対応する組を復元する |
| `attribution` | 原典はA31a・N03（いずれも国土交通省）。利用規約は出典と**加工の表示**を求める［実測］。派生形状を使う場合は、その加工の表示も必要［未決定: Normalize契約 ON-20］。文言は［未決定］ |
| 公開単位 | 統合成果物1つ＝1データセットが候補［未決定］ |

### 9.4 既存Elevation APIへの影響

本書の内容は `api/flood` の領域に閉じる。標高のRegistry・公開実体・API・Schema・契約は変更しない。Flood用プロファイルを採用する場合は、標高のSchemaの検証（未知キーの拒否など）が影響を受けないことを改訂案の中で確認する。

### 9.5 公開の可否

**現在のA31a・N03は、利用条件の未解決事項がある（ZIP内メタデータの「国土情報利用約款を参照」とデータページの「CC_BY_4.0」の差異など［実測］）。実データの一般公開を許可済みとして扱わない。** 国土地理院のDEM10Bに関する回答（問合せ番号92497）は、A31a・N03には適用しない。Flood用の認可プロファイルが成立するまで、実データの処理・公開はBLOCKEDとする。

## 10. Flood APIとの境界

最終的な応答Schemaは別工程で決める。**既存のAPI契約は変更しない。** 統合成果物は、APIが次の状態を区別して返せるようにする［提案］。

| 状態 | 意味 | 統合成果物の根拠 |
|---|---|---|
| 有効な浸水区域に該当 | 判定に使える形状（有効な原典、または承認された派生形状）の区域に、地点が含まれる | `geometry`（・`derived_geometry`）と `zone_record` |
| 複数区域に該当 | 上記が複数（成果品・ランクごと） | 同上。全区域の一覧 |
| 無効形状による判定保留 | 地点が、判定保留のFeatureのunknownの範囲に入る | `unknown_region` |
| 解釈が分かれる区域に該当する可能性 | 地点が、解釈不一致の型のunknownの範囲に入る | `unknown_region.reason` |
| 行政区域の対象外 | 地点が対象地域の外（`not_covered` に相当） | `region_polygon`（`outside`） |
| 境界上 | 区域の境界上、または地域の外縁上 | 判定器の `on`、`region_boundary` |
| 正式な洪水評価範囲が不明 | 地域内で、判定に使える区域にもunknownの範囲にも該当しない | A31aは評価済みの範囲を持たない［実測］。`unknown` に相当 |

安全上の原則:

- **N03行政区域の範囲内でA31aの該当ポリゴンが見つからないことを、洪水リスクなし・評価済みの区域外と判定しない。**
- **unknownを安全判定に変換しない。** 判定保留の範囲に入る地点を、「区域外」「浸水なし」として返さない。
- 有効な浸水区域に該当する場合でも、**判定保留の区域が重なる可能性があれば、その情報を消さない**（併記する）。有効な区域で該当しても、判定保留の区域のランクが分からないことを示す。
- `not_covered`（地域外）、`unknown`（評価範囲が不明・判定保留）、`outside_inundation_zone`（評価済みの区域外。A31aだけでは成立しない）の意味を混同しない。
- Phase 2-A.1で未解決の「洪水による浸水なし（内水のみ）」と記載された成果品（旧中川等）の表示・分類は［未決定: OI-16］。

API契約へ引き継ぐ未決定事項: 上表の状態の名前・Schema、判定保留を併記する形式、unknownの範囲のレベル（L1・L2）の表示、派生形状による判定であることの表示［未決定: OI-23］。

## 11. 障害・更新時の契約［提案］

### 11.1 停止条件（FAILED / BLOCKED）

次の場合、IntegrationをFAILEDまたはBLOCKEDとする。部分成功を無断で公開しない。

| 条件 | 扱い |
|---|---|
| 原典（Normalize成果物・評価成果物）が欠落 | FAILED |
| Source Fidelity Validateの失敗・記録の不一致 | FAILED |
| Geometry Validity Assessmentの未完了・`validation_error`・`completeness` の不一致 | FAILED |
| 未承認の派生形状の利用（Manifestに利用ポリシーがない、承認の範囲外） | FAILED |
| 検証Recordの対象ハッシュの不一致 | FAILED |
| 判定器の判定保留（有効な形状） | FAILED |
| 判定保留のFeatureを「交差なし」として除外した | FAILED（IV-19） |
| unknownの範囲を計算できない・保証できない | FAILED（IV-20）。正常な公開準備状態を与えない |
| 地域と重なる判定保留があり、その扱いの方針が未承認 | Integrationは成果物を確定できるが、`publication_readiness = blocked_unknown_policy`（第7.3節）。Publishに進めない |
| Flood用の認可プロファイルの未成立 | BLOCKED（実データの処理を行わない） |

### 11.2 障害・更新のケース

| ケース | 扱い |
|---|---|
| Download成功後のNormalize失敗 | 後続を停止する。成功した取得記録・ZIPは保持する |
| Normalize成功後のSource Fidelity Validate失敗 | Geometry Validity Assessment・Integrationを禁止する。失敗の証跡を対象の内容ハッシュに固定する |
| Geometry Validity Assessmentの失敗 | Integrationを禁止する。失敗の証跡を対象に固定する |
| 無効形状の存在 | 失敗ではない。判定保留として保持し、unknownの範囲を記録する |
| Integrationの中断・入力不一致 | 部分的な成果物は不採用。確定点（Integration Record）がない領域は再利用しない。旧公開世代を維持する |
| DBの破損 | 公開前の検査で検出。API起動を拒否。稼働中は取得失敗として報告し、空の正常結果に変換しない |
| N03だけ更新 | A31aのNormalize成果物・評価成果物は再利用し、N03・地域定義を固定した新しいManifestで選別と検証をやり直す |
| A31aの一部（1つのZIP）だけ更新 | そのZIPだけNormalize・評価をやり直し、他の入力の内容ハッシュを明示的に固定して再統合する |
| 検証器（妥当性・派生形状）の版の更新 | 新しい評価成果物・派生成果物を作り、新しいManifestで再統合する。旧評価を新しい版の結果として扱わない |
| 派生形状の利用ポリシーの承認・改訂・取消し | 新しいManifestで再統合する。取消し後に旧ポリシーの派生形状を含む公開世代を新たに公開しない |
| 旧世代へのロールバック | 既存のRestore → Publishの契約を継承する。DB・地域形状・Lineage Manifestを同一世代として戻す |
| Publish途中の障害 | 切替前は旧世代、切替後の応答不明は現行Registryを確認する（既存契約） |
| 複数の実行 | Publishの排他は既存契約。前処理は実行専用の領域・上書き禁止で衝突を避ける |
| 無承認の公開 | 禁止。Flood用の認可プロファイルが成立するまでBLOCKED |

## 12. テストケース（設計のみ。いずれも実行していない）

「期待」は将来の検証目標であり、成功を確認したものではない。

| ID | 入力・条件 | 期待 |
|---|---|---|
| I-01 | 合格した**A31aのNormalize成果物3つ＋N03のNormalize成果物1つ**と、それぞれの評価成果物でManifestを作成 | Integration・Integrated Validate SUCCESS予定。無効形状があるため `publication_readiness` は `ready` にならない予定 |
| I-02 | Manifestの内容ハッシュと異なる入力（入力の差し替え） | FAILED（入力を変更・自動選択しない） |
| I-03 | Source Fidelity Validateが不合格の入力、または別成果物の合格記録の流用 | FAILED |
| I-04 | IV-9の受入ケース（地域の選別）(1)〜(14) | それぞれの期待どおり |
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
| I-15 | 地域の内部で区域にもunknownの範囲にも該当しない地点 | 「区域外」とせず、評価範囲が不明として返る |
| I-16 | Integrated Validate合格後にDBファイルを差し替えてPublish | Publish直前の再確認でFAILED |
| I-17 | 地域形状（sidecar）とDBの世代が異なる組合せ | API起動を拒否 |
| I-18 | 関東地方整備局の残り37成果品 | 製品用の判定器で選別の結果（採用0件を含む）と妥当性の評価が記録される（調査では未判定） |
| I-19 | Phase 2-A.4の26成果品 | 製品用の判定器で選別をやり直し、調査値との差異を記録する（22成果品の有効なポリゴンは未再検証） |
| I-20 | Geometry Validity Assessmentが未完了の入力 | FAILED |
| I-21 | 評価成果物で `invalid_classified` のPolygonを、原典の形状で判定に使うように改変した統合成果物 | IV-14でFAILED |
| I-22 | 判定保留のFeatureを不採用として除外した統合成果物 | IV-19でFAILED |
| I-23 | unknownの範囲を原典の外接矩形より狭くした統合成果物（L2が未承認） | IV-20でFAILED |
| I-24 | 利用ポリシーが `null` のManifestで派生形状を含めた統合成果物 | IV-21でFAILED |
| I-25 | 有効な区域と判定保留の区域が重なる地点 | 有効な区域の該当と、判定保留の区域の可能性が併記される |
| I-26 | 判定保留のunknownの範囲の地点 | 「区域外」「浸水なし」にならない |
| I-27 | 地域と重なる判定保留があり、方針が未承認 | `publication_readiness = blocked_unknown_policy`。Publishを拒否 |
| I-28 | 派生形状を使う場合の来歴（承認後の将来の試験） | 原典 ↔ 派生形状の双方向の追跡、条件(a)〜(e)の証跡、ポリシーの版が揃う |

## 13. 未決定事項とOWNER判断事項

| No | 事項 | 選択肢・推奨 |
|---|---|---|
| OI-1 | 地域の選別方式 | 原典Feature単位で採用し、構成Polygon単位の結果を別記録（推奨）。切り取らない |
| OI-2 | 判定器の判定保留（有効な形状）の扱い | Integrationを失敗させる（推奨） |
| OI-3 | 製品用の交差判定器 | Phase 2-B.3の推奨構成（STRtree＋GEOS `relate`＋整数の参照判定器の全件照合）を候補。独立監査の後に確定 |
| OI-4 | RTreeの方式 | 通常の `rtree`（整数をそのまま渡す）を第一候補、`rtree_i32` の10⁻⁷度格子は代替 |
| OI-5 | バイト単位の再現性 | v0.1では論理ハッシュの一致を必須、バイト一致は検証して判断 |
| OI-6 | 代表ランクの方式 | 最大ランク方式は候補。管理者間の優先関係の確認後に決定 |
| OI-7 | 同一形状の共有 | 内容アドレスで共有可（全原典レコードの追跡を条件） |
| OI-8 | Flood用Registryプロファイル（第9.3節） | 改訂案の採否 |
| OI-9 | 公開単位 | 統合成果物1つ＝1データセットが候補。地域形状・Lineageを同一世代に含める |
| OI-10 | 出典・加工の表示文言 | 未決定（派生形状を使う場合を含む） |
| OI-11 | 利用条件の照会 | 国土情報提供サイト運営事務局への照会の要否 |
| OI-12 | 隣接県（埼玉県・神奈川県）の追加 | 取得の承認後、Normalize成果物を追加してManifestに含める |
| OI-13 | 地域定義 | 東京都本土の規則（コード範囲・東京湾の所属未定地・島しょ部の除外）、外縁上の状態、暫定の行政界の説明 |
| OI-14 | 地域形状の格納先 | 統合DB内（推奨）／同一世代のsidecar |
| OI-15 | 性能目標 | Macの生成時間・RSS、VPSの検索時間・RSSの受入上限。並列化の採否は測定後 |
| OI-16 | 「洪水による浸水なし（内水のみ）」の成果品 | 表示・分類の方針 |
| OI-17 | Flood用の認可プロファイル | 工程・ZIP・N03と承認範囲の結び付け。成立までBLOCKED |
| OI-18 | 座標の扱い | WGS84とJGD2011、API入力の桁数、格子外の地点の厳密な表現（未決定のまま地点を丸めない） |
| OI-19 | 派生形状の利用ポリシー（Normalize契約 ON-15・ON-16） | 未承認。承認まで無効形状はすべて判定保留 |
| OI-20 | 判定保留とunknownの範囲をAPIで扱う方針 | 承認まで `publication_readiness` は `ready` にならない |
| OI-21 | 解釈不一致の型（46件）の扱い | 判定保留（推奨）。解釈の優先はOWNER判断 |
| OI-22 | unknownの範囲のL2（精密な範囲）の採用条件 | 解析の独立検証とOWNER承認が条件。本改訂では承認しない |
| OI-23 | Flood API契約への状態の引継ぎ | 第10章の状態の名前・Schema・併記の形式 |
| OI-24 | 正式な洪水評価範囲の取得方法 | 未決定（A31aは評価済み範囲を持たない） |
| OI-25 | 26成果品の東京都本土との交差判定の全面再検証 | 製品用の判定器と独立した検証で実施（22成果品の有効なポリゴンは未再検証） |

本書の採用は、Integrationの実装・統合成果物の生成・派生形状の製品採用・公開・性能試験の承認ではない。
