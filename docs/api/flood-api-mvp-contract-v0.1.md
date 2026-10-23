# Flood API MVP Contract v0.1（案）

- Task: Phase 2-B.9 Flood API MVP Scope / Source Priority & Risk Aggregation Contract
- 状態: **契約案（OWNERレビュー待ち。正式採用されていない）**。本書は製品実装・正式なレスポンスSchema・実データの公開の承認ではない
- 作成: 2026-10-24（Claude）
- 基準コミット: `a701921540e4cf1e109b8932fcac2de1777d0870`
- 前提: [共通API契約 v0.1](common-contract-v0.1.md)、[Flood Source Priority & Risk Aggregation Contract v0.1（案）](../architecture/flood-source-priority-contract-v0.1.md)、[Flood Integration Contract v0.1（案）](../architecture/flood-integration-contract-v0.1.md)
- 検討の記録: [Phase 2-B.9 レビュー](../../reviews/phase2/phase2b9-flood-mvp-scope-and-priority.md)

区分: **［確定］** 既存の承認済み契約に由来、**［実測］** 調査で報告された値、**［提案］** 本書の設計提案（未承認）、**［未決定］** OWNER判断が必要。**フィールド名・型・列挙値・JSON例はすべてPROVISIONAL（暫定）であり、正式Schemaではない**（共通API契約 §1と同じ扱い）。

## 1. 目的

指定した1地点について、A31a（想定最大規模）の浸水想定区域への該当と浸水深区分を返す。複数の浸水想定が重なる場合は、承認済みのSource Priority Policyで代表結果を選ぶ。そのうえで、採用元・選択理由・他の該当・unknownを隠さずに返す。

設計原則: **内部は厳密に。外部はシンプルに。不確実性は隠さない。**

## 2. MVPの範囲

### 2.1 含めるもの［提案］

| 機能 | 本書の箇所 |
|---|---|
| 緯度・経度を指定した1地点のFlood判定 | 第3章 |
| 有効なA31a形状による浸水区域の該当判定 | 第4章（Point Assessment） |
| 浸水深区分の取得 | 第5.4節 |
| 提供主体の優先順位による代表結果の選択 | 第5.3節（Source Priority契約 第7章） |
| 採用した提供主体と具体的なデータソースの識別 | 第5.3節 |
| 採用理由の説明 | 第5.3節 `selection_reason` |
| 同じ順位の複数該当の集約 | Source Priority契約 第8章 |
| すべての該当ソースへの来歴参照 | 第5.5節 `matches` |
| 判定保留・unknownの通知 | 第5.5節 `unknowns` |
| 複数の浸水想定が共存することの表現 | 第5.5節 |
| 適用ポリシーのID・版・内容ハッシュの参照 | 第6章 |

### 2.2 含めないもの

- 無効ポリゴンの自動修復・派生形状の製品利用（Normalize契約 第10章。BLOCKED）
- unknownのL2（精密な範囲）への縮小（Integration契約 第4.4節。禁止）。**unknownの範囲はL1だけを使う**
- 避難経路の探索
- 複数地点・面の一括判定
- 地図タイルの生成（Layer Presentationとの接続条件だけをSource Priority契約 第9章に記す）
- 管理画面そのものの実装
- データソースの優先順位の無承認での即時変更
- 実データの公開（Flood用の認可プロファイル・利用条件が未成立。Integration契約 第9.5節）

## 3. 入力［提案］

| パラメータ | 必須 | 内容 |
|---|---|---|
| `lat` | ○ | 緯度（十進度） |
| `lon` | ○ | 経度（十進度） |

