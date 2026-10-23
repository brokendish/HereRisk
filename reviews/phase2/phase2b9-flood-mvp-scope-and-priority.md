# Phase 2-B.9 Flood API MVP Scope / Source Priority & Risk Aggregation 検討記録

- Task: Phase 2-B.9 Flood API MVP Scope / Source Priority & Risk Aggregation Contract
- 作成: 2026-10-24（Claude）
- 基準コミット: `a701921540e4cf1e109b8932fcac2de1777d0870`
- 成果物（新規）:
  - [Flood Source Priority & Risk Aggregation Contract v0.1（案）](../../docs/architecture/flood-source-priority-contract-v0.1.md)（以下「SP」）
  - [Flood API MVP Contract v0.1（案）](../../docs/api/flood-api-mvp-contract-v0.1.md)（以下「API」）
  - 本書
- 参照: [Normalize契約](../../docs/architecture/flood-normalize-contract-v0.1.md)（N）、[Integration契約](../../docs/architecture/flood-integration-contract-v0.1.md)（I）、[Phase 2-B.8 対応表](phase2b8-codex-audit-remediation.md)、[Phase 2-B.6 方針決定書](phase2b6-invalid-geometry-policy-decision.md)、[Phase 2-B.5 調査](phase2b5-remaining-invalid-geometry-survey.md)、[Phase 2-A.1 調査](phase2a1-a31a-source-investigation.md)、[共通API契約](../../docs/api/common-contract-v0.1.md)、[Dataset Registry](../../docs/architecture/dataset-registry-v0.1.md)、[Data Publish](../../docs/architecture/data-publish-v0.1.md)、[データソース定義](../../docs/architecture/data-source-definition-v0.1.md)、[本番実行認可](../../docs/architecture/production-authorization-v0.1.md)

本工程は**設計文書の作成だけ**である。製品コード・調査スクリプト・実データ・Registry実体・VPSを変更していない。新しいデータもダウンロードしていない。既存の契約（Normalize・Integration・共通API・Registry・Publish・Authorization）は変更していない。矛盾・不足は論点として記録した（第7章）。**本工程は、製品実装・契約の正式採用・ポリシーの承認・実データの公開の承認ではない。**

設計原則: **内部は厳密に。外部はシンプルに。不確実性は隠さない。**

## 1. MVPの対象・対象外

| 区分 | 項目 |
|---|---|
| **対象** | 緯度・経度の1地点のFlood判定。有効なA31a形状による浸水区域の該当判定。浸水深区分の取得。提供主体の優先順位による代表結果の選択。採用した提供主体と具体的なデータソースの識別。採用理由の説明（列挙値）。同順位の複数該当の集約。全該当ソースへの来歴参照。判定保留・unknownの通知。複数の浸水想定の共存の表現。適用ポリシーのID・版・内容ハッシュの参照 |
| **対象外** | 無効ポリゴンの自動修復・派生形状の製品利用（BLOCKED）。unknownのL2への縮小（禁止。L1だけ）。避難経路の探索。複数地点・面の一括判定。地図タイルの生成。管理画面の実装。優先順位の無承認での即時変更。実データの公開 |

詳細は API 第2章。

## 2. Source Priority Policyの設計

| 観点 | 設計（SP） |
|---|---|
| 位置付け | 代表結果の選択規則を、版付きの独立したポリシー文書として管理する（SP 第4章） |
| 必須項目 | `policy_id`・`version`・`content_sha256`・`source_category_order`・`same_priority_resolution`・`fallback_rule`・`unknown_handling`・`applies_to`・`approval_ref`・`effective_generation` |
| 初期値（提案） | 地方自治体（1）→ 国土交通省（2）→ その他（3）。**OWNERの承認まで提案値** |
| unknownの制約 | `unknown_handling` の「選択と独立」「全順位で保持」「上位・同順位のunknownがあれば代表を暫定にする」は変更不可。`false` にした版はPolicy Validateで拒否する |
| 固定 | 不変の保存先・内容ハッシュの再計算・承認の範囲の照合・期限・失効（I 第3.1節と同じ規則） |
| 変更の手順 | `draft` → `validated` → `approved`（OWNER）→ `active` → `superseded`。取消しは `withdrawn`（SP 第5.1節） |
| 有効化 | 同じ統合成果物を参照する**新しい公開世代**に、ポリシー・区分の割当記録・unknownポリシーを内容ハッシュで固定し、既存のPublishの原子的な切替えで有効化する。統合成果物は再生成しない（SP 第5.3節） |
| 混在の防止 | 1つの応答では1つの公開世代だけを使う。起動・切替時にポリシーの内容ハッシュを照合する。キャッシュのキーに世代を含める |
| 禁止 | リクエストでのポリシーの指定・上書き、未承認の版の使用、管理画面からの無承認の即時有効化、優先順位を理由とした原典・統合成果物の修正・削除（SP 第5.4節） |

