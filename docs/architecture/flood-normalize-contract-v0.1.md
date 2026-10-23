# Flood Normalize Contract v0.1（案・監査対応改訂・無効形状方針改訂）

- Task: Phase 2-B Flood Normalize / Integration Contract v0.1
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は実装・実データ処理・公開・性能試験・派生形状の製品採用の承認ではない
- 作成: 2026-10-21（Claude）
- 改訂: 2026-10-21 Phase 2-B.2 — Codex独立設計監査（Phase 2-B.1、FAIL: HIGH 7 / MEDIUM 3 / LOW 1）の指摘 F-03・F-04・F-08・F-09・F-10・F-11 等への対応。対応の全体は [監査対応表](../../reviews/phase2/phase2b2-codex-findings-resolution.md)
- 改訂: 2026-10-23 Phase 2-B.6 — Phase 2-B.3〜B.5の実測に基づく無効形状の取扱方針。改訂の内容と旧章番号との対応は [方針決定書](../../reviews/phase2/phase2b6-invalid-geometry-policy-decision.md)
  - 主な変更: 原典忠実性の検証と形状妥当性の評価を分離した（第2章・第8章・第9章）。派生ジオメトリの条件と来歴を新設した（第10章）。旧第9〜12章は第11〜14章に繰り下げた
- 対象: 災害種別 `flood`、国土数値情報 A31a（2025年度・想定最大規模）、補助データ N03（行政区域、東京都2025年版）
- 関連: [Flood Integration Contract v0.1（案）](flood-integration-contract-v0.1.md)

区分: **［確定］** 既存の承認済み契約（FIXED等）に由来する事項、**［実測］** Phase 2-A.1〜A.4・Phase 2-B.3〜B.5の実データ調査で報告された値（対象集合を併記する）、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要な事項

根拠資料: [Phase 2-A.1](../../reviews/phase2/phase2a1-a31a-source-investigation.md)、[Phase 2-A.2](../../reviews/phase2/phase2a2-national-river-source-investigation.md)、[Phase 2-A.3](../../reviews/phase2/phase2a3-kanto-a31a-data-verification.md)、[Phase 2-A.4](../../reviews/phase2/phase2a4-n03-tokyo-coverage-verification.md)、[Phase 2-B.3](../../reviews/phase2/phase2b3-geometry-accuracy-performance-poc.md)、[Phase 2-B.4](../../reviews/phase2/phase2b4-invalid-geometry-classification.md)、[Phase 2-B.5](../../reviews/phase2/phase2b5-remaining-invalid-geometry-survey.md)、[Dataset Registry設計](dataset-registry-v0.1.md)、[Data Publish設計](data-publish-v0.1.md)、[データソース定義設計](data-source-definition-v0.1.md)、[基本アーキテクチャ](basic-architecture-v0.1.md)、[本番実行認可設計](production-authorization-v0.1.md)

## 1. 目的・適用範囲

### 1.1 目的

A31a・N03の原典（公式配布ZIP）を、データソースごとに独立した**不変のNormalize成果物**へ変換し、後続のIntegrationが出典・原典属性・ランク・形状を失わずに使える形にする。あわせて、全Polygonの**形状妥当性を評価・分類**し、無効な形状を有効な形状と混同せずに後続工程へ引き継ぐ。

### 1.2 適用範囲

| 項目 | 初期値 | 区分 |
|---|---|---|
| 災害種別 | `flood` | ［提案］ |
| データ | A31a 2025年度、**採用シナリオ＝想定最大規模**（ZIP内フォルダ `20_想定最大規模`）。ZIP内の他のシナリオ（計画規模・浸水継続時間・家屋倒壊等）は正規化しない | ［提案］ |
| データソース（原典ZIP） | `A31a-25_13_10_GEOJSON.zip`、`A31a-25_13_20_GEOJSON.zip`（東京都管理河川）、`A31a-25_83_10_GEOJSON.zip`（関東地方整備局） | ［実測: Phase 2-A.1・A.3で取得・完全性を確認］ |
| 補助データ | `N03-20250101_13_GML.zip`（行政区域） | ［実測: Phase 2-A.4］ |
| 将来の追加 | 埼玉県・神奈川県のA31a（未取得・未検証） | ［未決定］ |

全国対応の設計とし、東京都・関東地方整備局に固有の処理をコードに埋め込まない。データソースの一覧・対象成果品・地域の規則・資源上限は、Source Definition（`api/flood/conf/`）の版管理された定義で与える［提案］。

### 1.3 本書で扱わないこと

Integration（統合・地域選別・空間索引・unknown範囲の統合）、Flood APIの応答Schema、Data Publish、Registryの変更。

### 1.4 設計原則（Phase 2-B.6）［提案］

| 原則 | 内容 |
|---|---|
| P-1 原典保持 | Normalizeは原典の全Feature・全属性・座標列・リング構造・順序・由来を保持する。**無効な幾何形状が含まれていても、原典を改変しない**。入力の破損・構文違反・必須情報の欠落・再現不能など、原典を正しく保存・解釈できない異常は、従来どおり失敗とする |
| P-2 合格条件の分離 | **原典を忠実に正規化できたこと（Source Fidelity）と、Flood判定に使用可能であること（Geometry Validity・派生形状の採用）は、別の合格条件とする** |
| P-3 妥当性の分類 | すべてのPolygon（MultiPolygonの構成Polygonを含む）に妥当性の状態を記録する。Feature件数と構成Polygon件数は分けて扱う |
| P-4 既定は判定保留 | 無効形状は、初期状態では判定保留とする。**無効形状であることは、原典の浸水区域が存在しないことを意味しない** |
| P-5 派生形状の分離 | 派生形状は原典の座標列を置き換えない。別の成果物・レコードとして管理し、原典Featureへ必ず戻れるようにする |
| P-6 無条件の自動修復の禁止 | `make_valid` 等の成功だけでは製品への採用を認めない。修復形状の妥当性と、原典作成者の意図との一致は別である |

## 2. パイプライン全体と本書の範囲

```text
Download ─► Normalize ─► Source Fidelity Validate ─► Geometry Validity Assessment ─┬─► Integration ─► Integrated Validate ─► Data Publish
 (ZIP取得)    (本書)       (本書 第8章)                 (本書 第9章)                   │   (統合契約)       (統合契約)              (既存契約)
                                                                                     └─► Derived Geometry Build ─► Derived Geometry Validate
                                                                                          (本書 第10章。利用ポリシーが承認された場合だけ。現時点では未承認)
```

各工程は既存のPipeline Execution Contractに従う［確定］: 明確な終了ステータス（SUCCESS / FAILED / BLOCKED）、正常終了の場合だけOrchestratorが次工程を実行、各モジュールは後続を直接呼ばない、結果とログを `run_id` で関連付ける、ログは結果の代用にしない。既存の共通Orchestrator・Data Publish・Registryの責務は変更しない。

### 2.1 工程ごとの契約（本書の範囲）