- **名前**: 指示書は `latitude`・`longitude` を例示している。一方、共通API契約 §2は `lat`・`lon` を入力とする。本書は共通API契約に合わせて `lat`・`lon` を提案し、名前の最終決定をOWNER判断とする（FA-C1）。
- **検証**: 共通API契約 §2に従う。欠落・`null`・非数値・非有限値・範囲外（lat −90〜90、lon −180〜180）を有効な地点として処理しない。latとlonを暗黙に交換しない。重複したパラメータは拒否する。
- **座標系・精度**: 原典はJGD2011（EPSG:6668）。API入力（WGS84想定）との扱い、受け付ける桁数、nano-degreeの格子に乗らない地点の扱いは未決定である（Normalize契約 ON-11、Integration契約 OI-18）。**未決定のまま地点を丸めない。** 最終の点の判定には丸めない入力地点を使う（Integration契約 第6.3節）。
- **任意パラメータ**: MVPでは**受け付けない**。未知のパラメータは入力エラーとする。理由は次のとおり。
  - ポリシー・優先順位・データソースの指定は、未承認の規則で本番の判定を変える経路になる（Source Priority契約 第5.4節で禁止）。`policy`・`priority`・`source` 等の名前のパラメータは、未知のパラメータとして拒否する。
  - 詳細の有無の切替え（例: `detail=summary`）は、不確実性を隠す使い方を招く。MVPでは常に全情報を返す。
  - 将来追加する場合は、必要性・入力検証・応答の意味の変化・キャッシュのキー・セキュリティ（列挙攻撃・負荷）を評価し、API契約の版を上げる。

## 4. 処理の3段階［提案］

| 段階 | 内容 | 正本 |
|---|---|---|
| A. Point Assessment | 公開世代の統合成果物で、地点と全ソースの判定用の構成Polygon（`search_target`）・unknownの範囲（`unknown_region`、L1）・地域（`region_polygon`）の関係を判定する。優先順位を参照しない | Source Priority契約 第6.1節 |
| B. Source Priority Resolution | 承認済みのポリシーで代表の区分・ソースを選ぶ | Source Priority契約 第7章 |
| C. Risk Aggregation / Response | 同順位の集約、全該当・unknown・境界接触・ソースごとの状態の整理、公開用の表現への変換 | Source Priority契約 第8章、本書 第5章 |

- APIは公開済みのRegistry・公開実体だけを読む［確定: 共通API契約 §5］。`work/` 領域、未公開の候補を読まない。
- 1つの応答では1つの公開世代だけを使う（Source Priority契約 第5.3節）。

## 5. 出力［提案］

### 5.1 全体の構成

共通API契約 §3の6フィールド（`hazard`・`location`・`status`・`result`・`dataset`・`error`）と `evaluated_at` に、`policy` を加える。

```json
{
  "hazard": "flood",
  "location": {"lat": 35.68, "lon": 139.76},
  "status": "success",
  "result": {
    "assessment": "affected",
    "assessment_status": "partial_unknown",
    "region_state": "inside",
    "representative": {
      "finality": "provisional",
      "selection_reason": "higher_priority_uncertain",
      "source_category": "national_government",
      "priority": 2,
      "source_id": "example-national-maximum",
      "source_organization": "国土交通省 関東地方整備局",
      "depth": {"kind": "class", "scheme": "ksj-a31a-water-depth-rank", "class_code": "3",
                "label": "3.0～5.0m未満", "lower_m": 3.0, "upper_m": 5.0, "bounds_inclusion": "unspecified"},
      "contributing_zones": ["example-zone-ref-1"],
      "tie_break": null
    },
    "deeper_match_outside_representative": false,
    "has_unknown": true,
    "has_boundary_contact": false,
    "uncertainty_reasons": ["higher_priority_uncertain", "unknown_invalid_geometry"],
    "category_states": [
      {"priority": 1, "source_category": "local_government", "state": "unknown"},
      {"priority": 2, "source_category": "national_government", "state": "confirmed_match"},
      {"priority": 3, "source_category": "other", "state": "not_registered"}
    ],
    "matches": [
      {"zone_ref": "example-zone-ref-1", "source_id": "example-national-maximum",
       "source_category": "national_government", "priority": 2,
       "source_organization": "国土交通省 関東地方整備局",
       "river_name_in_source": "荒川",
       "depth": {"kind": "class", "scheme": "ksj-a31a-water-depth-rank", "class_code": "3",
                 "label": "3.0～5.0m未満", "lower_m": 3.0, "upper_m": 5.0, "bounds_inclusion": "unspecified"},
       "is_representative": true}
    ],
    "unknowns": [
      {"zone_ref": "example-zone-ref-2", "source_id": "example-local-maximum",
       "source_category": "local_government", "priority": 1,
       "source_organization": "東京都",
       "reason": "invalid_geometry", "unknown_level": "L1"}
    ],
    "boundary_contacts": []
  },
  "dataset": {"id": "example-flood", "publication_version": "example-v1",
              "published_at": "2026-10-01T00:00:00Z",
              "attribution": [{"text": "<利用条件が求める出典・加工の表示>"}]},
  "policy": {
    "source_priority": {"id": "flood-source-priority", "version": "v1", "content_sha256": "<…>"},
    "source_category_assignment": {"id": "<…>", "version": "<…>", "content_sha256": "<…>"},
    "unknown_region": {"id": "<…>", "version": "<…>", "content_sha256": "<…>"}
  },
  "error": null,
  "evaluated_at": "2026-10-24T00:00:00Z"
}
```

