# Phase 2-B.10 Flood Source Selection 設計改訂 検討記録 — **HISTORICAL**

> **履歴資料（2026-10-25 Phase 2-B.17で表示を追加）: 本書は現行の仕様の根拠ではない。実装・API・UI・テストの根拠として使用禁止。**
>
> - 本書が扱うSource Selection方式のうち、ソース間の深さの比較（`deeper_in_other_sources`）・ソース内の集約・状態の要約（`overall_status`）・サーバ側のソースの選択は、OWNERの仕様変更（公式データ忠実提示方式）により**廃止**された。廃止した機能を再導入しない。
> - 現行の正本: [Design Principles](../../docs/architecture/design-principles-v1.0.md)、[Flood Official Data Presentation Contract](../../docs/architecture/flood-official-data-presentation-contract-v0.1.md)、[Flood API MVP Contract](../../docs/api/flood-api-mvp-contract-v0.1.md)。
> - 本書の監査判定・日時・観測結果・対応の記録は改変していない。本書に記載したBlocking・OWNER判断事項のうち、廃止した機能に関するものは、現行の仕様のBlockingではない。扱いは [Phase 2-B.17 レビュー](phase2b17-official-data-presentation-realignment.md) 第7章を参照。

- Task: Phase 2-B.10 Flood Source Selection Contract 設計改訂
- 作成: 2026-10-25（Claude）
- 基準コミット: `fdf4f2df7d7a29f18519183ff8d2b931e6f4adc5`
- 成果物:
  - 新規: [Flood Source Selection Contract v0.1（案）](../../docs/architecture/flood-source-selection-contract-v0.1.md)（以下「SS」）
  - 新規: 本書
  - 修正: [Flood Source Priority & Risk Aggregation Contract v0.1（案）](../../docs/architecture/flood-source-priority-contract-v0.1.md)（以下「旧SP」）。冒頭に移行案内を追加し、本文はPhase 2-B.9の時点のまま残した
  - 修正: [Flood API MVP Contract v0.1（案）](../../docs/api/flood-api-mvp-contract-v0.1.md)（以下「API」）。選択方式へ全面改訂
- 参照: [Normalize契約](../../docs/architecture/flood-normalize-contract-v0.1.md)、[Integration契約](../../docs/architecture/flood-integration-contract-v0.1.md)（I）、[共通API契約](../../docs/api/common-contract-v0.1.md)、[Phase 2-B.8 対応表](phase2b8-codex-audit-remediation.md)、[Phase 2-B.9 レビュー](phase2b9-flood-mvp-scope-and-priority.md)、Dataset Registry・Data Publish・本番実行認可・データソース定義

本工程は**設計案の改訂だけ**である。変更はMarkdownの4ファイルだけで、製品コード・調査スクリプト・実データ・Registry実体・Docker・VPSには触れていない。新しいデータも取得していない。Normalize・Integration・共通API・Registry・Publish・Authorizationの契約は変更していない。**本工程は正式採用・実装・公開の承認ではない。** 旧SPの「置き換え（superseded）」は設計案の変更履歴であり、どちらの案もOWNERに正式採用されていない。

設計原則: **内部は厳密に。外部はシンプルに。不確実性は隠さない。**

## 1. 旧Priority方式との比較

| 観点 | 旧Priority方式（Phase 2-B.9） | 新Selection方式（Phase 2-B.10） |
|---|---|---|
| 代表の決め方 | システムが提供主体の優先順位（地方自治体 → 国土交通省 → その他）で代表のソースを自動で選ぶ | **システムは選ばない**。利用者が `source_id` を指定した場合だけ、そのソースを主表示にする |
| 提供主体の区分 | 選択の単位で、順位を持つ | 分類・表示・フィルターだけに使う。**順位を持たない** |
| 未選択の状態 | なし（常に代表を決める） | `overview` を正式な状態とし、特定のソースを暗黙に代表にしない |
| ソース間の扱い | 同じ区分の複数の該当を「同順位」として集約する | ソースごとに独立して判定する。**異なるソース間で浸水深を統合しない** |
| 集約 | 同順位（同じ区分）の最も深い区分 | 同一ソース内の最も深い区分だけ（ソース内の集約） |
| より深い他の想定 | `deeper_match_outside_representative`（代表との比較） | `deeper_in_other_sources`（選択中のソースとの比較）、`overview` では `depth_classes_present`（事実の列挙） |
| 不確実性の表現 | `finality`（`final`・`provisional`）、区分ごとの状態 | ソースごとの `assessment_status`・5つの区別、全体の状態の要約 `overall_status`（浸水深を持たない） |
| ポリシー | Source Priority Policy（承認・有効化・公開世代への固定） | 廃止。代わりにSource Catalog・Source Display Settings（表示順。信頼性の順位ではない）を公開世代に固定 |
| リクエストの入力 | `lat`・`lon` だけ | `lat`・`lon`・任意の `source_id` |
| サービスの立場 | 運用設定としての順位（優劣・精度の評価ではないと注記） | 提供主体どうしの信頼性に**独自の優劣を付けない** |