| 工程 | 責務 | 入力 | 出力 | 成功条件 | 失敗条件 | 証跡 | 再実行の単位 | 中断後の再開 |
|---|---|---|---|---|---|---|---|---|
| Download | 公式ZIPの取得と完全性・安全性の確認 | Source Definitionの取得設定 | `dl/` 配下のZIP（取得IDで世代を識別。第4.1節）、Acquisition Record | HTTP 200、Content-Lengthと実サイズの一致、SHA-256の記録、ZIP中央ディレクトリ・CRCの検査、第6.1節の安全性検査に合格 | 通信失敗、サイズ不一致、CRC不正、安全性検査の不合格 | Acquisition Record | 1つの原典ZIP | 部分ファイルは確定させない。新しい取得として最初から確認する |
| Normalize | 原典ZIPの採用シナリオの全メンバーを、規定の正規化表現に変換する。**幾何形状の妥当性では拒否しない** | Download成功のZIP（Acquisition RecordのSHA-256で照合） | `work/normalized/<run_id>/` のNormalize成果物（第4章） | 全対象メンバーを変換し、内容ハッシュ（第11章）を計算し、Normalize Recordを最後に確定 | 第5章の拒否条件、入力ハッシュ不一致、書込み失敗 | Normalize Record（第7章） | 1つの原典ZIP（＝1つのNormalize成果物） | 確定前の出力は不採用。同じ入力から新しい `run_id` で作り直す |
| Source Fidelity Validate | Normalize成果物を原典と照合し、**原典の情報が欠落・変更なく保存されたこと**を検証する（旧称 Source Validate） | Normalize成果物（内容ハッシュで指定）と、その原典ZIP | Source Fidelity Validate Record | 第8章の検証プロファイルの全項目に合格 | いずれかの項目に不合格 | Source Fidelity Validate Record（第8.3節） | 1つのNormalize成果物 | 読取専用で、何度でも同じ結果になる |
| Geometry Validity Assessment | 全Polygonの位相妥当性を評価し、無効形状を分類・記録する | Source Fidelity Validate合格のNormalize成果物 | 評価成果物（第9.5節）、Geometry Validity Assessment Record | **全Polygonに妥当性の状態を付与**し、2つの独立した検証器の判定が全件一致（第9.2節） | 検証器の異常終了、対象Polygonの欠落、検証器間の不一致（`validation_error`）、入力ハッシュ不一致 | Geometry Validity Assessment Record（第9.6節） | 1つのNormalize成果物 | 読取専用の入力から何度でも同じ評価内容になる |
| Derived Geometry Build / Validate | 承認された利用ポリシーの対象分類について派生形状を作り、独立に検証する | 評価成果物と利用ポリシー | 派生成果物・Derived Geometry Validate Record（第10章） | 第10章の全条件 | 第10章の条件の不成立は、その形状を判定保留のまま残す（工程の失敗ではない）。検証器の異常終了・入力不一致は失敗 | 第10.4節・第10.5節 | 1つの評価成果物 | 同上 |

- **Geometry Validity Assessmentが成功しても、無効な形状が「判定に使用可能」になるわけではない。** 評価の成功は、全Polygonの状態が確定したことだけを意味する。
- Geometry Validity Assessmentが未完了、検証器が異常終了、対象Featureが欠落した場合は、後続工程（Integration、派生形状の生成）を進めない。
- Integration以降は[Integration契約](flood-integration-contract-v0.1.md)。

### 2.2 既存のDownload実装・認可との関係［実測・提案］

- 既存のDownload（Phase 1-A〜1-I）は標高PNG（1タイル）専用であり、ZIPの取得・検査を持たない［実測］。flood用には、同じ共通Orchestrator・保存層・Acquisition Recordの契約に従う、ZIP用のDownloadモジュールを `api/flood` 側に追加する必要がある［提案］。
- 既存の本番実行認可は、承認記録をタイル・既存工程に結び付けている［確定: 本番実行認可設計］。flood の各工程（Download（ZIP単位）・Normalize・Source Fidelity Validate・Geometry Validity Assessment・派生形状・Integration・Integrated Validate・Publish）と、複数のZIP・N03を、どの承認範囲に結び付けるかは**実行前に追加設計が必要**［未決定］。
- Manifest・成果物のハッシュの一致は、OWNER承認の代用にはならない。**Flood用の認可プロファイルが成立するまで、実データの処理はBLOCKEDとする**［提案］。

## 3. データソースの独立性

| 原則 | 内容 | 区分 |
|---|---|---|
| 1原典ZIP = 1 Normalize成果物 | 東京都管理河川は2つのZIP（`_10`・`_20`）なので2成果物、関東地方整備局は1成果物、N03は独立した補助の1成果物 | ［提案］ |
| 成果物の同一性 | 成果物は「原典ZIPのSHA-256・対象メンバー集合・処理ID/版・設定の内容ハッシュ」で同一性を定める（第11章の内容ハッシュ） | ［提案］ |
| 相互に依存しない | あるデータソースのNormalizeは、他のデータソースの成果物を読まない。N03もA31aのNormalizeには使わない（地域の選別はIntegrationで行う） | ［提案］ |
| 不変 | 確定したNormalize成果物・評価成果物・派生成果物は変更しない。新版は新しい `run_id` の別成果物として作る。参照する統合・公開世代がある間は削除しない | ［提案］（既存の上書き禁止・旧実体保護の原則に従う［確定］） |
| 対象メンバー | 採用シナリオのフォルダの**全成果品**（関東地方整備局は想定最大規模48成果品［実測: ZIP内の件数］） | ［提案］。理由: 東京都本土との交差を調査したのは48成果品のうち11成果品だけ［実測］で、しかもその判定器には欠陥がある（Integration契約 第4.1節）。調査結果で事前に絞ると、未検証の成果品を「関係しない」と扱うことになる |
| 代替案 | Source Definitionで対象成果品を列挙し、それだけを変換する | ［未決定］。除外の根拠の記録が必要 |

## 4. Normalize成果物の論理構造

### 4.1 配置と世代［提案］

既存のAPI別データ領域（`/data/<api>/` の `dl/`・`work/`・`rel/versions/`・`records/`）［確定］に従い、標高の配置と揃える。

```text
/data/flood/
  dl/current/<source_ref>/<acquisition_id>/<原典ZIP名>   Download（取得ごとに別の取得IDの領域。上書きしない）
  work/normalized/<run_id>/
    content.json                                        内容の目録（実行固有値を含まない。第4.2節）
    members/<product_id>.ndjson                         成果品ごとの正規化レコード（第4.3節）
  work/geometry_assessment/<run_id>/                    形状妥当性の評価成果物（第9.5節）
  work/derived_geometry/<run_id>/                       派生成果物（第10.4節。利用ポリシーが承認された場合だけ）
  records/acquisitions/<run_id>/…                       Acquisition Record（既存契約の形式）
  records/configurations/<run_id>/…                     設定スナップショット（既存契約の形式）
  records/normalizations/<run_id>.json                  Normalize Record（実行証跡。確定点）
  records/source_fidelity_validations/<run_id>.json     Source Fidelity Validate Record（確定点）
  records/geometry_assessments/<run_id>.json            Geometry Validity Assessment Record（確定点）
  records/derived_geometry_validations/<run_id>.json    Derived Geometry Validate Record（確定点）
```

- **同名ZIPの改版**: 公式サイトで同じファイル名のZIPが更新されても、取得ごとに別の `acquisition_id` の領域に保存し、既存のZIP・成果物を上書きしない。ZIPの世代は `acquisition_id` とSHA-256で識別する［提案］。
- **実行専用の領域**: 各工程は自分の `run_id` の領域にだけ書く。すべてのファイルは新規作成のみ（上書き禁止）。**確定点は各工程のRecordの新規作成**であり、Recordのない `run_id` の領域は未完了として扱い、再利用しない［提案］。未完了の領域の掃除の方針は［未決定］。
- `source_ref` はSource Definitionの取得設定ID（命名は［未決定］）。
- 保存層の書込み許可領域に、上記の `work/`・`records/` の各領域を追加する必要がある（標高と同様の明示的な最小追加）［提案］。

### 4.2 content.json（内容の目録）［提案］

**実行固有の値（run_id、取得のrun、日時、設定スナップショットのパス）を含めない。** これらはNormalize Record（第7章）に置く。

