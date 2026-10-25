# Phase 2-B.14 Codex再監査指摘 対応表（Source Selection / Flood API MVP） — **HISTORICAL**

> **履歴資料（2026-10-25 Phase 2-B.17で表示を追加）: 本書は現行の仕様の根拠ではない。実装・API・UI・テストの根拠として使用禁止。**
>
> - 本書が扱うSource Selection方式のうち、状態の導出（B13-01）・ソース間の比較の承認（B13-02）・版をまたぐ比較（B13-03）・比較の件数（B13-04）は、OWNERの仕様変更（公式データ忠実提示方式）により**廃止**された。廃止した機能を再導入しない。
> - 現行の正本: [Design Principles](../../docs/architecture/design-principles-v1.0.md)、[Flood Official Data Presentation Contract](../../docs/architecture/flood-official-data-presentation-contract-v0.1.md)、[Flood API MVP Contract](../../docs/api/flood-api-mvp-contract-v0.1.md)。
> - 本書の監査判定・日時・観測結果・対応の記録は改変していない。本書に記載したBlocking・OWNER判断事項のうち、廃止した機能に関するものは、現行の仕様のBlockingではない。扱いは [Phase 2-B.17 レビュー](phase2b17-official-data-presentation-realignment.md) 第8章を参照。

- Task: Phase 2-B.14 Codex Re-Audit Findings Remediation
- 作成: 2026-10-25（Claude）
- 監査: Phase 2-B.13 Codex独立再監査（OWNERから提供された全文を一次資料とする）。監査対象 `7ef60043ce4638ad2417dcb17b723ce4411c43bc`（Phase 2-B.12の修正 `bc3815116c3a4b9b8de12ce8eef5aa65045cb5d6` と、Design Principles の追加を含む）
- 監査判定: **FAIL**（新規 HIGH 1 / MEDIUM 3。4件とも Implementation Blocking）
- 基準コミット: `7ef60043ce4638ad2417dcb17b723ce4411c43bc`
- 修正対象: [Flood Source Selection Contract v0.1（案）](../../docs/architecture/flood-source-selection-contract-v0.1.md)（以下「SS」）、[Flood API MVP Contract v0.1（案）](../../docs/api/flood-api-mvp-contract-v0.1.md)（以下「API」）、[Phase 2-B.12 対応表](phase2b12-source-selection-audit-remediation.md)（訂正の注記の追記だけ）

本書は**契約文書の修正状況**を示す。設計の機能追加ではなく、既存契約の矛盾・曖昧さの解消である。変更はMarkdownの4ファイル（上記3つと本書）だけである。Design Principles・Project Charter・共通API・Normalize・Integration・Publish・Registry・既存の監査原文・製品コード・実データ・VPS・Dockerには触れていない。

**Phase 2-B.11・B.13の監査判定（FAIL）を変更していない。Codexによる再監査（本修正の監査）は未実施である。** 本工程は契約の修正だけで、実装・実データ処理・公開・OWNERの正式承認を意味しない。

維持した原則（Design Principles v1.0）: **公式情報の違いを隠さない。内部は厳密に。外部はシンプルに。不確実性は隠さない。** Source Selection方式（`overview` 既定、利用者の選択、自動代表選択なし）を維持した。

## 1. 一覧

| ID | 重要度 | 件名 | 文書上の解決状況 | 主な修正箇所 |
|---|---|---|---|---|
| B13-01 | HIGH | 該当0件の規則がunknown・境界接触の状態を上書きする | RESOLVED（文書） | SS §3.5・§5.2冒頭、SS-03・SS-32・SS-37〜SS-40、API §8.3・FA-03・FA-22・FA-26、B.12対応表の注記 |
| B13-02 | MEDIUM | 比較未承認時の扱いが決定表と対応表で一致しない | RESOLVED（文書） | SS §7（判定の順序・承認の適用範囲・必須ケース表）、SS-U3・SS-U15、SS-41〜SS-43・SS-49・SS-50、API §5.6・FA-27、B.12対応表の注記 |
| B13-03 | MEDIUM | 同等と承認された異なる版の比較・集約が未定義 | RESOLVED（文書）。版の同等性はMVPの対象外へ移した（SS-U17） | SS §5.3（比較の資格・集約の識別子）、§7（区域の分類・`overview` の並び順）、SS-33・SS-46〜SS-48、API §5.5・FA-23・FA-28、B.12対応表の注記 |
| B13-04 | MEDIUM | 選択 `depth = null` 時の比較件数が未定義 | RESOLVED（文書） | SS §7（比較の件数の表）、SS-27・SS-28・SS-44・SS-45・SS-51、API §5.6・FA-27 |