## 3. 提供主体の分類

| 観点 | 設計（SP 第3章） |
|---|---|
| 識別子の分離 | `source_category`（区分）・`source_id`（データソース）・`product_id`（原典の成果品） |
| 東京都管理河川のA31a | `local_government`（`A31a_203` が都道府県コード 01〜47） |
| 関東地方整備局管理河川のA31a | `national_government`（`A31a_203` が地方整備局等のコード 81〜90） |
| `other` | 初期は該当なし。資格は未決定 |
| 確定の根拠 | ダウンロード元だけで自動確定しない。原典属性（`A31a_203`・`A31a_204` が成果品の全Featureで一致）、メタデータ、公式の掲載情報を確認し、**Source Category Assignment Record**（版付き・承認付き）に根拠を保存する |
| 分類不能 | `other` へ割り当てず `unclassified` とする。代表の選択に参加させない。Readinessで阻害することを提案する |
| 意味 | 順序は代表結果を選ぶ運用設定であり、提供主体の優劣・精度の評価ではない |

## 4. 優先順位の判定表

区分ごとの状態（SP 第7.2節）:

| 状態 | 意味 |
|---|---|
| `confirmed_match` | 確認済みの該当（判定用の形状の内部。境界上・unknownは含まない） |
| `unknown` | 該当はなく、unknown（L1）がある |
| `boundary_only` | 境界上の接触だけ |
| `not_evaluated` | ソースはあるが評価できない（判定不能） |
| `no_polygon_extent_unknown` | 該当もunknownもない。**評価範囲不明**（A31aは評価済み範囲を持たない） |
| `not_registered` | その区分のソースが公開世代にない（データ未登録） |
| `confirmed_no_match` | 予約（評価済み範囲を持つデータ用）。**A31aでは使わない** |

代表の選択（SP 第7.3節）:

| 上位区分の状態 | 採用区分に確認済みの該当 | 代表結果 | `selection_reason` | `finality` |
|---|---|---|---|---|
| （採用区分がpriority 1） | あり | 採用区分 | `highest_priority_confirmed_match` | 同じ区分に不確実性があれば `provisional`、なければ `final` |
| すべて `no_polygon_extent_unknown`・`not_registered` | あり | 採用区分 | `no_higher_priority_confirmed_match` | 同上 |
| いずれかが `unknown`・`boundary_only`・`not_evaluated` | あり | 採用区分 | `higher_priority_uncertain` | `provisional` |
| — | 全区分になし | `null` | `no_confirmed_match` | — |
| — | あり、ただし同順位で比較不能 | 浸水深 `null` | `aggregation_undetermined` | `provisional` |

同順位の集約（SP 第8章）: 原典のランク番号を数値比較せず、同じ体系・同じ版の正規化した区間（下限・上限・端点の包含は `unspecified`）で比較し、最も深い区分を代表にする。包含・部分的な重なり・異なる体系は比較不能（`aggregation_undetermined`）とする。同じ深さのタイは、寄与した全区域を列挙する。そのうえで、決定的な順序の先頭を `primary` とする。

## 5. unknownを含むケース別の期待結果