旧方式を採用しない理由: 運用設定と注記しても、自動の代表選択は「サービスが選んだ値が正しい」と受け取られやすい。また、優先1のソースが浅く優先2のソースが深い場合に、深い想定が代表から外れる。新方式は、どのソースを主に見るかを利用者に委ね、他のソースの情報を常に同じ応答に含める。

## 2. 新Selection方式の責務

| 担当 | 責務（SS 第1章） | しないこと |
|---|---|---|
| Source Discovery | 地点に関係するソースの候補を列挙する。5つの区別（登録・サービス対象地域・評価済み範囲・確認済みの該当・unknown）と、候補の列挙範囲・候補不足の可能性を返す | 判定・選択 |
| Point Assessment | ソースごとに独立して地点を判定する。全該当・境界接触・unknownを保持し、ソース内の集約を行う | ソース間の統合・選択 |
| Source Selection | 明示された `source_id` を検証・解決する | 判定の変更・代表の自動選択 |
| Flood API | 結果・来歴・不確実性・安全上の情報を返す | 安全・浸水なしへの変換 |
| UI（将来） | 比較・選択の支援、選択中のデータの明示、他のデータの存在・より深い想定・unknownの提示 | 判定・選択の代行。並び順を「おすすめ」「信頼度順」と表現すること |
| Data Management（将来） | ソースの登録・公開資格、区分と根拠、表示順・グルーピング、公開世代・来歴・承認の管理 | 承認の代行、原典・統合成果物の変更 |

**原典・Normalize・Integrationへの影響**: なし。選別（I 第4.1節）は全ソースの全Featureに同じ規則を適用しており、ソースの選択の影響を受けない。ソースの選択・表示順・区分の変更は、統合成果物を再生成しない。目録・区分の割当記録・表示設定を公開世代に固定する項目は、Publish・Registryの追加契約として扱う（第7章）。

## 3. API入出力の差分

| 項目 | 旧（Phase 2-B.9） | 新（Phase 2-B.10） |
|---|---|---|
| エンドポイント | 未記載（共通APIと同じく未決定） | `GET /api/flood?lat&lon[&source_id]` の1つ（仮案）。Discoveryの別エンドポイントはMVPでは設けない（API 第3.1節） |
| 入力 | `lat`・`lon`。任意パラメータなし | `lat`・`lon`・任意の `source_id`。その他のパラメータは入力エラー |
| `result.representative` | 代表結果 | **廃止** |
| `selection_reason`・`priority`・`finality`・`category_states` | あり | **廃止** |
| `result.selection` | なし | `mode`（`overview`・`single_source`）・`source_id`・`selected_by`（`user` のみ） |
| ソースごとの結果 | なし（全ソースの `matches` 等を1つの配列） | `result.sources[]`。ソースごとに `assessment_status`・`depth`・`matches`・`unknowns`・`boundary_contacts`・5つの区別 |
| 全体の状態 | `assessment_status`（代表に基づく） | `overall_status`（全ソースの状態の要約。浸水深を持たない） |
| 安全上の情報 | `deeper_match_outside_representative` | `result.safety`（`other_sources_count`・`deeper_in_other_sources`・`has_unknown`・`has_unknown_in_other_sources`・`depth_classes_present`）、`selected_result_is_exclusive = false` |
| 候補の範囲 | なし | `candidate_scope`・`candidate_completeness = not_guaranteed`・`not_included_notice` |
| 設定の版 | `policy`（Source Priority Policy 等） | `settings`（Source Catalog・区分の割当記録・表示設定・unknownポリシー） |
| 入力エラー | 座標・未知のパラメータ | 加えて `invalid_source_id`・`source_not_available`・`multiple_sources_not_supported` |