値はすべて架空である。実在の地点の浸水想定・データの識別子・承認済みのポリシーを示さない。

### 5.2 `assessment_status`（列挙値の案）

`result.assessment_status` は、地点の判定の状態を1つの列挙値で表す。**有効な該当の有無と、不確実性の有無の組合せ**で決まる。

| 値 | 確認済みの該当 | 不確実性（unknown・境界接触・評価できないソース・未分類・集約不能・地域の外縁） | 意味 |
|---|---|---|---|
| `determined_match` | あり | なし | 代表結果が確定している |
| `partial_unknown` | あり | あり | 代表結果はあるが、他の情報で変わりうる、または追加の浸水想定の可能性がある |
| `aggregation_undetermined` | あり | （集約不能） | 該当はあるが、同順位の区分が比較できず、代表の浸水深を決められない |
| `unknown_only` | なし | あり | 判定保留・境界接触だけがある。**浸水なしではない** |
| `no_match_extent_unknown` | なし | なし（地域の内部） | 判定に使える区域にもunknownにも該当しない。**A31aは評価済み範囲を持たないため、「浸水なし」「区域外」と確定しない** |

- `aggregation_undetermined` でunknownもある場合も、`assessment_status` は `aggregation_undetermined` とする。unknownは `has_unknown`・`unknowns` で示す。
- 評価済みの区域外であることを表す値（共通API契約の `not_affected`、Integration契約の `outside_inundation_zone`）は、**MVPでは使わない**。A31aだけでは成立しない（Integration契約 第10章）。

`result.assessment`（共通API契約 §4.2の該当性）との対応:

| `assessment_status` | `assessment` |
|---|---|
| `determined_match`・`partial_unknown`・`aggregation_undetermined` | `affected` |
| `unknown_only`・`no_match_extent_unknown` | `undetermined`（新しい値の提案。`not_affected` にしない。FA-C2） |

### 5.3 代表結果（`representative`）

| 項目 | 内容 |
|---|---|
| `finality` | `final` または `provisional`（Source Priority契約 第7.3節の手順6）。地域の外縁上（第5.6節）も `provisional` |
| `selection_reason` | 列挙値（Source Priority契約 第7.5節）: `highest_priority_confirmed_match`・`no_higher_priority_confirmed_match`・`higher_priority_uncertain`・`aggregation_undetermined` |
| `source_category`・`priority` | 採用区分と、その優先順位 |
| `source_id`・`source_organization` | 採用したソースの公開用の識別子と提供主体名。タイの場合は `primary` のソース（`tie_break` 参照） |
| `depth` | 代表の浸水深区分（第5.4節）。`aggregation_undetermined` の場合は `null` |
| `contributing_zones` | 代表の浸水深に寄与した全区域の `zone_ref`（タイの全件） |
| `tie_break` | タイがない場合は `null`。ある場合は `deterministic_order`（`primary` が決定的な順序で選ばれたことを示す） |