```json
{
  "schema": "hererisk-flood-a31a-normalized-content-v0.1",
  "source": {
    "zip_name": "A31a-25_83_10_GEOJSON.zip",
    "zip_sha256": "<原典ZIPのSHA-256>",
    "dataset": "A31a", "reference_year": "2025", "scenario": "maximum",
    "scenario_folder": "20_想定最大規模"
  },
  "processing": {"id": "<未採番>", "version": "<未採番>"},
  "configuration_content_sha256": "<設定スナップショットの内容（正規化JSON）のSHA-256>",
  "crs": "EPSG:6668",
  "coordinate_unit": "nano_degree_integer",
  "members": [
    {"product_id": "A31a-20-25_83_8303040001_10",
     "zip_member": "20_想定最大規模/A31a-20-25_83_8303040001_10.geojson",
     "zip_member_raw": "20_想定最大規模\\A31a-20-25_83_8303040001_10.geojson",
     "member_size": 0, "member_crc32": "<中央ディレクトリの値>", "member_sha256": "<展開バイト列のSHA-256>",
     "source_root_properties": {"type": "FeatureCollection", "name": "<原典の値>", "crs": "<原典の値>",
                                 "other": [{"key": "xy_coordinate_resolution", "type": "number", "token": "1e-09"}]},
     "output": "members/A31a-20-25_83_8303040001_10.ndjson", "output_sha256": "<出力のSHA-256>",
     "features": 0, "polygons": 0, "interior_rings": 0, "vertices": 0,
     "geometry_types": {"Polygon": 0, "MultiPolygon": 0},
     "rank_counts": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0},
     "source_rank_type": "integer"}
  ]
}
```

値はすべて例示であり、実在する処理ID・公開版・承認証跡ではない。`members` は `product_id` の昇順。

### 4.3 正規化レコード（A31a、`members/<product_id>.ndjson` の1行）［提案］

1つの原典Feature＝1レコード。原典ファイル内の順序で出力する。

```json
{"key": {"zip_sha256": "<…>", "zip_member": "20_想定最大規模/A31a-20-25_83_8303040001_10.geojson", "feature_index": 0},
 "product_id": "A31a-20-25_83_8303040001_10",
 "source_properties": [
   {"key": "A31a_201", "type": "string", "value": "8303040001"},
   {"key": "A31a_202", "type": "string", "value": "荒川"},
   {"key": "A31a_203", "type": "string", "value": "83"},
   {"key": "A31a_204", "type": "string", "value": "関東地方整備局"},
   {"key": "A31a_205", "type": "number", "token": "1"}],
 "derived": {"river_code": "8303040001", "river_name_in_source": "荒川",
             "manager_code": "83", "manager_name": "関東地方整備局", "rank": 1},
 "geometry": {"type": "Polygon", "coordinates": [[[139234567000, 35641250000], ["…"]]]},
 "source_geometry_sha256": "<原典geometryの正規化表現（第11.1節）のSHA-256>"}
```

| 項目 | 規則 | 区分 |
|---|---|---|
| `key` | **原典Featureの安定した複合一意キー**: 原典ZIPのSHA-256 ＋ 正規化したZIPメンバー名 ＋ 0始まりの `feature_index`。実行ごとに変わる値を含めない | ［提案］ |
| `source_properties` | 原典 `properties` の**全キー**を、原典の出現順に、型（`string`・`number`・`boolean`・`null`・`object`・`array`）と値で保持する。数値は原典の数値トークン（文字列）を `token` に保持する。値が `null` のキーは `type: null` として残し、**キーが存在しないことと区別する** | ［提案］ |
| `derived` | 検索用の派生列。`source_properties` から規則どおりに導出し、原典の値を置き換えない（派生ジオメトリとは別の概念。第10章） | ［提案］ |
| `derived.rank` | 整数 1〜6。原典のランクは文字列（東京都）と整数（関東地方整備局）が確認されている［実測］。**同一成果品の中で型が混在する場合は、v0.1では拒否する**（第5章）［提案。OWNER判断 ON-12］ | ［提案］ |
| `derived.river_name_in_source` | 原典 `A31a_202`。**成果品の代表河川名であり、個別ポリゴンの原因河川ではない**（統合成果品・同一形状の重複がある［実測］） | ［実測］ |
| `geometry` | `Polygon` / `MultiPolygon` のまま。**各リングの頂点の順序・向き・始点・穴の順序を、無効形状であっても原典のとおり保持する**。座標は10⁻⁹度単位の整数（第6.3節） | ［提案］ |
| `source_geometry_sha256` | 原典geometryの正規化表現のハッシュ。同一形状の追跡と原典との照合に使う | ［提案］ |

- 浸水深ランクの区分境界（以上・未満）は**原典で未規定**であり、Normalizeは区分の数値（`depth_min_m` 等）を付け加えない［実測: 製品仕様書］。
- 原典にないキーを付け加えない。原典ルートの追加メンバー（例: `xy_coordinate_resolution`）は `content.json` の `source_root_properties` に型付きで保持する。
- 正規化レコードには妥当性の評価結果を書き込まない（評価は別の成果物。第9章）。Normalize成果物の内容ハッシュは、評価の有無・評価器の版に依存しない。

### 4.4 N03（補助データ）の正規化［提案］

N03には専用の目録・レコード・検証プロファイルを適用する（A31aの項目を流用しない）。

| 項目 | 規則 |
|---|---|
| 入力 | `N03-20250101_13_GML.zip` の **GML**（正本）。同梱のGeoJSON・Shapefileは正規化に使わない（GeoJSONは外周の向きが逆で、座標の桁数が異なる［実測］） |
| 安全な解析 | 第6.1節（DTD・実体の拒否を、文字コードを考慮した解析設定で保証。外部参照の禁止） |
| 座標軸 | GMLの `posList` は（緯度, 経度）［実測］。正規化レコードは（経度, 緯度）の10⁻⁹度整数 |
| 地物レコード | `key`（ZIPのSHA-256・メンバー名・地物の出現順）、地物の `gml:id`、参照する `gml:Surface` の `gml:id`、**全子要素を型付きで保持**（`prefectureName`・`municipalityName`・`administrativeAreaCode`・`districtName`［実測］、その他の要素も出現順に）、`geometry`（外周1・穴0以上。`curveMember` の数も記録） |
| 目録 | `content.json` 相当（`schema: hererisk-flood-n03-normalized-content-v0.1`）。地物数・Surface数・穴の数・頂点数、行政区域コード別の件数、データセットの `boundedBy`、出力のSHA-256 |
| 地域の区分 | **本土・島しょ部などの区分はNormalizeでは行わない**。区分の規則は、Integrationの地域定義（版管理された設定）で与える。公式属性には本土・島しょ部の区別がない［実測］ |
| 形状妥当性 | A31aと同じGeometry Validity Assessment（第9章）を適用する。東京都本土の154ポリゴンは全件有効［実測: Phase 2-B.3］。N03に無効形状がある場合の地域判定での扱いは［未決定: ON-21］ |
| 注意 | N03は行政区域を表すだけであり、A31aの洪水の評価済み範囲を表さない |

## 5. 拒否・隔離・許容の条件

**自動修復して成功扱いにすることは禁止する。** 本章の拒否は、**原典を正しく保存・解釈できない異常**に限る。幾何形状の位相的な無効は、本章の拒否の対象にしない（第9章で評価・分類する）。

| 条件 | v0.1の扱い［提案］ |
|---|---|
| ZIPの完全性（CRC、サイズ、ハッシュ）の不一致 | 拒否（Downloadで停止） |
| 第6.1節の安全性・資源上限の違反 | 拒否（展開・解析しない） |
| GeoJSONのルートが `FeatureCollection` でない、`crs` が EPSG:6668 でない、`name` がメンバー名の幹と一致しない | 拒否 |
| JSONの重複キー（どの階層でも） | 拒否 |
| 必須属性（`A31a_201`〜`A31a_205`）の欠落・null・空 | 拒否 |
| ランクが整数1〜6（または文字列"1"〜"6"）以外 | 拒否 |
| 同一成果品の中でランクの型が混在 | 拒否［未決定: ON-12］ |
| geometryがnull・空、`Polygon`/`MultiPolygon` 以外 | 拒否 |
| 非有限値、2次元以外の座標 | 拒否 |
| 小数10桁以上の座標（整数化で不可逆になる）、指数表記など許可しない数値表記 | 拒否（第6.3節） |
| 座標の配列構造の破損（リングが座標の配列でない、座標が2要素の数値でない等） | 拒否（原典を解釈できない） |
| **幾何形状の位相的な無効**（自己接触・自己交差・リングが閉じていない・4点未満・穴の配置の不正・内部の非連結等） | **拒否しない**。原典のとおり保持し、Geometry Validity Assessment（第9章）で分類する。既定は判定保留 |
| 連続する重複頂点 | 許容して件数を記録（変更しない）［未決定: ON-6］ |
| 想定外の追加属性 | 許容（`source_properties` に保持） |
| N03: 第8.2節の参照構造の不正 | 拒否（地物とSurfaceの対応を解釈できない） |