指示書の概念例（`selected_result`＋`other_sources`）は、`sources[]`＋`is_selected` の1つの形にまとめた。`overview` と `single_source` で同じ形を使い、選択によって他のソースの情報の形が変わらないようにするためである（API 第5.1節）。

## 4. 未選択・選択済みの状態遷移

```text
              source_id を指定
 overview ────────────────────────► single_source(A)
    ▲                                   │     │
    │ source_id を外す                  │     │ 別の source_id(B) を指定
    └───────────────────────────────────┘     ▼
                                       single_source(B)

 single_source(A) で A が新しい公開世代の目録にない場合
   → 入力エラー（source_not_available）。overview・別ソースへ自動で移らない
```

- 状態はリクエストごとに決まる。サーバは利用者の選択を保存しない（保存・復元はUIの責務）。
- 公開世代の切替えで選択中のソースがなくなった場合、UIはその事実を示して選び直しを求める。自動で別のソースに切り替えない。
- `selected_by` に `system` の値はない。

## 5. 他ソースの情報・unknownを維持する規則

| No | 規則 | 契約 |
|---|---|---|
| 1 | 選択は判定を変えない。`source_id` の有無・値にかかわらず、全ソースの判定の項目は同じ | SS 第6.1節、API 第4章、FA-05 |
| 2 | `single_source` でも全ソースを `sources[]` に含める | SS 第7章 No.1、API 第5.3節 |
| 3 | 選択中のソースより深い区分の確認済みの該当が他ソースにあれば `deeper_in_other_sources = true` | SS 第7章、API 第5.6節 |
| 4 | 比較不能な区分を大小比較しない。区分の体系の同一性が未承認の間は `null` | SS 第5.3節・第7章 |
| 5 | 全ソースのunknownを全件返す。`has_unknown_in_other_sources` | SS 第7章 No.4 |
| 6 | 無効形状由来のunknownを浸水なしにしない（`unknown_only`） | SS 第5.2節 |
| 7 | 評価範囲不明を区域外と断定しない（`assessed_extent_relation = unknown`、`no_match_extent_unknown`） | SS 第4.1節 |
| 8 | 選択中の値を唯一の正しい浸水深として示さない（`selected_result_is_exclusive = false`） | SS 第7章 No.7 |
| 9 | 選択中のソースが確定していても、他ソースに不確実性があれば `overall_status = partial_unknown` | API 第5.7節 |
| 10 | 同じFeatureの有効部分の該当とunknownを両方保持する | SS 第5.1節 |
| 11 | 一覧を件数の上限で黙って切り捨てない | API 第5.4節 |

## 6. 表示順と信頼性順位の区別

- 一覧の並び順は、公開世代のSource Display Settings（SS 第8.1節）で決める。**表示順は信頼性の順位を意味しない。** 設定がない場合の既定は `source_id` の昇順（中立な順序）。
- 表示順の変更は、判定の結果・選択の可否・安全上の情報を変えない。表示順の変更だけでNormalize・Integrationを再実行しない（同じ統合成果物を参照する新しい公開世代で切り替える）。
- 表示順・区分・優先順位をリクエストで指定させない。
- 表示設定には「表示順は信頼性の順位ではない」ことを示す文言の参照を持たせる。UIは並び順を「おすすめ」「信頼度順」と表現しない。
- 区分によるグルーピング（`group_by = source_category`）のグループの順も、表示順の設定であり、区分の順位ではない。

## 7. 既存契約との不整合・論点（変更せず記録）