- 確認済みの該当がない場合、`representative` は `null` とする。その場合の理由は `result.selection_reason = no_confirmed_match` で示す（`representative` の外に置く）。
- 説明の文言（例: 「上位の提供主体の情報に判定保留があるため、国土交通省のデータを暫定の代表としています」）は、列挙値から生成する。自由記述の説明を判定の根拠にしない。

### 5.4 浸水深区分（`depth`）

共通API契約 §4.2の候補（`kind`・`category`・`lower_m`・`upper_m`）に沿う。

| 項目 | 内容 |
|---|---|
| `kind` | `class`（階級）。数値の浸水深ではない |
| `scheme` | 区分の体系のID（例: `ksj-a31a-water-depth-rank`） |
| `class_code` | 原典のコード（文字列に正規化） |
| `label` | 原典の定義の文言 |
| `lower_m`・`upper_m` | 区間の下限・上限。上限なし（コード6）は `null` |
| `bounds_inclusion` | `unspecified`（A31aでは端点の包含が原典で未規定） |

- 浸水深ランクは実測の浸水深や推定値ではない。範囲・階級から架空の代表値（中央値等）を作らない［確定: 共通API契約 §4.2］。
- 指示書の例の `depth_range_m: {min, max}` は、本書では `lower_m`・`upper_m` に置き換えた（共通API契約の候補に合わせたため）。

### 5.5 全該当・unknown・境界接触

| 項目 | 内容 |
|---|---|
| `matches[]` | 確認済みの該当の全件（全区分）。`zone_ref`・`source_id`・`source_category`・`priority`・`source_organization`・`river_name_in_source`（成果品の代表河川名。個別の区域の原因河川ではない［実測］）・`depth`・`is_representative` |
| `unknowns[]` | unknownの範囲（L1）に地点が入る全件（全区分）。`zone_ref`・`source_id`・`source_category`・`priority`・`reason`（`invalid_geometry`・`feature_invalid_component`）・`unknown_level`（`L1`） |
| `boundary_contacts[]` | 判定用の構成Polygonの境界上にある全件 |
| `category_states[]` | 区分ごとの状態（Source Priority契約 第7.2節の値） |
| `has_unknown`・`has_boundary_contact` | 上の一覧が空でないか |
| `deeper_match_outside_representative` | 代表より深い区分の確認済みの該当が、代表以外にあるか。比較不能を含む場合は `null` |
| `uncertainty_reasons[]` | 不確実性の理由の列挙値（重複なし・昇順）: `assessed_extent_unknown`・`unknown_invalid_geometry`・`zone_boundary_contact`・`higher_priority_uncertain`・`same_priority_uncertain`・`unclassified_source`・`aggregation_undetermined`・`region_boundary` |

- `matches`・`unknowns`・`boundary_contacts` の並び順は、`priority` → `source_id` → `zone_ref` の昇順で決定的とする。
- **件数の上限で黙って切り捨てない。** 応答の大きさの上限を設ける場合は、上限を超えたことを `truncated` と全件数で示す（上限値は［未決定: FA-U7］）。調査では最大6成果品の重なりが観測されている［実測: Phase 2-A.4の標本］。
- **同じFeatureの有効部分の該当とunknown**（Integration契約 `has_area_match`・`has_unknown`）は、`matches` と `unknowns` の両方に同じFeatureの区域として現れうる。どちらも削除しない。
- `zone_ref` は公開用の不透明な識別子とする。内部の `record_key` は原典のZIPメンバー名（ファイル名）を含むため、そのまま公開しない（共通API契約 §5）。`zone_ref` は公開世代の中で安定し、内部で `record_key`・`polygon_index` へ戻せること。生成規則は［未決定: FA-U6］。
- unknownの区域の原典のランクを「該当した場合の可能性」として返すかは未決定である（FA-U5。Source Priority契約 SP-C6）。MVPの案では返さない。