| No | 状況 | 代表 | `assessment_status` | `selection_reason`・`finality` | 保持する情報 |
|---|---|---|---|---|---|
| 1 | 優先1・優先2とも確認済みの該当 | 優先1 | `determined_match` | `highest_priority_confirmed_match`・`final` | 優先2の該当を来歴付きで保持。優先2が深ければ `deeper_match_outside_representative = true` |
| 2 | 優先1に該当なし、優先2に確認済みの該当 | 優先2 | `determined_match` | `no_higher_priority_confirmed_match`・`final` | 優先1は「評価範囲不明」。データがない・浸水しないと断定しない |
| 3 | 優先1がunknown、優先2に確認済みの該当 | 優先2 | `partial_unknown` | `higher_priority_uncertain`・`provisional` | 優先1のunknownを残す。判定済みだけで完結させない |
| 4 | 全ソースで該当なし（地域の内部） | なし | `no_match_extent_unknown` | `no_confirmed_match` | `assessment = undetermined`。「安全」「浸水なし」と返さない |
| 5 | 同じFeatureに有効な構成Pと判定保留の構成Q | Pの区分（比較の結果） | `partial_unknown` | Qと同じ区分なら `provisional` | `matches` と `unknowns` の両方に現れる（`has_area_match`・`has_unknown`） |
| 6 | 異なる区分の複数unknown | 確認済みの該当があればその規則、なければなし | `partial_unknown` または `unknown_only` | — | 低順位のunknownも削除しない |
| 7 | 優先1に境界接触だけ、優先2に確認済みの該当 | 優先2 | `partial_unknown` | `higher_priority_uncertain`・`provisional` | 境界接触を保持 |
| 8 | 優先1の中で比較できない区分の該当 | 浸水深なし | `aggregation_undetermined` | `aggregation_undetermined` | 両方の該当を保持 |
| 9 | 地域外／地域の外縁上 | — | 地域外は `status = no_data`／外縁上は判定し `region_boundary` を付ける | 外縁上は `provisional` | 地域外は判定しない |

**表示上の代表値の選択と、安全性の評価を混同しない。** 代表は運用設定で選ぶため、代表より深い想定が他の区分にありうる。下位の該当は必ず返し、`deeper_match_outside_representative` で示す。全ソース中の最大区分の併記（`max_depth_among_matches`）は拡張案として示し、見せ方・安全上の扱いはOWNER判断とした（SP 第8.5節）。

エラーと正常な判定不能を混同しない。unknown・評価範囲不明・集約不能・外縁上は `status = success` で `result` に入れる。取得失敗・整合性の異常・入力の不正は `result = null` とする（API 第5.7節）。

## 6. 既存契約との責務分界

| 担当 | 責務 | 禁止 |
|---|---|---|
| Normalize | 原典の完全保持・幾何妥当性の評価 | 優先順位によるデータの削除 |
| Integration | 全原典の来歴・有効な検索形状・判定保留の保持 | 優先順位による原典の切捨て。代表ランクの格納（I 第5章 原則4と整合） |
| Point Assessment | 地点と各形状・unknown範囲・地域の関係の判定 | 優先順位の参照 |
| Source Priority Resolver | 承認済みのポリシーによる代表ソースの選択 | 該当・unknownの削除。未承認のポリシー |
| Risk Aggregator | 比較可能な浸水深区分の集約、全ソース・unknownの維持 | ランク番号の数値比較。比較不能時の任意の選択 |
| Flood API | 代表・理由・採用元・不確実性の表示 | unknownの非該当・安全への変換。ポリシーの上書き |
| Data Management（将来） | ポリシー・区分の割当の登録・変更・承認の依頼・有効化の依頼・履歴 | 承認の代行。原典・統合成果物の変更 |
| Data Publish | ポリシーを含む公開世代の原子的な切替え（既存契約） | — |

優先順位・区分の変更では、Normalize・Integrationの実データを作り直さない。ソースの追加・削除・原典の更新による再処理は、別の問題として扱う（I 第11.2節）。

## 7. 既存契約との論点（変更せず記録）