| No | 既存契約 | 論点 | 記録先 |
|---|---|---|---|
| 1 | Data Publish・Dataset Registry・I 第9.3節 | 公開世代にSource Catalog・区分の割当記録・表示設定・unknownポリシーを含める項目がない | SS-C1 |
| 2 | データソース定義 §2 | 区分の割当とSource Catalogは、Source Definitionにも公開Registryにも入らない。新設が必要 | SS-C2 |
| 3 | I 第7.3節 | Readinessの阻害理由に、`unclassified` のソース・Source Catalogの不整合がない | SS-C3 |
| 4 | 共通API §6、Registry §6 | 「優先順位・最大値による選択を独断で導入しない」。新方式はシステムによる優先順位・自動選択を導入しないため整合する。ソース内の集約はOWNERの承認まで提案 | SS-C4・FA-C7 |
| 5 | 共通API §2「利用者に都道府県やデータセットの選択を要求しない」 | 選択は要求しない（既定は `overview`）。ただし、データソースを任意に選ぶ入力は共通契約にない | SS-C5・FA-C8 |
| 6 | 共通API §3 `dataset` の複数件の形 | 公開世代の `dataset` は1つ、ソースごとの来歴は `sources[]` | SS-C6・FA-C9 |
| 7 | 本番実行認可 | 設定（目録・区分の割当・表示設定）の承認記録のSchemaがない | SS-C7 |
| 8 | I 第10章 | 判定保留の区域の原典ランクを可能性として返すか | SS-C8・FA-U5 |
| 9 | 共通API §2・§3.1・§4.2・§5 | 入力名（`lat`・`lon`）、`undetermined` の追加、`source_organization` と「管理主体を公開しない」の関係、入力エラー・部分結果の `status`、追加フィールド `settings` | FA-C1〜FA-C6 |
| 10 | I 第5章 原則4（代表ランクは統合成果物に格納しない）・OI-6（最大ランク方式は候補） | 整合する。新方式はソース間の代表ランクを作らない。OI-6の「代表ランクの方式」は、ソース内の集約（SS-U2）に置き換わる可能性がある（I は変更していない） | — |
| 11 | [Phase 2-B.9 レビュー](phase2b9-flood-mvp-scope-and-priority.md) | 旧Priority方式を前提とした記述が残る。本工程の変更対象外（4ファイルに限定）のため修正していない。**履歴の記録として読み、現行の設計案の根拠にしない** | — |

## 8. 回帰テストケース

| ID | ケース | 期待 | 契約 |
|---|---|---|---|
| R-01 | **ケースA**: 東京都ランク1、関東地方整備局ランク4、東京都を選択 | 東京都を主表示。関東地方整備局を保持。`deeper_in_other_sources = true` | SS-01・FA-01 |
| R-02 | **ケースB**: 東京都unknown、関東地方整備局ランク3、関東地方整備局を選択 | 関東地方整備局の確認済みの結果を主表示。東京都のunknownを保持。`overall_status = partial_unknown` | SS-02・FA-02 |
| R-03 | **ケースC**: どのソースにも確認済みの該当なし | 浸水深0m・浸水なし・安全と返さない。評価範囲不明を示す | SS-03・FA-03 |
| R-04 | `overview` でケースAの地点 | 主表示なし。暗黙の代表なし。`depth_classes_present` に2区分 | SS-04・FA-04 |
| R-05 | 選択の有無・値を変えた同じ地点 | 全ソースの判定の項目が同一 | SS-11・FA-05 |
| R-06 | 同一ソースの2区域（ランク2・ランク3） | ソースの `depth` はランク3。両区域を保持 | SS-05 |
| R-07 | 同一ソース内の比較不能な区分 | `aggregation_undetermined`・`depth = null` | SS-06 |
| R-08 | 同じFeatureの有効P・判定保留Q | `matches` と `unknowns` の両方 | SS-07・FA-06 |
| R-09 | 目録にない・旧世代・形式不正・複数の `source_id` | 入力エラー。別ソース・未選択へ置き換えない | SS-09・FA-07 |
| R-10 | 区分・優先順位・ポリシーを指定する入力 | 入力エラー | SS-12・FA-08 |
| R-11 | 表示設定だけを変えた新しい公開世代 | 統合成果物は再生成されず、並び順だけが変わる | SS-10・FA-14 |
| R-12 | 区分の体系の同一性が未承認 | `deeper_in_other_sources = null`。両方の該当は保持 | SS-14 |
| R-13 | 応答全体 | `representative`・`selection_reason`・`priority`・`finality` が現れない。`selected_by = system` が現れない | FA-15 |
| R-14 | 地域外・外縁上 | `no_data`（`outside_service_region`）／`region_boundary` で不完全でありうることを示す | SS-15・FA-10 |
| R-15 | ランク番号の数値比較の誤りの模擬 | 正規化した区間の比較との不一致を検出 | SS-13 |
| R-16 | 同じ地点・同じ世代・同じ選択の繰り返し | 結果・並び順が同一 | SS-16・FA-18 |

いずれも設計だけで、テストコードは作成も実行もしていない。

## 9. 未決定事項