## 2. 指摘ごとの対応

### B13-01 — HIGH：該当0件の新規規則がunknown・境界の状態を上書きする

**元の指摘**: SS §3.5は「目録にソースがあるが、確認済みの該当がない」場合、各ソースと全体を `no_match_extent_unknown` としていた。地点がL1 unknownに入る・境界接触がある・地域の外縁上の場合もこの条件を満たすが、§5.2とAPI §5.7では `unknown_only` になる。SS-32・FA-22にも同じ不足がある。

**修正箇所**

- SS §3.5: 表の3行目から状態名を削除し、「第5.2節の導出順序と決定表で決める」とした。確認済みの該当0件の5条件の表を追加した。
- SS §5.2冒頭: 本節を、ソースの `assessment_status` と `overall_status` の導出の唯一の正本と明記した。
- SS-03（ケースC）・API §8.3・FA-03: 前提に「unknown・境界接触がない、地域の内部」を加えた。同じ誤分類を持つ説明として検索で見つけた箇所である。
- SS-32・FA-22: 期待値を「状態は§5.2で導出」に訂正した。
- SS-37〜SS-40・FA-26を新設した。
- B.12対応表のB11-05の箇所に、訂正の注記を加えた。

**契約上の解決内容**: 状態の導出の正本を、SS §5.2の1か所にした。§3.5は状態を直接決めない。確認済みの該当0件の場合は次のとおり（いずれも§5.2の導出の結果）。

| 条件 | `assessment_status` | `overall_status` |
|---|---|---|
| 該当0件＋L1 unknownあり | `unknown_only`（順5） | `unknown_only` |
| 該当0件＋境界接触あり | `unknown_only`（順5） | `unknown_only` |
| 地域の外縁上＋該当0件 | `unknown_only`（順5） | `unknown_only` |
| 地域の内部で、該当・unknown・境界接触がすべて0件 | `no_match_extent_unknown`（順6） | `no_match_extent_unknown` |
| 空の目録 | （ソースなし） | `indeterminate`・`flood_integrity_error`。そもそも公開しない |

ソースごとに状況が異なる場合は、ソースごとに§5.2の順序を適用し、全体は§5.2の決定表で決める。ソースごとの `assessment_status` と、全体の要約である `overall_status` を混同しないことも明記した。

**元のB11 Findingへの影響**: B11-04・B11-05（再監査の判定はREGRESSION）の退行の原因を除いた。§5.2の導出順序・決定表・空の目録の規則（B.12の修正）は変更していない。

---

### B13-02 — MEDIUM：比較未承認時の扱いが決定表と対応表で一致しない

**元の指摘**: SS §7の決定表では、他ソース0件（順3）や確認済み区域0件（順6）で `false` になる。一方、B.12対応表とSS末尾には「未承認の間は全ケース `null`」とあり、未承認かつ他ソース0件で `false` と `null` が競合する。

**修正箇所**: SS §7（判定の順序、承認の適用範囲の注記、`basis` の決め方、必須ケース表への未承認の3行の追加、末尾の注記の訂正）、SS-U3・SS-U15、SS-41〜SS-43・SS-49・SS-50、API §5.6（`deeper_in_other_sources`・`deeper_comparison`）・FA-27、B.12対応表の注記

**契約上の解決内容**

- 判定の順序を、指示書の7段階にした。

| 順 | 条件 | 値 |
|---|---|---|
| 1 | 選択中のソースに確認済みの該当がない | `null` |
| 2 | 選択中のソースの `depth = null` | `null` |
| 3 | 他ソースが0件 | `false` |
| 4 | 他ソースに確認済み区域が0件 | `false` |
| 5 | 比較可能な深い区域が1件以上 | `true` |
| 6 | 深い区域がなく、比較不能な区域がある | `null` |
| 7 | すべて比較可能で、深い区域がない | `false` |