### 5.6 地域外・地域の外縁上

| `region_state` | 扱い |
|---|---|
| `inside` | 第5.2節のとおり判定する |
| `region_boundary`（対象地域の外縁上） | 判定は行い、`uncertainty_reasons` に `region_boundary` を加える。代表は `provisional`。統合成果物は地域と接するだけのFeatureを保持しないため（Integration契約 第4.1節）、外縁上の地点では情報が不完全でありうる |
| `outside` | 判定しない。`status = no_data`、`error.code = outside_service_region` |

`not_covered`（地域外）、`unknown`（評価範囲が不明・判定保留）、`outside_inundation_zone`（評価済みの区域外。MVPでは使わない）を混同しない（Integration契約 第10章）。

### 5.7 共通の `status` との関係・エラーと正常な判定不能の区別

**正常な判定不能（unknown・評価範囲不明・集約不能・地域の外縁）は、エラーではない。** `status = success` とし、内容を `result` に入れる。エラー（取得失敗・整合性の異常・入力の不正）は `result = null` とし、`status` と `error` で返す。

| 状況 | `status` | `result` | `error.code`（案） |
|---|---|---|---|
| 第5.2節のいずれか（地域の内部・外縁上） | `success` | あり | `null` |
| 地点が対象地域の外 | `no_data` | `null` | `outside_service_region` |
| Floodの公開データがない（未公開） | `no_data` | `null` | `flood_not_published` |
| 公開停止（公開Registryにfloodのデータセットがない状態に戻された） | `no_data` | `null` | `flood_not_published`（公開停止と未公開を公開応答で区別するかは［未決定: FA-U8］） |
| 公開Registry・公開実体の読取り失敗 | `retrieval_failed` | `null` | `flood_read_failed` |
| 公開世代の不整合（ポリシー・地域形状の内容ハッシュの不一致、参照の欠落） | `indeterminate` | `null` | `flood_integrity_error` |
| 点の判定器の判定保留（有効な形状。Integration契約 第4.1節では統合時にFAILEDとなるため、通常は発生しない） | `indeterminate` | `null` | `flood_point_undecided` |
| 入力の不正（欠落・非数値・範囲外・未知のパラメータ・重複） | 入力エラー（`invalid_input` の追加を提案。FA-C4） | `null` | `invalid_coordinates`・`unknown_parameter` 等 |

- HTTPステータスとの対応は［未決定］（共通API契約 §10と同じ）。正常な判定不能に、エラーのHTTPステータスを使わないことを提案する。
- `no_data`・`retrieval_failed`・`indeterminate`・入力エラーのいずれも、非該当・浸水深0mに変換しない［確定: 共通API契約 §3.1］。
- `error.message` は公開用の説明とし、内部の例外の文字列・パスを含めない［確定: 共通API契約 §5］。

## 6. データ・ポリシーの世代の追跡［提案］

| 項目 | 内容 |
|---|---|
| `dataset.id`・`dataset.publication_version`・`dataset.published_at` | 公開Registryの識別・版（共通API契約 §5） |
| `dataset.attribution` | 利用条件が求める出典・加工の表示（A31a・N03。文言は［未決定: Integration契約 OI-10］） |
| `policy.source_priority` | 使ったSource Priority PolicyのID・版・内容ハッシュ |
| `policy.source_category_assignment` | 使った区分の割当記録のID・版・内容ハッシュ |
| `policy.unknown_region` | 使ったunknownポリシーのID・版・内容ハッシュ（Integration契約 第3.1節） |
| `evaluated_at` | 評価時刻（データの基準日・公開日とは別） |