| No | 既存契約 | 論点 | 記録先 |
|---|---|---|---|
| 1 | Data Publish・Dataset Registry・I 第9.3節 | 公開世代にSource Priority Policy・区分の割当記録・unknownポリシーを含める項目がない | SP-C1 |
| 2 | データソース定義 §2 | 指示書の「Source Registry」に当たる記録がない。区分の割当（確認済みの事実と承認）は、Source Definition（予定）にも公開Registryにも入らないため、新設が必要 | SP-C2 |
| 3 | I 第7.3節 | Readinessの阻害理由に、Source Priority Policyの未承認・`unclassified` のソースがない | SP-C3 |
| 4 | 共通API §6、Registry §6 | 優先順位・最大値による選択を独断で導入しない、という規定。本書の規則はOWNER承認まで提案 | SP-C4・FA-C7 |
| 5 | 本番実行認可 | ポリシーの承認記録のSchemaがない（I OI-27と同じ） | SP-C5 |
| 6 | I 第10章 | 「判定保留の区域のランクが分からない」の解釈。原典のランクは属性で分かるが、地点が含まれるかが分からない。可能性として返すかは未決定 | SP-C6・FA-U5 |
| 7 | 共通API §2 | 入力名は `lat`・`lon`。指示書の例は `latitude`・`longitude` | FA-C1 |
| 8 | 共通API §3.1・§4.2 | 該当性は `affected`・`not_affected`。本書は `undetermined` を追加し、`not_affected` を使わない | FA-C2 |
| 9 | 共通API §5 | 「管理主体を公開しない」と、提供主体名（`source_organization`）の返却の関係 | FA-C3 |
| 10 | 共通API §2・§3.1 | 入力エラーの `status`、部分結果の `status` が未決定 | FA-C4・FA-C5 |
| 11 | 共通API §3 | 追加フィールド（`policy`）の規則が未決定 | FA-C6 |

## 8. 未決定のOWNER判断

| No | 指示書の項目 | 本書の提案 | 記録先 |
|---|---|---|---|
| 1 | 同順位内での浸水深比較の正式な規則 | 同じ体系の正規化した区間で最も深い区分。確認項目CQ-1〜CQ-8の確認後に確定 | SP-U1 |
| 2 | 代表と全ソース中の最大浸水深の併記 | `deeper_match_outside_representative` は返す。最大値の併記は判断待ち | SP-U2・FA-U2 |
| 3 | `other` に含められるデータの資格 | 初期は該当なし | SP-U3 |
| 4 | 提供主体区分をどの原典情報から確定するか | `A31a_203`・`A31a_204`・メタデータ・掲載情報の一致 | SP-U4 |
| 5 | 区分を横断した比較可能性 | 代表の選択には使わず、事実の提示に限る | SP-U5 |
| 6 | 未評価・未登録・unknown・非該当の区別 | 区分ごとの7状態。非該当はA31aでは使わない | SP-U6 |
| 7 | 優先順位の変更時の世代管理とキャッシュの無効化 | 公開世代に固定、キャッシュのキーに世代 | SP-U7 |
| 8 | Data Managementの承認・有効化の権限 | 作成と承認の分離。承認はOWNER | SP-U8 |
| 9 | Flood APIの正式なレスポンスSchema | API 第5章を叩き台 | FA-U1 |
| 10 | A31aの評価範囲の扱い | 評価済み範囲がない前提で「評価範囲不明」を返す。正式な取得方法は未決定 | I OI-24 |
| 11 | Flood Publish / Registry / Authorizationとの接続 | 公開世代にポリシーを含める追加契約（SP-C1）、Readinessの阻害理由（SP-C3）、承認記録のSchema（SP-C5） | I OI-17・OI-27・OI-28 |
| 12 | 派生形状とL2の将来の利用条件 | MVPの対象外。Phase 2-B.8のBlockingのまま | N ON-15・ON-24、I OI-22 |
| 13 | Source Priority PolicyとLayer Presentation Policyの共通化 | 別の版管理とし、区分の割当記録・優先順位を内容ハッシュで参照する案 | SP-U13 |

追加の判断事項: 境界接触を確認済みの該当にしないこと（SP-U10）、`unclassified` の扱い（SP-U9）、共通APIとの論点（FA-C1〜FA-C7）、説明文言（FA-U4）、`zone_ref` の規則（FA-U6）、応答の上限（FA-U7）、公開停止と未公開の区別（FA-U8）、入力の座標系（FA-U9）。

## 9. 実装前・公開前のBlocking

**実装前（Flood APIのMVP）**

1. Phase 2-B.8の実装前Blockingの全件（[対応表](phase2b8-codex-audit-remediation.md) 第5章）。特に、製品の交差判定器・点の判定器と独立検証の方式（I OI-3）、妥当性モデルと版の固定（N ON-5）、統合成果物のSchema。
2. 本書の3文書の契約案の正式承認。
3. Source Priority Policyの初期版と、Source Category Assignment Recordの内容の承認。
4. 同順位の比較規則の確定（CQ-1〜CQ-8）。
5. 公開世代にポリシーを含める追加契約（SP-C1）、区分の割当記録の保存先（SP-C2）、ポリシーの承認記録のSchema（SP-C5）。
6. 共通API契約との論点の決定（FA-C1〜FA-C7）と、正式なレスポンスSchema（FA-U1）。
7. API入力の座標系・精度（FA-U9）。
8. 合成データだけで実装・試験する場合も、その範囲の承認（実データの処理はFlood用の認可プロファイルが成立するまでBLOCKED）。

