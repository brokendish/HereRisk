# 洪水診断の提示契約（Stage 3案）

- 状態: **設計案（未承認・未実装）**。Location API v0.1 には追加していない。
- 前提: Phase 4-E のShadow統合と分類（`flood-diagnosis-adoption-v1`）。

## 1. 目的

無効Polygonのために `unknown` となる地点について、将来、診断上の解釈を利用者へ示す場合の形を決める。正常なPolygonに由来する `zones`（原典の正式な区域）と、診断に由来する解釈を、API利用者が取り違えないことを必須とする。

## 2. 提示の条件（すべて必要）

1. OWNERが提示を承認していること（派生形状の扱い: Normalize契約 ON-15・ON-16 の判断を含む）。
2. 分類が `candidate` であること。`undetermined`・`rejected` は提示しない。
3. 分類規則の版、診断索引、flood索引が、承認時の組み合わせと一致すること。
4. 承認時に決めた検証（対照の不一致0件、`make_valid` との一致、半径による反転0件など）を、提示するデータの版で通過していること。

## 3. 形（案）

正式な `zones`・`results`・`status` は変えない。診断の解釈は、ソースごとの独立した配列 `interpretations` にだけ入れる。

```json
{
  "source_id": "local-a31a-2025-83",
  "zones": [],
  "unknowns": [{"zone_ref": "loc-zn-…", "reason": "invalid_geometry", "unknown_level": "L1"}],
  "interpretations": [
    {
      "interpretation_status": "candidate",
      "interpretation_method": "local-contour-winding-v1",
      "adoption_version": "flood-diagnosis-adoption-v1",
      "zone_ref": "loc-zn-…",
      "relation": "inside",
      "depth_class": {"class_code": "3", "label": "3.0～5.0m未満"},
      "certainty": "diagnostic_only",
      "notice": "原典の形状に不整合があるため、正式な区域としては判定できません。参考の解釈です。"
    }
  ]
}
```

## 4. 規則

- `interpretations` の各要素は、同じソースの `unknowns` にある `zone_ref` に限る。診断索引から構成を追加しない。
- `relation` が `outside` の解釈は、区域がないことの表明ではない（`no_match` にしない）。
- `status` は正式な判定のまま（`unknown` を `available` にしない）。代表値・最大値の算出、ソース間の統合・優先順位付けはしない。
- `certainty` は常に `diagnostic_only`。`depth_class` は原典のランクをそのまま示し、確定した浸水深として扱わない。
- 画面では、正式な区域と見た目でも区別し、注記を必ず添える。

## 5. 未決定事項（OWNER判断）

1. 提示するかどうか。提示する場合の対象ソース・地域。
2. `defect_within_max_radius`（Phase 4-D のB 521組）を、追加の検証規則で `candidate` にできるか。
3. `no_local_boundary`（最大半径内に輪郭がない。全体の約46%）に、遠方の回転数だけによる解釈を認めるか。
4. 検証を通過した診断索引を、Dataset Registryの世代として管理する方法。