- これらはすべて同じ公開世代に属する（Source Priority契約 第5.3節）。応答の中で世代を混在させない［確定: 共通API契約 §5］。
- 内部の `run_id`・ファイルパス・統合成果物のファイル名・承認記録の内部参照は公開しない。

## 7. ケース別のレスポンス（すべて架空・暫定）

以下は `result` の要点だけを示す（他のフィールドは第5.1節と同じ形）。

### 7.1 優先1・優先2の両方に確認済みの該当（ケース1）

```json
{"assessment": "affected", "assessment_status": "determined_match", "region_state": "inside",
 "representative": {"finality": "final", "selection_reason": "highest_priority_confirmed_match",
                    "source_category": "local_government", "priority": 1, "source_id": "example-local-maximum",
                    "source_organization": "東京都",
                    "depth": {"kind": "class", "class_code": "1", "label": "0～0.5m未満", "lower_m": 0, "upper_m": 0.5, "bounds_inclusion": "unspecified"},
                    "contributing_zones": ["z-a"], "tie_break": null},
 "deeper_match_outside_representative": true,
 "has_unknown": false, "has_boundary_contact": false, "uncertainty_reasons": [],
 "category_states": [{"priority": 1, "source_category": "local_government", "state": "confirmed_match"},
                     {"priority": 2, "source_category": "national_government", "state": "confirmed_match"},
                     {"priority": 3, "source_category": "other", "state": "not_registered"}],
 "matches": [{"zone_ref": "z-a", "priority": 1, "depth": {"class_code": "1"}, "is_representative": true},
             {"zone_ref": "z-b", "priority": 2, "depth": {"class_code": "4"}, "is_representative": false}],
 "unknowns": [], "boundary_contacts": []}
```

代表は優先1（ランク1）だが、優先2のランク4の該当を保持し、`deeper_match_outside_representative = true` で示す。

### 7.2 優先1に該当なし・優先2に確認済みの該当（ケース2）

`assessment_status = determined_match`、`representative.selection_reason = no_higher_priority_confirmed_match`、`finality = final`。優先1の `category_states.state` は `no_polygon_extent_unknown`（評価範囲不明）であり、`not_registered`・非該当とは返さない。`uncertainty_reasons` には `assessed_extent_unknown` を入れない（代表の選択には影響しないため）。上位の区分が評価範囲不明であることは `category_states` で分かる。

### 7.3 優先1がunknown・優先2に確認済みの該当（ケース3）

第5.1節の例のとおり。`assessment_status = partial_unknown`、`selection_reason = higher_priority_uncertain`、`finality = provisional`。優先1のunknownは `unknowns` に残る。

### 7.4 全ソースで該当なし（ケース4）

```json
{"assessment": "undetermined", "assessment_status": "no_match_extent_unknown", "region_state": "inside",
 "representative": null, "selection_reason": "no_confirmed_match",
 "deeper_match_outside_representative": null,
 "has_unknown": false, "has_boundary_contact": false, "uncertainty_reasons": ["assessed_extent_unknown"],
 "category_states": [{"priority": 1, "source_category": "local_government", "state": "no_polygon_extent_unknown"},
                     {"priority": 2, "source_category": "national_government", "state": "no_polygon_extent_unknown"},
                     {"priority": 3, "source_category": "other", "state": "not_registered"}],
 "matches": [], "unknowns": [], "boundary_contacts": []}
```

「安全」「浸水なし」と返さない。説明の文言は「この地点は、登録されている浸水想定区域に該当しません。ただし、評価範囲が示されていないため、浸水しないことを意味しません」等の趣旨とする（文言は［未決定］）。

### 7.5 同じFeatureに有効な構成と判定保留の構成（ケース5）

`matches` に有効な構成Pの区域、`unknowns` に同じFeatureの判定保留の構成Qの区域が現れる。`has_unknown = true`。Qと同じ区分の該当を代表にした場合は `same_priority_uncertain` で `provisional`。