**公開前**

1. Phase 2-B.8の公開前Blockingの全件（同 第5章）。全対象入力の検証、A31a・N03の利用条件、出典・加工表示、Flood Publishの受入プロファイル、OWNERの公開承認を含む。
2. Source Priority Policy・区分の割当・unknownポリシーの承認と、公開世代への固定。Publication Readiness・Publish直前の再確認での照合（SP-C3）。
3. 第5章のケース1〜9と、API 第10章の契約テストの合格。
4. 説明文言の確定（FA-U4）。評価範囲不明・判定保留が「安全」と誤読されないこと。
5. 代表と最大浸水深の見せ方の決定（SP-U2）。

## 10. Phase 2-B.8の未解決事項への影響

本工程は、Phase 2-B.8の未解決のBlockingを**解消していない**。MVPの設計は、それらの未解決を前提に組み立てた。

| Phase 2-B.8の事項 | 状態（変更なし） | 本設計への影響 |
|---|---|---|
| B7-01 Readiness | 文書上は解決。Publishとの接続は未決定（OI-28） | ポリシー・区分の割当の照合を、Readinessの阻害理由に追加する提案（SP-C3）を加えた。接続の追加契約の範囲が広がる |
| B7-02 Feature／構成Polygon | 文書上は解決。関与集合の特定方式は未確定 | Point Assessmentは `search_target`・`unknown_region` を使い、同じFeatureの有効部分の該当とunknownを両方返す（ケース5）。方式が確定するまで実装できない |
| B7-03 派生形状 | **一部解決。製品利用はBLOCKED** | MVPの対象外とした。`geometry_basis = derived` の該当は確認済みの該当に数えない |
| B7-04 L2 | **禁止。採用前Blocking** | MVPはL1だけ。unknownの範囲は外接矩形であり、実際の区域より広い。説明文言（FA-U4）と地図の表現（SP 第9章）に影響する |
| B7-05 N03 | 文書上は解決 | 地域外・外縁上の判定の前提。N03が使えない世代は公開されないため、APIは `region_state` を常に得られる前提とした |
| B7-06 Feature階層 | 文書上は解決 | 提供主体の区分の根拠（`A31a_203`・`A31a_204`）は `source_properties` から取る。原典の `Feature.id` は公開しない（`zone_ref` を使う） |
| B7-07 評価行 | 文書上は解決 | 影響なし |
| B7-08 unknownポリシー | 文書上は解決。承認記録のSchemaは未決定（OI-27） | Source Priority Policyも同じ固定の規則を使う。承認記録のSchemaの未決定が、両方のポリシーに及ぶ |
| B7-09 座標モデル | 文書上は解決 | API入力の座標系・精度（FA-U9）は未決定のまま。地点を丸めない |
| 26成果品の選別の再検証（I OI-25）・関東地方整備局の残り37成果品 | 未実施 | どの区域が統合成果物に入るかが確定していないため、ケース別の結果は合成データでしか検証できない |
| A31a・N03の利用条件 | 未解決 | 公開できない。`source_organization`・`attribution` の文言も未確定 |

## 11. 本工程で確認していないこと

1. 本書の3文書は、Codexによる監査・OWNERのレビューを受けていない。
2. 東京都と関東地方整備局の区域が実際に重なる地点での代表結果は、計算していない。Integration契約のI-07は、Phase 2-A.4の入力版の調査値として、東京駅が荒川（国）ランク1と隅田川の成果品（都）ランク1の2区域に該当するとしている（調査用の判定器による値で、製品の判定器での再現は未確認）。この場合は、本設計の初期値で代表は都（優先1）になり、国の該当も保持される。
3. 浸水ランクコードの版・閾値が東京都と関東地方整備局で同じかは、確認していない（CQ-1・CQ-3）。
4. 契約テストはすべて設計だけで、実行していない。