- 順4と順5〜7の対象の集合は、他ソースの `matches[]` の全区域と一致すると明記した。
- **比較の承認が必要なのは、実際に異なるソースの浸水深区分を比較する場合（順5〜7）だけ**とした。比較の対象がない場合（順1〜4）は、承認の有無によって結果を変えない。
- 確認済み区域があり、ソース間の比較が未承認なら、その全区域を `incomparable` とし、深さの数値の比較を行わない（順6で `null`）。
- 順6の `basis` は、未承認なら常に `cross_source_comparison_unapproved`、承認済みなら `incomparable_zones_present` とした（未承認では全区域が比較不能になるため、一意に決まる）。
- 「承認前は全ケース `null`」の記述は、SS（§7末尾・SS-U3・SS-U15）とB.12対応表の注記で訂正した。
- `false` は「確認済み区域について、より深い結果を確認していない」の意味であり、unknown・評価範囲不明は別のフィールドで返すことを維持した。

**元のB11 Findingへの影響**: B11-03（再監査の判定はPARTIALLY RESOLVED）の残りの問題のうち、承認の適用範囲を解消した。B.12で解消済みの深い＋比較不能・浅い＋比較不能・個別区域の参照の規則は維持した。B.12の順序では「他ソースに確認済み区域0件」が順6だったため、順4へ移した。結果の値は変わらない（区域が0件なら、深い区域も比較不能な区域も存在しないため）。

---

### B13-03 — MEDIUM：同等と承認された異なる版の比較・集約が未定義

**元の指摘**: SSは承認された同等の版を比較可能とし、ソース内の集約にも適用していた。ところが、比較表の「同じ」「深い」は同じ版を条件にしていた。体系X・v1・コード3と体系X・v2・コード3（同等は承認済み）が同じソースに該当すると、集約の可否と、集約の `depth` にどちらの版のキーを付けるかが決まらない。

**修正箇所**: SS §5.3（比較の表、比較の資格、MVPの対象外、集約の結果の識別子）、§7（区域の分類、`overview` の並び順）、SS-33・SS-46〜SS-48、SS-U15・SS-U17、API §5.5・FA-23・FA-28、B.12対応表の注記

**契約上の解決内容**

- **MVPでは、浸水深区分の版をまたいだ比較・集約を行わない。** 異なる版の区分は、閾値が同じに見えても比較不能とする。版の同等性を承認して比較する仕組みは、将来の拡張事項としてMVPの対象外にした（SS-U17）。
- 比較の資格は、`scheme_id`・`scheme_version`・区分体系の比較規則（`comparison_rule_id`。内部の項目）の3つの一致とした。`class_code` は個々の区分の同一性を識別する項目であり、異なる深さの区分を比べるために同じ値である必要はないと明記した。ソース間の安全上の比較は、これに加えてソース間の比較の承認を要する。
- 集約の結果の識別子は、集約に使った区域と同じキーとした。MVPでは集約できる区域が常に同じ体系・同じ版なので、識別子を選ぶ余地がない。同じソースに異なる版の区域が該当した場合は、集約不能（`depth = null`）とする。**任意の版を選んで代表 `depth` の識別子に採用しない。**
- 異なる版の原典情報と区分は、それぞれのキーのまま保持してAPIへ返す。`overview` の `depth_classes_present` では別の要素とし、並び順は `by_key` とする。
- `depth_classes_present` の `by_depth` の条件を、列挙した全区分が互いに比較可能（異なるソースの区分を含む場合はソース間の比較の承認も）な場合に限定した。

**元のB11 Findingへの影響**: B11-06（再監査の判定はPARTIALLY RESOLVED）の残りの問題を、機能の範囲を狭めて解消した。区分の識別（全 `depth` に3つ組を必須）と重複排除の規則（B.12の修正）は維持した。

---

### B13-04 — MEDIUM：選択 `depth = null` 時の比較件数が定義されていない

**元の指摘**: `deeper_comparison` は理由と3つの区域の件数を返すが、各区域の分類は選択中の `depth`（S）との比較を前提としている。選択中に該当がない場合や集約不能の場合、件数が決まらない。

**修正箇所**: SS §7（比較の件数の表、`basis` と件数の対応、必須ケース表への件数の列の追加）、SS-27・SS-28・SS-44・SS-45・SS-51、API §5.6（`deeper_comparison`）・FA-27