### 7.6 異なる区分の複数unknown（ケース6）

```json
{"assessment": "undetermined", "assessment_status": "unknown_only", "region_state": "inside",
 "representative": null, "selection_reason": "no_confirmed_match",
 "has_unknown": true, "uncertainty_reasons": ["unknown_invalid_geometry"],
 "category_states": [{"priority": 1, "source_category": "local_government", "state": "unknown"},
                     {"priority": 2, "source_category": "national_government", "state": "unknown"},
                     {"priority": 3, "source_category": "other", "state": "not_registered"}],
 "matches": [],
 "unknowns": [{"zone_ref": "z-c", "priority": 1, "reason": "invalid_geometry", "unknown_level": "L1"},
              {"zone_ref": "z-d", "priority": 2, "reason": "invalid_geometry", "unknown_level": "L1"}],
 "boundary_contacts": []}
```

低順位のunknownも削除しない。

### 7.7 同順位で集約不能

`assessment_status = aggregation_undetermined`、`representative.depth = null`、`representative.selection_reason = aggregation_undetermined`。採用区分・該当の全件は返す。A31aの単一の体系だけを扱うMVPでは、通常は発生しない（Source Priority契約 第8.3節）。

### 7.8 地域外・エラー

```json
{"hazard": "flood", "location": {"lat": 35.0, "lon": 135.0}, "status": "no_data", "result": null,
 "dataset": null, "policy": null,
 "error": {"code": "outside_service_region", "message": "この地点は、洪水の浸水想定を提供している対象地域の外です。"}}
```

## 8. 共通API契約との整合［既存契約は変更しない］

| No | 共通API契約 | 本書 | 論点 |
|---|---|---|---|
| FA-C1 | §2 入力は `lat`・`lon` | `lat`・`lon`（指示書の例は `latitude`・`longitude`） | 名前の最終決定 |
| FA-C2 | §3.1・§4.2 該当性は `affected`・`not_affected` | `affected`・`undetermined`（`not_affected` を使わない） | `undetermined` の追加。共通契約は列挙値を網羅的に確定していない |
| FA-C3 | §5「管理主体を公開レスポンスへ含めない」 | `source_organization`（提供主体名）を返す | 共通契約の「管理主体」はシステムの管理情報を指すと解釈した。原典の提供主体名は出典（`source.provider` の公開用要約）に当たり、利用条件の表示にも必要である。解釈の確認が必要 |
| FA-C4 | §2 入力エラーの形式は詳細設計 | `invalid_input` の追加を提案 | `status` の列挙への追加の可否 |
| FA-C5 | §3.1 `success` は「要求された取得・評価が成立」 | unknown・評価範囲不明でも `success` とし、`result.assessment_status` で区別 | 共通契約 §4.2は「部分結果のstatusは未決定」としている。本書の案（`success`＋`assessment_status`）と、新しい `status`（例: `partial`）の追加のどちらにするか |
| FA-C6 | §3 6フィールド。追加フィールドの規則は未決定 | `policy` を追加 | 追加フィールドの規則 |
| FA-C7 | §6 複数データセットの優先順位・集約は未決定。最大値等を独断で導入しない | Source Priority契約の規則（優先順位・同順位の最大区分） | **OWNERの承認があるまで提案**。承認前に導入したとは扱わない |
| FA-C8 | §5 位置情報をログに残さない | 同じ | — |

## 9. セキュリティ・プライバシー

- 位置情報（`lat`・`lon`・位置を含むURL・本文）を、アプリログ・アクセスログ・プロキシ・トレース・エラー収集に残さない［確定: 共通API契約 §5］。
- リクエストでポリシー・ソースを選ばせない（第3章）。
- 応答には内部パス・ファイル名・`run_id`・承認記録の内部参照・スタックトレースを含めない。
- 応答の大きさに上限を設ける場合も、黙って切り捨てない（第5.5節）。