- 旧版（Phase 2-B.2改訂）の「第6.2節の位相妥当性の不合格は拒否」は、本改訂で上記に置き換えた。理由は、調査した26成果品のすべてに無効形状があり［実測: Phase 2-B.5］、拒否すると原典の浸水区域を保持できないためである。
- 安全性は、無効形状を判定に使わない既定（判定保留）と、Integration・APIでの扱い（unknownを安全判定に変換しない）で維持する（Integration契約 第4.4節・第10章）。

**隔離**（不正なFeatureを除外して残りを成功とする）は、v0.1では採用しない［提案］。無効形状のFeatureも除外せず保持する。採用する場合は、除外するFeatureを特定する検証プロファイルと、除外の証跡、OWNERの承認を必要とする［未決定］。

Phase 2-A.1・A.3の調査では、調査で検査した項目（属性・座標表記等）について上記の拒否条件に該当するFeatureは0件と報告されている［実測。対象: 東京都15成果品と関東地方整備局8成果品］。位相妥当性の実測は第9.1節。

## 6. 入力の安全性とジオメトリ

### 6.1 入力の安全性・資源上限［提案］

資源上限は、**設定スナップショットに固定**する（実行中に変えない［確定: 開始時設定の固定］）。値は初期候補であり、OWNERの承認とテストで確定する［未決定: ON-13］。初期候補は調査で観測された最大値に余裕を持たせて決めるが、本書では性能を推測した値を記載しない。

| 対象 | 上限・規則（初期候補の考え方） |
|---|---|
| ZIP | エントリ数の上限、展開後の総量の上限、1エントリの展開後サイズの上限。観測値: エントリ数221、総量4,402,131,145 B、最大エントリ628,250,582 B［実測: 関東地方整備局ZIP］ |
| 圧縮率 | **圧縮率だけで拒否しない**。N03の正常な `.dbf` は167.9倍で、展開後1,284,370 B［実測］。「圧縮率がRを超え、かつ展開後サイズがSを超える」場合に拒否する二条件とし、展開前に中央ディレクトリの値で判定したうえで、展開中も実際の展開量で上限を監視する |
| 対象外メンバー | 正規化しないメンバー（N03の `.dbf` 等、他のシナリオ）は展開しない。安全性の検査（名前・サイズ）だけ行う |
| パス | バックスラッシュを区切りとして解釈し［実測: A31aの全エントリ］、各要素の空・`.`・`..`・NUL・ドライブ文字・絶対パスを拒否する。Unicode正規化（NFC）と区切りの正規化を行った**後の名前が重複する場合は拒否**する。symlinkのエントリは拒否する |
| 成果品ID | 同一ZIP内で `product_id`（メンバー名の幹）が重複する場合は拒否する |
| JSON | 1行の最大長、1Featureの最大頂点数・最大リング数、ネストの最大深さ、1成果品の最大Feature数を上限とする。観測値: 最長行約1.48MB（関東地方整備局・多摩川の成果品）、1ポリゴンの最大頂点数558,747・最大リング数20,681（荒川）［実測: Phase 2-B.3・B.4］。重複キーは拒否。1行1Featureの書式を前提にストリーミングで読み、書式が異なる場合は拒否する（全体を一度にメモリへ読む方式へ切り替えない） |
| XML（N03） | DOCTYPE・ENTITY・外部DTDを、**文字コードを考慮した解析器の設定**で拒否する（バイト列の部分一致だけに頼らない。例: 解析器のDOCTYPE宣言ハンドラで停止する）。`xlink:href` は**同一文書内の一意な `gml:id` への参照（`#id`）だけ**を許可し、外部参照・未解決参照・重複IDを拒否する |

### 6.2 位相妥当性

位相妥当性の評価・分類は第9章（Geometry Validity Assessment）で行う。Normalize・Source Fidelity Validateは位相妥当性で合否を決めない。

### 6.3 座標の表現［提案］

- 原典の座標は小数9桁以下と報告されている［実測。対象: 関東地方整備局の8成果品は `xy_coordinate_resolution` 1e-09、東京都15成果品も最大9桁］。10⁻⁹度単位の整数に変換しても、**座標の数値を失わない（数値的な可逆性）**。
- 変換は、JSONの数値を浮動小数として読まず、**数値トークン（文字列）から直接**整数へ変換する。小数10桁以上、および許可しない数値表記（指数表記等。許可する表記は［未決定］）は拒否する（丸めない）。4成果品・約1,170万座標で、数値トークンからの厳密な変換と浮動小数を経由する変換の差は0件だった［実測: Phase 2-B.3］。製品では厳密な変換を維持する。
- **原典の文字列表記（例: `139.0` と `139.000` の違い）は、Normalize成果物からは復元できない**。原典の文字列表記は、不変の原典ZIP（Download）と `member_sha256` によって保持・照合する。
- 範囲: 経度・緯度とも符号付き64ビット整数に収まる。
- より粗い単位（例: 10⁻⁷度）への丸めは不可逆であり、Normalizeでは採用しない（Integrationの検索専用の派生データで使う場合は、そちらの契約に従う）。

### 6.4 座標系［未決定］

原典はJGD2011（EPSG:6668）［実測］。Normalizeは座標を変換せず、`crs` を記録する。API入力（WGS84）との扱い、API入力の桁数、nano-degree格子に乗らない地点の厳密な表現は、Flood API契約で決める。**未決定のまま地点を丸めない**。位置正確度はA31aが標準偏差50m、N03が25m［実測: メタデータ］。

## 7. Normalize Record（実行証跡）［提案］

| 項目 | 内容 |
|---|---|
| `record_schema_version` | 証跡の契約版 |
| `run_id`・`module`・`status` | 既存の実行結果の契約［確定］ |
| `source_ref`・`acquisition_id`・`acquisition_record_ref`・`acquisition_record_sha256` | 入力の識別 |
| `input.zip_sha256` | Acquisition Recordの値と照合済みの原典ZIPのハッシュ |
| `configuration` | 設定スナップショットの参照とSHA-256、および内容ハッシュ（開始時に固定）［確定: 開始時設定の固定］ |
| `processing` | 処理ID・版、依存の版（Python、使用した場合はShapely・GEOS、SQLite等） |
| `content_ref`・`content_sha256` | 第4.2節の内容の目録とその内容ハッシュ（第11.1節） |
| `outputs[]` | 成果品ごとの出力の参照・SHA-256・件数 |
| `warnings[]` | 許容した事項（連続する重複頂点の件数など） |
| `started_at`・`completed_at` | UTC |
| `record_sha256` | 実行証跡ハッシュ（第11.2節） |

Normalize Recordの新規作成（上書き禁止）を、Normalize全体の成功の確定点とする。

## 8. Source Fidelity Validate［提案］

旧称 Source Validate。**原典の情報が欠落・変更なく保存されたこと**だけを検証する。旧プロファイルの位相妥当性の項目（旧V-8・旧VN-6）は、Geometry Validity Assessment（第9章）へ移した。**幾何形状が無効であることだけを理由に、Source Fidelity ValidateをFAILEDとしない。**

### 8.1 A31aの検証プロファイル