| No | 事項 | 本工程の提案 | 記録先 |
|---|---|---|---|
| 1 | `source_id` の粒度（提供主体×シナリオ×配布単位の系列、または成果品ごと） | 東京都・関東地方整備局の2つ | SS-U1 |
| 2 | ソース内の集約の正式な規則 | 同じ体系の正規化した区間で最も深い区分。CQ-1〜CQ-8の確認後 | SS-U2 |
| 3 | ソース間の比較（`deeper_in_other_sources`・`depth_classes_present`）とその前提 | 返す。区分の体系の同一性の承認前は `null` | SS-U3 |
| 4 | `source_id`・`zone_ref` の生成規則 | 公開世代の中で安定した不透明な識別子 | SS-U4・FA-U6 |
| 5 | `other` の資格 | 初期は該当なし | SS-U5 |
| 6 | 表示設定の承認の主体・軽重 | 版の固定と履歴は必須。承認の主体はOWNER判断 | SS-U6 |
| 7 | 目録の文言（`title`・`not_included_notice`） | 未決定 | SS-U7・FA-U12 |
| 8 | UIでの、より深い想定・unknownの見せ方 | 見落としにくい表示 | SS-U8 |
| 9 | 将来のモード（`multiple_sources`・`compare`）とソース間の比較の規則 | 保留 | SS-U9 |
| 10 | 公開世代に目録・設定を含める追加契約、保存先 | Publish・Registryの追加契約 | SS-U10 |
| 11 | エンドポイントの構成・APIパス・HTTPステータス | 1つのエンドポイント | FA-U10 |
| 12 | 正式なレスポンスSchema | API第5章を叩き台 | FA-U1 |
| 13 | 説明文言 | 「安全」「浸水なし」「おすすめ」「信頼度順」と誤読されない文言 | FA-U4 |
| 14 | 共通API契約との論点 | 第7章 No.9 | FA-C1〜FA-C9 |
| 15 | API入力の座標系・精度 | 地点を丸めない | FA-U9 |

## 10. 実装前・公開前のBlocking

**MVPの簡素化によって、既存のBlockingが解消されたとは扱わない。** 次は今回も未解決である。

**実装前**

1. Phase 2-B.8の実装前Blockingの全件（[対応表](phase2b8-codex-audit-remediation.md) 第5章）。
2. 幾何演算の独立検証（製品の交差判定器・点の判定器・独立検証の方式。I OI-3。妥当性モデルと版の固定。Normalize ON-5）。
3. 本工程の設計案（SS・API）の正式承認。
4. Source Catalog・区分の割当記録（根拠の確認を含む）・表示設定の内容の承認。
5. ソース内の集約の規則（SS-U2）と、区分の体系の同一性の確認（CQ-1〜CQ-8）。
6. 公開世代に目録・設定を含める追加契約（SS-C1）、保存先（SS-C2）、承認記録のSchema（SS-C7）。
7. 共通API契約との論点の決定（FA-C1〜FA-C9）と、正式なレスポンスSchema。
8. API入力の座標系・精度（FA-U9）。
9. 合成データだけで実装・試験する場合も、その範囲の承認（実データの処理は、Flood用の認可プロファイルが成立するまでBLOCKED）。

**公開前**

1. Phase 2-B.8の公開前Blockingの全件。
2. 有効Polygonを含む選別の再検証（26成果品のうち22成果品の有効Polygon、関東地方整備局の残り37成果品。I OI-25・I-18）。
3. Flood用のPublish・Registry・Authorizationの未決定事項（I OI-17・OI-27・OI-28、SS-C1・SS-C3・SS-C7）。
4. A31a・N03の利用条件、出典・加工表示（I OI-10・OI-11）。
5. 回帰テスト（第8章）と、API・SSの契約テストの合格。
6. 説明文言の確定（FA-U4）。
7. OWNERによる正式な契約承認と公開承認。

**引き続き禁止・BLOCKEDの機能**: 派生形状の製品利用（Normalize 第10.2節 条件(f)の独立方式が未完了）、L2の利用（I 第4.4節）。

## 11. 本工程で確認していないこと

1. 本書・SS・改訂したAPI契約は、Codexの監査・OWNERのレビューを受けていない。
2. 東京都と関東地方整備局の区域が重なる実際の地点での結果は計算していない。ケースA・B・Cは合成の想定である。
3. 東京都と関東地方整備局の浸水ランクコードの版・閾値が同じかは確認していない（CQ-1・CQ-3）。
4. 契約テスト・回帰テストはすべて設計だけで、実行していない。