## 10. 契約テストの受入条件（将来の実装時。いずれも実行していない）

| ID | 入力・状況 | 受入条件 |
|---|---|---|
| FA-01 | Source Priority契約 第7.6節のケース1〜9の合成データ | 第7章の各例のとおり |
| FA-02 | 全ソースで該当なし（地域の内部） | `no_match_extent_unknown`・`assessment = undetermined`。`not_affected`・浸水深0にならない |
| FA-03 | 優先1のunknownと優先2の確認済みの該当 | `partial_unknown`・`provisional`。unknownが残る |
| FA-04 | 同じFeatureの有効Pと判定保留Q | `matches` と `unknowns` の両方に現れる |
| FA-05 | 優先1がランク1、優先2がランク4 | 代表は優先1、`deeper_match_outside_representative = true`、優先2が `matches` に残る |
| FA-06 | 未知のパラメータ・`policy` パラメータ | 入力エラー。判定結果は返さない |
| FA-07 | 欠落・`null`・非数値・非有限値・範囲外・重複の `lat`/`lon` | 入力エラー。`no_data`・非該当に変換しない |
| FA-08 | 地域外・外縁上・内部の境界上 | `no_data`（`outside_service_region`）／`success`＋`region_boundary`＋`provisional`／`inside` |
| FA-09 | 公開データなし・公開停止 | `no_data`（`flood_not_published`） |
| FA-10 | 公開実体の読取り失敗・ポリシーの内容ハッシュの不一致 | `retrieval_failed`／`indeterminate`。正常結果を生成しない |
| FA-11 | 公開世代の切替え中の連続した要求 | 各応答の `dataset.publication_version` と `policy` の各ハッシュが同じ世代に対応し、混在しない |
| FA-12 | 応答の全体 | 内部パス・ファイル名・`record_key`・`run_id` を含まない |
| FA-13 | 正常・異常時のログ | 位置情報を含まない |
| FA-14 | 該当が上限を超える地点（合成データ） | 黙って切り捨てず、`truncated` と全件数を示す |
| FA-15 | 同じ地点・同じ世代で繰り返し要求 | 結果と並び順が同一 |

## 11. 未決定事項とOWNER判断事項

| No | 事項 | 本書の提案 |
|---|---|---|
| FA-U1 | Flood APIの正式なレスポンスSchema（型・必須性・null・省略） | 本書の構成を叩き台とする |
| FA-U2 | 代表と全ソース中の最大浸水深区分の併記（Source Priority契約 SP-U2） | `deeper_match_outside_representative` は返す。最大値の併記は判断待ち |
| FA-U3 | 共通契約との論点 FA-C1〜FA-C7 | 第8章 |
| FA-U4 | 説明文言（評価範囲不明・判定保留・暫定の代表） | 「安全」「浸水なし」と誤読されない文言。OWNERが確定 |
| FA-U5 | unknownの区域の原典ランクを可能性として返すか | MVPでは返さない |
| FA-U6 | `zone_ref` の生成規則 | 公開世代の中で安定し、内部の原典キーへ戻せる不透明な識別子 |
| FA-U7 | 応答の大きさの上限 | 黙って切り捨てない条件付きで設定 |
| FA-U8 | 公開停止と未公開の区別 | 公開応答では区別しない案（どちらも `flood_not_published`） |
| FA-U9 | API入力の座標系・精度・格子外の地点の扱い（Normalize契約 ON-11・Integration契約 OI-18） | 未決定のまま地点を丸めない |
| FA-U10 | APIパス・HTTPメソッド・HTTPステータス・API版の指定方式 | 共通API契約 §10と同じく未決定 |
| FA-U11 | 「洪水による浸水なし（内水のみ）」の成果品の表示（Integration契約 OI-16） | 未決定 |

本書の採用は、製品実装・正式Schema・実データの公開の承認ではない。