| No | 項目 | 方法 |
|---|---|---|
| V-1 | 入力の一致 | 原典ZIP・メンバーのSHA-256が `content.json` と一致 |
| V-2 | Feature数 | 成果品ごとに、原典のFeature数＝出力のレコード数 |
| V-3 | ランク分布 | 成果品ごとに、原典のランク別件数＝出力のランク別件数 |
| V-4 | 原典属性の保持 | 全レコードで、`source_properties` が原典のキー・順序・型・値（数値トークン）と一致。`derived` が規則どおり |
| V-5 | geometry型 | Polygon / MultiPolygon の件数が原典と一致 |
| V-6 | 形状の構造 | Feature数・Polygon数・穴の数・頂点数を**それぞれ別に**原典と照合。**リングの頂点の順序・向き・始点が原典と同一**（無効形状を含む全件） |
| V-7 | 座標の数値的可逆性 | 出力の整数座標を10進に戻した数値が、原典の数値トークンの数値と一致（全頂点） |
| V-8 | （欠番） | 旧「位相妥当性」。第9章へ移動 |
| V-9 | 出力のハッシュ | 各出力ファイルのSHA-256が `content.json` と一致し、`content.json` の内容ハッシュがNormalize Recordと一致 |
| V-10 | 目録の完全性 | 採用シナリオのフォルダの全メンバーが目録にある（またはSource Definitionの列挙と一致） |
| V-11 | キーの一意性 | `key` が成果物全体で一意 |

### 8.2 N03の検証プロファイル

| No | 項目 | 方法 |
|---|---|---|
| VN-1 | 入力の一致 | 原典ZIP・GMLメンバーのSHA-256 |
| VN-2 | 件数 | 地物数・Surface数・外周数・穴の数・頂点数を原典と照合 |
| VN-3 | 参照構造 | `gml:id` の一意性、全ての `ksj:bounds` の `xlink:href` が同一文書内の `gml:Surface` に解決、未解決参照0、外部参照0、参照されないSurfaceの扱い（拒否または記録。［未決定］） |
| VN-4 | 属性 | 全地物の全子要素（`prefectureName` 等）が原典と一致。行政区域コード別の件数 |
| VN-5 | 座標軸と可逆性 | （緯度, 経度）→（経度, 緯度）の変換と、数値の一致（全頂点） |
| VN-6 | （欠番） | 旧「位相妥当性」。第9章へ移動 |
| VN-7 | 出力のハッシュ | V-9と同じ |

### 8.3 Source Fidelity Validate Record（必須項目）

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約 |
| `target` | 検証対象のNormalize成果物の `content_sha256`、`content_ref`、Normalize Recordの参照と `record_sha256`、出力ファイルの集合（パスとSHA-256） |
| `inputs` | 照合に使った原典ZIPのSHA-256、Acquisition Recordの参照とSHA-256 |
| `configuration` | 設定の内容ハッシュ |
| `validator` | 検証器のID・版、依存の版 |
| `profile` | 検証プロファイルのID・版（A31a用またはN03用） |
| `results` | 各項目の合否・件数。不合格の場合は最初のN件の位置（成果品ID・`feature_index`・`polygon_index`）。座標の値そのものは記録しない |
| `record_sha256` | 実行証跡ハッシュ |

- 1項目でも不合格ならFAILED。Geometry Validity Assessment・Integrationの入力にできない。
- **合格記録の流用・差し替えを禁止する**: 後続工程は、Source Fidelity Validate Recordの `target.content_sha256` が、指定したNormalize成果物の内容ハッシュと一致することを確認する（Integration契約 第3章）。
- 不合格の記録も、対象のハッシュに固定して保存する（後から別の成果物の記録として扱わない）。
- 旧版の「Source Validate Record」への参照は、本Recordを指す（必須項目・ハッシュの結合は旧版から変えていない）。

## 9. Geometry Validity Assessment［提案］

### 9.1 実測事実（Phase 2-B.3〜B.5）［実測］

| 項目 | 件数 |
|---|---:|
| 対象26成果品（Phase 2-A.4の対象）のPolygon | 1,508,379 |
| 有効 | 1,484,991 |
| 無効 | 23,388（1.55%） |
| 派生形状の適用候補（調査PoCの条件(a)〜(e)を満たした） | 23,342 |
| 解釈不一致（条件(c)の不成立） | 46 |

| 無効の分類（重複あり） | 件数 |
|---|---:|
| 自己接触（頂点‐頂点） | 23,294 |
| 内部の非連結 | 94 |
| 真の辺交差・辺の重複・スパイク・面積0のリング・頂点‐辺の接触 | 0 |

- 26成果品のすべてに無効形状がある（最少は霞川の0.16%）。1つのFeatureに無効な構成Polygonが2つ以上ある例はなかった。
- 解釈不一致の46件は、いずれもMultiPolygonの構成Polygonである。外周と同じ向きの穴を持ち、その穴が同じFeatureの他の構成（島）を内側に含む型である。
- Shapely（GEOS 3.14.1）と整数の参照判定器の有効／無効の判定は、全1,508,379件で一致した。
- **これらの件数は、調査した26成果品についての測定値であり、全A31aデータで保証されたものではない。** 関東地方整備局ZIPの残りの成果品・他の都道府県では、未出現の分類（真の交差・スパイク等）が現れうる。

### 9.2 妥当性モデルと検証器［提案。最終確定は ON-5］

- 妥当性モデルは **OGC Simple Featuresの妥当性**（リングの単純性、穴の配置、内部の連結、MultiPolygonの構成の非重複）を第一候補とする。
- 判定は、**独立した2つの検証器**で行う:
  - (1) 整数演算による参照判定器
  - (2) 版を固定したGEOSの妥当性検査
- 2つの判定が一致しないPolygonは `validation_error` とする。
- 検証器のID・版、依存（Python・Shapely・GEOS）の版、検証設定のハッシュを固定し、証跡に記録する。
- **実装前に、モデルと2つの検証器と版を固定することを実装開始の条件とする**（ブロッキング）。

### 9.3 妥当性の状態（Polygonごと）［提案］

| 状態 | 意味 | 後続での扱い |
|---|---|---|
| `valid` | 2つの検証器がともに有効と判定 | 原典の形状を判定に使用できる |
| `invalid_classified` | 2つの検証器がともに無効と判定し、第9.4節の分類に当てはまった | 既定は**判定保留**。承認された派生形状がある場合だけ、その派生形状を判定に使用できる（第10章） |
| `invalid_unclassified` | 無効だが、既知の分類に当てはめられない（「その他・判定不能」） | **判定保留**。派生形状の対象外 |
| `validation_error` | 検証器の異常、検証器間の不一致、評価できない入力 | **Assessment全体をFAILEDとする**（後続を進めない） |

- MultiPolygonは、構成Polygonごとの状態に加えて、**Feature全体の妥当性**（構成どうしの内部の重なり・辺の共有）を評価する。
- Feature件数と構成Polygon件数は分けて集計する。

### 9.4 無効形状の分類［提案。Phase 2-B.4・B.5の分類体系を採用候補とする］

1つのPolygonに複数の分類を付けてよい（重複あり）。**既知の分類に無理に当てはめない**。どの分類にも当てはまらない場合は「その他・判定不能」とする。

| コード | 分類 | 判定の根拠（座標列と整数演算） |
|---|---|---|
| `self_touch_vertex_vertex` | 頂点同士の自己接触 | 同じリングで同じ座標の頂点が連続しない位置に現れる |
| `self_touch_vertex_edge` | 頂点と辺の内部の接触 | 頂点が同じリングの非隣接の辺の内部にある |
| `proper_crossing` | 真の辺交差 | 2辺が互いの内部の点で交わる |
| `collinear_overlap` | 辺の重複 | 2辺が同一直線上で長さを持って重なる |
| `spike` | スパイク | 隣接する2辺が往復する |
| `zero_area_ring` | 面積0のリング | リングの符号付き面積が0、または異なる点が3未満、4点未満、閉じていない |
| `shell_hole_touch` | 外周と穴の接触 | 外周と穴が点で接する |
| `hole_hole_touch` | 穴同士の接触 | 2つの穴が点で接する |
| `hole_containment` | 穴の包含関係の不正 | 穴が外周の外、穴の入れ子、穴どうしの内部の重なり、外周と辺を共有 |
| `multipolygon_overlap` | MultiPolygon構成面の重複 | 構成どうしの内部の重なり、または辺の共有 |
| `interior_disconnected` | 内部の非連結 | リングと接点の二部グラフに閉路がある |
| `other_undetermined` | その他・判定不能 | 上記に当てはまらない |