**契約上の解決内容**

| 状況 | 3つの件数 |
|---|---|
| 比較を実施していない（順1・2。比較の基準 `S` がない） | すべて `null`。他ソースが0件でも、選択側の理由（`basis`）を優先する |
| 比較を実施し、対象が空（順3・4） | すべて `0` |
| 比較を実施した（順5〜7） | 各分類の件数。`incomparable_zones` には比較不能な区域の件数を返す。3つの和は他ソースの確認済み区域の総数 |

- `null` は比較を実施していないこと、`0` は比較を実施しその分類の区域が0件であることを表し、区別する。
- `basis` が `selected_has_no_confirmed_match`・`selected_depth_unavailable` なら件数はすべて `null`、それ以外なら件数はすべて整数とし、`basis` と件数の意味が常に一致するようにした。

**元のB11 Findingへの影響**: B11-03の残りの問題のうち、応答仕様の完全性を解消した。

## 3. 新規・変更した受入条件

**新規（SS-37〜SS-51。API FA-26〜FA-28はこれを参照）**

指示書の15の合成ケースとの対応は次のとおりである。各ケースの `assessment_status`・`overall_status`・`deeper_in_other_sources`・`basis`・比較の件数は、SS §12の表に前提とともに記載した。共通の前提（地域の内部、同じ体系・同じ版・同じ比較規則、ソース間の比較は承認済み、選択中はA）を表の上に明記し、各ケースで異なる前提は行に書いた。

| No | 指示書のケース | テスト | 要点 |
|---|---|---|---|
| 1 | 非空Catalog、該当0件、unknownあり | SS-37 | `unknown_only` / `unknown_only` |
| 2 | 非空Catalog、該当0件、境界接触あり | SS-38 | `unknown_only` / `unknown_only` |
| 3 | 非空Catalog、地域外縁上、該当0件 | SS-39 | `unknown_only`（`region_boundary`） / `unknown_only` |
| 4 | 非空Catalog、該当・unknown・境界接触が0件 | SS-40 | `no_match_extent_unknown` / `no_match_extent_unknown` |
| 5 | 比較未承認、他ソース0件 | SS-41 | `false` / `no_other_sources` / 0・0・0 |
| 6 | 比較未承認、他ソースunknownのみ | SS-42 | `false` / `no_confirmed_match_in_other_sources` / 0・0・0 |
| 7 | 比較未承認、他ソースに確認済み区域あり | SS-43 | `null` / `cross_source_comparison_unapproved` / 0・0・1 |
| 8 | 選択中に確認済み該当なし、他ソース2件 | SS-44 | `null` / `selected_has_no_confirmed_match` / null・null・null |
| 9 | 選択中が集約不能、他ソース2件 | SS-45 | `null` / `selected_depth_unavailable` / null・null・null |
| 10 | 異なる版の同深度区分 | SS-46 | ソース内は集約不能、ソース間は `null` / `incomparable_zones_present` / 0・0・1 |
| 11 | 異なる版の異なる深度区分 | SS-47 | ソース内は集約不能、ソース間は `null`（`true` にしない） |
| 12 | 同一体系・同一版の異なる深度区分 | SS-48 | ソース内は深い方、ソース間は `true` / `deeper_zone_found` / 1・0・0 |
| 13 | 深い区域＋比較不能区域 | SS-49 | `true` / `deeper_zone_found` / 1・0・1 |
| 14 | 浅い区域＋比較不能区域 | SS-50 | `null` / `incomparable_zones_present` / 0・1・1 |
| 15 | 他ソース0件、選択中 `depth = null` | SS-51 | `null` / `selected_depth_unavailable` / null・null・null |

**変更（期待値・前提の訂正）**

| テスト | 変更 | 指摘 |
|---|---|---|
| SS-03・FA-03（ケースC） | 前提に「unknown・境界接触がない、地域の内部」を明記 | B13-01 |
| SS-32・FA-22 | 非空の目録の該当0件の期待値を「§5.2で導出」に訂正 | B13-01 |
| SS-27 | 件数がすべて `null` を追記 | B13-04 |
| SS-28 | 前提「選択中に `depth` がある」と件数 `0` を明記 | B13-04 |
| SS-33・FA-23 | 「版の同等性が未承認なら比較不能」を「MVPでは常に比較不能」に訂正 | B13-03 |
| SS §7 の必須ケース表 | 件数の列を追加し、未承認の3ケースと「他ソース0件・選択中 `depth = null`」を追加 | B13-02・B13-04 |