**OGCの妥当性とは別の検査**: 外周と同じ向きの穴（`hole_same_orientation_as_shell`）、外周の向き（時計回り・反時計回り）を、全Polygonについて別に記録する。OGCの妥当性の条件ではないが、解釈の不一致（第10.2節の条件(c)）の原因になる［実測: Phase 2-B.4・B.5の46件］。

### 9.5 評価成果物［提案］

```text
work/geometry_assessment/<run_id>/
  summary.json            成果品ごとの件数（Feature・Polygon・状態別・分類別・向きの検査）。実行固有値を含まない
  assessments.ndjson      valid以外の全Polygonと、向きの検査に該当する全Polygonの1行ずつ
```

`assessments.ndjson` の1行（例示）:

```json
{"key": {"zip_sha256": "<…>", "zip_member": "<…>", "feature_index": 0}, "polygon_index": 0,
 "source_geometry_sha256": "<…>", "status": "invalid_classified",
 "classes": ["self_touch_vertex_vertex", "shell_hole_touch"],
 "locations": [{"class": "self_touch_vertex_vertex", "ring": 0, "vertex_indices": [7, 11]},
               {"class": "shell_hole_touch", "rings": [0, 3], "vertex_indices": [[120], [0]]}],
 "orientation": {"shell": "cw", "holes_same_orientation_as_shell": []},
 "validators": {"reference": "invalid", "geos": "invalid"}}
```

- 位置の情報はリング・頂点・辺の番号で記録する（座標の値そのものは記録しない。原典から再現できる）。1つのPolygonで位置が多い場合は件数と先頭N件を記録し、全件は別ファイルに分けてよい［未決定: 形式］。
- 決定的なシリアライズ規則（第11.1節）に従い、`key`・`polygon_index` の昇順で出力する。内容ハッシュを計算する。

### 9.6 Geometry Validity Assessment Record（必須項目）［提案］

| 項目 | 内容 |
|---|---|
| `run_id`・`module`・`status` | 既存の実行結果の契約 |
| `target` | 対象のNormalize成果物の `content_sha256`、Source Fidelity Validate Recordの参照と `record_sha256`（合格であること） |
| `inputs` | 原典ZIPのSHA-256、ZIPメンバーの一覧 |
| `validators` | 2つの検証器のID・版、Python・Shapely・GEOSの版 |
| `model` | 妥当性モデルのID・版、分類体系のID・版 |
| `configuration` | 検証設定の内容ハッシュ |
| `outputs` | `summary.json`・`assessments.ndjson` の参照・SHA-256、評価成果物の内容ハッシュ |
| `counts` | 成果品ごと・全体の、Feature数・Polygon数・状態別・分類別・向きの検査の件数 |
| `completeness` | 評価したPolygon数が、Normalize成果物のPolygon数と一致すること |
| `record_sha256` | 実行証跡ハッシュ |

- 全件の無効形状の識別子は評価成果物に保持し、Recordにはその参照・SHA-256・件数を持たせる。
- 成功の条件: 全Polygonに状態が付き、`validation_error` が0件で、`completeness` が一致すること。**無効形状が存在してもSUCCESSになりうる**（状態の記録が完了したことを意味する）。

## 10. 派生ジオメトリ［提案。利用ポリシーは未承認］

### 10.1 位置付け

派生ジオメトリは、無効形状の原典を置き換えずに、判定に使える有効な形状を**別の成果物として**作るものである。

**現時点では、派生形状の利用ポリシーは承認されていない**（ON-15）。承認までは、無効形状はすべて判定保留のまま扱う。条件(a)〜(e)の成立は、**原典作成者が意図した浸水区域との一致を証明しない**。

### 10.2 適用条件(a)〜(e)

派生形状の採用候補とするには、`invalid_classified` のPolygonについて次のすべてを満たす必要がある。

| 条件 | 内容 | 検証方法 |
|---|---|---|
| (a) 接触の種類 | すべての接触が、既存の頂点同士の接触である | 第9.4節の分類で、`self_touch_vertex_edge`・`proper_crossing` がないこと |
| (b) 対象外の不正を含まない | 真の辺交差、辺の重複、スパイク、面積0のリングを含まない | 同上（`proper_crossing`・`collinear_overlap`・`spike`・`zero_area_ring`・`other_undetermined` がない） |
| (c) 面の解釈が一致 | **偶奇規則・非ゼロ巻き数規則・GeoJSONのPolygon / MultiPolygonの構造**（1番目のリングを外周、以降を穴）の3つの内外の解釈が、**全域で一致**する | リングを繰り返し現れる頂点で単純なループに分解し、ループの包含関係と向きから、各領域での3つの解釈を整数演算で厳密に比較する。**有限個の地点（ランダム地点等）の一致では代用しない**。包含関係を決められない場合は不成立 |
| (d) 独立した派生方式の一致 | 次の3方式の出力が、いずれも有効なPolygon / MultiPolygonで、互いに位相的に一致する: (1) 整数演算によるリングの分割・再構成（C-3）、(2) `make_valid(method="linework")`、(3) `make_valid(method="structure")` | 低次元の要素・GeometryCollection・予期しない構成要素は**不成立**。同じ入力での再実行で同一の結果になること。C-3の出力は整数の参照判定器とGEOSの両方で有効であること |
| (e) 原典にない頂点を追加しない | 派生形状の頂点集合が、原典の頂点集合に含まれる | 派生形状の全座標を原典の頂点集合と照合する |

- 条件を判定できなかった場合（資源制限・検証器の異常）は「未判定」とし、採用候補にしない。
- 調査では、26成果品の無効23,388件のうち23,342件が(a)〜(e)を満たし、46件が(c)だけ満たさなかった［実測。調査PoCでの判定であり、製品の検証器による判定ではない］。

### 10.3 解釈不一致（条件(c)の不成立）の扱い

- (c)を満たさないPolygon（調査では46件）は、**派生形状の自動採用の対象外**とする。Featureは保持し、初期状態は判定保留とする。
- 解釈不一致の原因（外周と同じ向きの穴等）、対象のリング、解釈が異なる領域を評価成果物に記録する。
- **GeoJSONのリング構造や偶奇規則を、OWNER判断なしに他の解釈より優先してはならない**（ON-17）。
- **2つの不確実性を区別する**:
  - (1) **原典の解釈そのものの不確実性**: 作成者がどの領域を浸水区域としたかが原典から決まらないこと。条件(a)〜(e)を満たしても残る。
  - (2) **数学的に異なる解釈の領域**: 3つの解釈規則で内外が異なる点の集合。条件(c)の解析で厳密に特定できる。
- 判定保留の範囲（unknownの範囲）の設計は、Integration契約 第4.4節で定める。精密な範囲（レベル2）は、検証と承認が成立するまで使わない。

### 10.4 派生成果物と来歴［提案］

派生形状は、原典のNormalize成果物とは別の成果物とする。

```text
work/derived_geometry/<run_id>/
  summary.json            件数（候補・不成立・未判定）、方式、依存の版
  derived.ndjson          派生形状1件＝1行
```

`derived.ndjson` の1行の必須項目:

| 項目 | 内容 |
|---|---|
| `source` | 原典Featureの `key`、`polygon_index`、`source_geometry_sha256` |
| `derived_geometry` | 派生形状（整数座標）と `derived_geometry_sha256` |
| `method` | 派生方法（C-3）・設定・処理版。比較に使った `make_valid` の方式と結果のハッシュ |
| `dependencies` | Python・Shapely・GEOS等の版 |
| `classification` | 評価成果物の分類（第9.4節）と、その行の参照 |
| `conditions` | (a)〜(e)の判定結果と根拠（(c)の領域の比較結果、(d)の一致結果、(e)の照合結果） |
| `status` | `eligible`（(a)〜(e)を満たす）／`not_eligible`／`undetermined` |

- **派生形状を作れることと、採用されることは別である**。`eligible` は採用の承認ではない。
- 同じ形状であっても、異なる原典Feature・浸水深ランク・来歴を統合して消してはならない（派生形状は原典Feature・Polygonごとに1行）。
- 原典 → 派生形状（`key`・`polygon_index` による検索）、派生形状 → 原典（`source`）の双方向の追跡を可能にする。

### 10.5 Derived Geometry Validate Record（独立検証）［提案］

派生成果物の作成とは別の検証器で、次を全件検証する。

- 派生形状の参照する原典が存在すること
- ハッシュが一致すること
- 条件(a)〜(e)を再計算して一致すること
- `eligible` 以外が判定に使われる設定になっていないこと

| 項目 | 内容 |
|---|---|
| `target` | 派生成果物の内容ハッシュ、作成工程のRecordの参照と `record_sha256` |
| `inputs` | Normalize成果物の `content_sha256`、評価成果物の内容ハッシュと Geometry Validity Assessment Recordの `record_sha256` |
| `validator` | 検証器のID・版、依存の版（作成工程と独立であること） |
| `policy` | 適用した**派生形状の利用ポリシー**のID・版（第10.6節） |
| `results` | 件数（eligible・not_eligible・undetermined）、再計算の不一致の件数（0であること） |
| `record_sha256` | 実行証跡ハッシュ |

### 10.6 派生形状の利用ポリシーと採用の条件［未決定: ON-15・ON-16］

派生形状を判定に使うには、次のすべてが必要である。

1. **派生形状の利用ポリシー**（ID・版付き）がOWNERに承認されている。ポリシーには、対象とする分類（例: 条件(a)〜(e)を満たす頂点同士の接触だけの形）、条件の最終要件、公開時の加工表示を定める。
2. Derived Geometry Validate RecordがPASSで、その `policy` が承認されたポリシーと一致する。
3. OWNERの承認記録への参照がある（承認の範囲に、対象の成果物・ポリシーの版が含まれる）。

### 10.7 状態の連鎖（後続の成功とみなさない）

次の各段階は独立した合格条件であり、**いずれかの成功を後続の成功とみなしてはならない**。

| 段階 | 証跡 | これだけでは意味しないこと |
|---|---|---|
| 1. 原典保持に成功 | Normalize Record、Source Fidelity Validate Record（PASS） | 形状が有効であること |
| 2. 形状の位相妥当性検査に合格（`valid`） | Geometry Validity Assessment（Polygonの状態） | 浸水区域の評価範囲が分かること |
| 3. 無効形状の分類に成功（`invalid_classified`） | 評価成果物 | 派生形状を作れること |
| 4. 派生形状の生成に成功 | 派生成果物 | 条件(a)〜(e)を満たすこと |
| 5. 派生形状の独立検証に合格（`eligible`） | Derived Geometry Validate Record | 採用されたこと |
| 6. 派生形状の採用承認が成立 | 承認された利用ポリシー＋OWNER承認記録 | 統合・公開ができること |
| 7. 統合・公開資格が成立 | Integrated Validate・公開の承認（既存契約） | 原典作成者の意図との一致 |

## 11. 来歴と再生成性［提案］（旧第9章）

### 11.1 内容ハッシュ（再生成性の判定に使う）

**内容ハッシュと実行証跡ハッシュを分ける。** 再生成性は内容ハッシュで判定する。

- 内容ハッシュの対象: `content.json` と `members/*.ndjson` の全バイト列。`content.json` は実行固有値（run_id、日時、パス）を含まない（第4.2節）。評価成果物（第9.5節）・派生成果物（第10.4節）も、それぞれ同じ規則で内容ハッシュを持つ。
- `content_sha256` ＝ `content.json` の正規化バイト列のSHA-256（`content.json` は各出力ファイルのSHA-256を含むので、成果物全体の内容を表す）。
- **決定的なシリアライズ規則**（`content.json`・NDJSON・`source_geometry_sha256`・評価成果物・派生成果物の対象に共通）:
  1. UTF-8、BOMなし。
  2. 改行はLF。NDJSONは1レコード1行で、最終行の後にも改行を置く。`content.json` は1行の正規化JSONとし、末尾に改行を1つ置く。
  3. オブジェクトのキーは、本書で定めた順序（レコード: `key`・`product_id`・`source_properties`・`derived`・`geometry`・`source_geometry_sha256`）、それ以外はUnicodeコードポイントの昇順。`source_properties` は原典の出現順を保つ配列。
  4. 区切りは `,` と `:`（空白なし）。
  5. 文字列のエスケープ: `"`・`\`・制御文字（U+0000〜U+001F）だけをエスケープし（`\"`・`\\`・`\b`・`\f`・`\n`・`\r`・`\t`、その他は小文字16進の `\u00xx`）、他の文字（非ASCIIを含む）はUTF-8のまま出力する。
  6. 数値: 出力に浮動小数を含めない。整数は10進、符号は負の場合のみ、先頭のゼロなし。原典の数値は `token`（文字列）で保持する。
  7. 入力の重複キーは拒否する（出力に重複キーは生じない）。
- 原典geometryの正規化表現（`source_geometry_sha256` の対象）: `{"type":…,"coordinates":…}` を上記の規則で、座標を整数として表現したもの。派生形状の `derived_geometry_sha256` も同じ規則による。

### 11.2 実行証跡ハッシュ

Normalize Record・Source Fidelity Validate Record・Geometry Validity Assessment Record・Derived Geometry Validate Recordは、run_id・日時・参照パスを含む実行証跡であり、それぞれの `record_sha256` は再実行で一致しない（一致を要件としない）。

### 11.3 再生成の要件と来歴

- 同じ原典ZIP・対象メンバー集合・処理版・設定の内容から、**同じ `content_sha256`（バイト単位で同一の内容）**を生成することを要件とする。評価成果物・派生成果物も、同じ入力・検証器の版・設定から同じ内容ハッシュを生成することを要件とする。テストで確認する（第13章 N-03・N-22）。
- 来歴の連鎖は次のとおり。各Recordは、前段の成果物の内容ハッシュとRecordのハッシュを持つ。
  1. Acquisition Record（原典ZIPのSHA-256）
  2. Normalize Record（処理版・設定・`content_sha256`）
  3. Source Fidelity Validate Record（対象の `content_sha256`）
  4. Geometry Validity Assessment Record（対象の `content_sha256`・評価成果物の内容ハッシュ）
  5. 派生成果物・Derived Geometry Validate Record（利用する場合）

## 12. 既存契約との整合（旧第10章）