いずれも設計上の受入条件であり、テストコードは作成も実行もしていない。

## 4. Phase 2-B.12対応表の扱い

B.12対応表の元の記述と対応状況は、履歴として変更していない。訂正が必要な6か所（B11-03の承認の記述、B11-03の受入条件（判定の順序と件数）、B11-05の非空の目録の該当0件、B11-06の版の同等性・比較の資格の2段階、B11-06のOWNER判断事項、第4章の監査反例No.4の順番号）に「［Phase 2-B.14で訂正］」の注記を追記した。冒頭にも追記の趣旨と、再監査の判定（B11-03・B11-06はPARTIALLY RESOLVED、B11-04・B11-05はREGRESSION）を記載した。B11-01・B11-02・B11-07（再監査でRESOLVED）の記述には手を加えていない。

## 5. 未決定事項と既存Blocking

**本工程で変更・追加した未決定事項**

| No | 事項 | 状態 |
|---|---|---|
| SS-U3 | ソース間の比較を返すことと、その前提 | 承認前の扱いの適用範囲を明確化（比較の対象の区域がある場合だけ `null`） |
| SS-U15 | ソース間の比較の承認 | 版の同等性を切り離した。CQ-1・CQ-3の確認後のOWNER承認 |
| SS-U17 | 版の同等性を承認して版をまたいで比較・集約する仕組み | **新設。MVPの対象外** |
| — | `comparison_rule_id`（区分体系の比較規則）の登録の形式 | Source CatalogのSchemaの一部として未決定（SS-C2の範囲） |

**既存のBlocking（変更なし。解消したとは扱わない）**: Phase 2-B.13監査の §7・§8、Phase 2-B.12対応表 第5章、Phase 2-B.8対応表 第5章のとおりである。主なものは次のとおり。

- **実装前**
  - SS・APIのOWNER正式承認
  - `source_id` の粒度・生成・継続性
  - 目録・所属・区分の割当・表示設定・Catalog Validate Record・承認記録のSchemaと保存先
  - CQ-1〜CQ-8・ソース内の集約・ソース間の比較の確認・承認
  - 共通APIの追加値・フィールド・HTTP対応・正式Schema
  - 座標系・精度・幾何モデル・独立検証方式・依存版・資源上限
  - Flood用のSource Definition・各Record・認可プロファイル
  - SS-C1・SS-C3・SS-C10の公開世代・Readinessへの接続
  - 応答上限の値と性能評価
- **公開前**
  - 全対象入力の検証（残り22成果品の有効Polygon、関東地方整備局の残り37成果品を含む）
  - 所属漏れ・重複・unknown欠落・混在Feature・N03異常・索引漏れの否定試験
  - Flood Publish・Registry・AuthorizationとReadinessの接続
  - Publish直前の再確認
  - 世代切替・並行要求・障害・復元の検証
  - A31a・N03の利用条件、出典・加工表示、`source_organization` の公開の解釈
  - 説明文言とOWNERの明示的な公開承認
- **引き続き禁止・BLOCKED**: 実データの処理（Flood用の認可プロファイルの成立まで）、派生形状の製品利用、L2

既存のIntegration・Publish・Registry・共通APIへの追加（SS-C1・SS-C3・SS-C10・SS-C11等）は、未反映のままである。

## 6. 未実施の検証

1. **本修正に対するCodexの再監査は未実施である。** Phase 2-B.13の判定（FAIL）は変更していない。
2. 三値判定・状態の導出・比較の件数・版の扱いを、実装・試験していない。受入条件はすべて設計だけである。
3. 浸水ランクコードの版・閾値・比較規則が、東京都と関東地方整備局で同じかは確認していない（CQ-1・CQ-3）。
4. 修正後の文書全体について、Design Principles v1.0との整合を、本工程の範囲（DP-07・DP-08・DP-10に関わる箇所）で確認した。全原則の独立した照合は、再監査で行う必要がある。