| 既存契約 | 本書の扱い | 矛盾・差異 |
|---|---|---|
| Pipeline Execution Contract（data-publish §4） | そのまま適用 | なし |
| API別データ領域（基本アーキテクチャ §6.4、FIXED） | `/data/flood/` の `dl`・`work`・`records` を使う | 保存層の書込み許可領域の追加が必要（標高と同様）。`dl/current/` 配下を取得IDで分ける点は、既存の「元DL原則現行1世代」との関係を整理する必要がある［未決定］ |
| Acquisition Record（データソース定義 §7） | 1つの原典ZIP＝1取得実体として適用 | 既存の項目「tile」は標高用。ZIP用の項目（ZIP名・メンバー一覧）が必要［未決定: 契約の追加］ |
| Source Definition（データソース定義 §3） | `api/flood/conf/sources.json` に取得設定・資源上限・地域の規則を置く | 既存のSchemaは標高（`xyz_png`）用。flood用のSchemaが必要［未決定］ |
| 開始時設定の固定（基本アーキテクチャ §6.2、FIXED） | 設定スナップショットを各Recordに固定 | なし |
| 本番実行認可（production-authorization） | Flood用の認可プロファイルが成立するまで実データの処理はBLOCKED | 既存の承認記録はタイル単位。Flood用の追加設計が必要［未決定］ |
| Dataset Registry | Normalize成果物・評価成果物・派生成果物は公開Registryに登録しない | なし |
| 標高（Elevation）の各契約 | 変更しない | なし（flood固有の工程は `api/flood` の領域に閉じる） |

既存の文書は本書では改訂しない。

## 13. テストケース（設計のみ。いずれも実行していない）（旧第11章）

「期待」は将来の検証目標であり、成功を確認したものではない。

| ID | 入力 | 期待 |
|---|---|---|
| N-01 | 東京都ZIP（`_13_10`） | SUCCESS予定。成果品7件、Feature数・ランク分布がPhase 2-A.1の報告値と一致 |
| N-02 | 関東地方整備局ZIP | **SUCCESSは将来の検証目標**（48成果品のうち、調査で解析したのは11成果品だけ［実測］） |
| N-03 | 同じ入力で2回実行 | `content_sha256` と全出力のSHA-256が一致（`record_sha256` は一致しなくてよい） |
| N-04 | ランクが文字列の原典と整数の原典 | どちらも `derived.rank` は整数、`source_properties` に原典の型とトークン |
| N-05 | 同一成果品でランクの型が混在する合成データ | FAILED |
| N-06 | 小数10桁の座標・指数表記の座標 | FAILED |
| N-07 | null geometry・NaN・座標配列の構造の破損 | それぞれFAILED |
| N-08 | ランク0・7・null | FAILED |
| N-09 | 正規化後に重複するZIPメンバー名・同じ `product_id` | FAILED |
| N-10 | JSONの重複キー | FAILED |
| N-11 | 資源上限を超える行長・頂点数・展開量 | FAILED（全体読込みへ切り替えない） |
| N-12 | 圧縮率は高いが小さいエントリ（N03の `.dbf` と同等） | 拒否されない |
| N-13 | 追加属性・null値の属性を含む合成データ | `source_properties` に型・nullが保持され、欠落と区別される |
| N-14 | 穴・MultiPolygonを含む合成データ | 構造を保持（V-5・V-6が一致） |
| N-15 | 出力ファイルを1バイト改変 | Source Fidelity Validate V-9でFAILED |
| N-16 | 別の成果物のSource Fidelity Validate合格記録を流用 | 後続工程で拒否（`target.content_sha256` の不一致） |
| N-17 | 確定済みの成果物への再書込み、同名ZIPの改版 | 上書きされず、新しい取得ID・run_idの領域になる |
| N-18 | N03のGMLにDOCTYPE（UTF-8以外の文字コード宣言を含む）を加えた合成データ | FAILED（解析しない） |
| N-19 | N03の外部 `xlink:href`・未解決参照・重複 `gml:id` | FAILED |
| N-20 | N03 GMLの座標軸 | 正規化レコードが（経度, 緯度）で、既知の地点（例: 千代田区の範囲）と一致 |
| N-21 | 第9.4節の各分類の合成データ（Phase 2-B.4の合成ケースY1〜Y8を含む）。閉じていないリング・3点のリングを含む | **Normalize・Source Fidelity ValidateはSUCCESS**（原典をそのまま保持）。Geometry Validity Assessmentで各分類が付く |
| N-22 | 同じNormalize成果物でAssessmentを2回実行 | 評価成果物の内容ハッシュが一致 |
| N-23 | 2つの検証器の判定が異なるように作った入力（検証器の模擬） | `validation_error`、AssessmentはFAILED |
| N-24 | 検証器が途中で異常終了・Polygonが1件欠落 | AssessmentはFAILED。後続は実行されない |
| N-25 | 無効形状のリングの順序・始点・向き | Normalize成果物で原典と同一（V-6） |
| N-26 | 外周と同じ向きの穴（島を含む型、Phase 2-B.4・B.5の46件と同型の合成データ） | `hole_same_orientation_as_shell` が記録され、派生形状は条件(c)不成立で `not_eligible` |
| N-27 | 条件(a)〜(e)を満たす頂点同士の自己接触（Phase 2-B.4の合成ケースY1・Y3） | `eligible`。ただし利用ポリシー未承認では判定に使われない |
| N-28 | 派生成果物の1件のハッシュを改変・原典への参照を削除 | Derived Geometry Validate FAILED |
| N-29 | ランダム地点では解釈の差を検出できない形（解釈が異なる領域が小さい形） | 条件(c)の厳密な比較で不成立を検出する |

## 14. 未決定事項とOWNER判断事項（旧第12章）

| No | 事項 | 選択肢・推奨 |
|---|---|---|
| ON-1 | Normalize成果物の単位と同一性 | 1原典ZIP＝1成果物、同一性はZIPハッシュ・メンバー集合・処理版・設定の内容ハッシュ（推奨） |
| ON-2 | 変換対象 | 採用シナリオ内の全Feature（推奨。他シナリオは対象外）／Source Definitionで列挙 |
| ON-3 | 正規化表現の形式 | NDJSON（成果品ごと、整数座標、型付き原典属性）（推奨） |
| ON-4 | 座標の単位 | 10⁻⁹度の整数（数値的に可逆。推奨）。原典の文字列表記は原典ZIPで保持 |
| ON-5 | 妥当性モデルと2つの検証器・版 | **実装前のブロッキング条件**。OGC準拠、整数の参照判定器＋GEOS（版固定）を第一候補 |
| ON-6 | 連続する重複頂点 | 許容して記録（推奨）／拒否 |
| ON-7 | 隔離の採用 | v0.1では採用しない（推奨。無効形状のFeatureも保持） |
| ON-8 | ZIP用のAcquisition Record・flood用Source DefinitionのSchema | 既存契約への追加案を別途作成する |
| ON-9 | `source_ref` の命名、`dl/current/` の世代と取得IDの関係 | 未決定 |
| ON-10 | 処理ID・版の採番 | 未決定（実在のIDを本書では定めない） |
| ON-11 | JGD2011とWGS84、API入力の桁数、格子外の地点の表現 | Flood API契約で決定。未決定のまま地点を丸めない |
| ON-12 | 同一成果品内のランクの型の混在 | 拒否（推奨）／保持して許容 |
| ON-13 | 資源上限の値 | 観測値に余裕を持たせた初期値を、テストで確定 |
| ON-14 | Flood用の認可プロファイル | 成立まで実データ処理はBLOCKED |
| ON-15 | 派生形状の利用ポリシーの正式採用 | **未承認**。承認まで無効形状はすべて判定保留 |
| ON-16 | 条件(a)〜(e)の最終要件 | 本書の(a)〜(e)を候補とする。製品の検証器での再判定が必要 |
| ON-17 | 解釈不一致（条件(c)不成立）の型の扱い | 判定保留（推奨。自動採用しない）。GeoJSONの構造・偶奇規則を優先するかはOWNER判断 |
| ON-18 | 整数の参照判定器・C-3・条件(c)の判定方法の独立監査 | 実装前に実施（推奨） |
| ON-19 | 原典の作成者への照会 | 島を含む穴の向き、自己接触の記述方法が論点 |
| ON-20 | 派生形状を使った場合の公開時の加工表示 | 未決定 |
| ON-21 | N03に無効形状がある場合の扱い | 東京都本土は全件有効［実測］。他地域の追加時に決める |

本書の採用は、Normalizeの実装・実データの処理・派生形状の製品採用・公開・性能試験の承認ではない。
