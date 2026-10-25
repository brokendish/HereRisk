# Phase 2-B.12 Codex Source Selection監査指摘 対応表

- Task: Phase 2-B.12 Codex Source Selection Audit Remediation
- 作成: 2026-10-25（Claude）
- 監査: Phase 2-B.11 Codex独立契約監査（OWNERから提供された全文を一次資料とする）。対象コミット `c3ace814c59e62d99c08a9983c4ba021ab570642`
- 監査判定: **FAIL**（CRITICAL 0 / HIGH 3 / MEDIUM 4 / LOW 0）。7件とも Implementation Blocking
- 修正対象: [Flood Source Selection Contract v0.1（案）](../../docs/architecture/flood-source-selection-contract-v0.1.md)（以下「SS」）、[Flood API MVP Contract v0.1（案）](../../docs/api/flood-api-mvp-contract-v0.1.md)（以下「API」）

本書は**契約文書の修正状況**を示す。監査結果の原文は変更していない。変更はMarkdownの3ファイル（上記の2文書と本書）だけで、製品コード・テスト・調査スクリプト・実データ・Registry実体・Docker・VPSには触れていない。Normalize・Integration・共通API・Publish・Registry・Authorizationの契約、Phase 2-B.10の履歴レビュー、旧Priority契約は変更していない。

**本工程は設計文書の修正であり、Codex監査のPASS、実装の開始、製品の公開を意味しない。** Source Selection方式の基本方針（利用者による選択・自動代表選択の廃止・unknownの保持）は維持した。

略記: 監査と同じく、Integration契約を「I」とする。節番号は本改訂後のものである。

> **Phase 2-B.14による訂正の追記（2026-10-25）**: Phase 2-B.13のCodex独立再監査（FAIL: HIGH 1 / MEDIUM 3）で、本書の対応に含まれる記述の不整合が指摘された（B13-01〜B13-04）。本書の元の記述と対応状況は履歴として変更せず、訂正が必要な箇所に「［Phase 2-B.14で訂正］」の注記を追記した。訂正の内容は [Phase 2-B.14 再監査対応表](phase2b14-codex-reaudit-remediation.md) を参照。再監査の判定は、B11-03・B11-06がPARTIALLY RESOLVED、B11-04・B11-05がREGRESSIONであり、本書の「文書上の解決状況」の記載はその判定の前のものである。

文書上の解決状況の区分:

- **RESOLVED（文書）**: 指摘の欠陥を契約から除き、反例に対する受入条件を定めた。再監査・実装では検証していない
- **RESOLVED（文書）＋追加契約待ち**: 本書の範囲では規則を定めたが、既存契約（Integration・Publish・Registry・共通API）への追加が必要な接続点が残る（既存契約は変更していないため）

## 1. 一覧

| ID | 重要度 | 件名（要約） | 文書上の解決状況 | 主な修正箇所 |
|---|---|---|---|---|
| B11-01 | HIGH | unknownポリシー改版時の再統合要件の矛盾 | RESOLVED（文書）＋追加契約待ち（SS-C10） | SS §8.2・§8.3、API §7、SS-17・SS-18、FA-24 |
| B11-02 | HIGH | Catalogと統合成果物の収録完全性・重複の検証規則がない | RESOLVED（文書）＋追加契約待ち（SS-C3・SS-C10） | SS §3.1・§3.3・§3.4、SS-19〜SS-23、FA-25 |
| B11-03 | HIGH | `deeper_in_other_sources` の三値判定が混在ケースで一意でない | RESOLVED（文書）。比較の承認はOWNER判断（SS-U15） | SS §7、API §5.1・§5.6・§8.1、SS-24〜SS-29、FA-19 |
| B11-04 | MEDIUM | ソース状態の条件の重複、`not_evaluated` の位置付け | RESOLVED（文書） | SS §5.1・§5.2、API §5.4・§5.7・§6、SS-30・SS-31、FA-20・FA-21 |
| B11-05 | MEDIUM | 空のSource Catalogの応答が未定義 | RESOLVED（文書）＋追加契約待ち（SS-C3） | SS §3.3・§3.5、API §6、SS-32、FA-22 |
| B11-06 | MEDIUM | 深さ区分の版をAPI上で識別できない | RESOLVED（文書） | SS §5.3・§7、API §5.1・§5.5・§5.6・§8.1、SS-33、FA-23 |
| B11-07 | MEDIUM | 全件保持と応答打切りの接続が未完成 | RESOLVED（文書）。エラーの `status` は共通契約の論点（SS-C11） | SS §5.1、API §5.4・§6、SS-34・SS-35、FA-17 |

## 2. 指摘ごとの対応

### B11-01 — HIGH：unknownポリシー改版時の再統合要件が矛盾する

**元の指摘**: SS（旧307〜314行）は、unknownポリシーを含む設定の変更だけなら同じ統合成果物を参照し「再生成しない」としていた。一方、I 第3.1節（158行）・第11.2節（770行）はポリシー改版時に新Manifestで再統合することを要求し、DB内のポリシー情報とManifestの一致も検証する。そのため、v1のDBにv2を設定した公開世代がSSには適合し、Iには適合しない。

**修正箇所**: SS §8.2（再生成しないとした文を削除）、§8.3（新設）、API §7 `settings.unknown_region`、SS-17・SS-18、API FA-24

**最小修正内容**

- 変更を6つに区分し、統合成果物（DB）を再利用できるかと、必要な手順を表にした（SS §8.3）。
  - 表示順・グルーピングだけの変更は、DBを再利用する（ファイルのSHA-256は不変）。
  - unknownポリシーの改版は、Iの手順で再統合・再検証する。
  - 区分の割当・目録の変更は、所属集合が変わるかどうかで条件を分けた（B11-02の照合の成立、`source_id` の再利用の禁止）。
- 異なるunknownポリシーのDBと公開設定を結び付けないことを明記した。Readiness作成時・Publish直前・APIの起動時・世代の切替時に照合する。
- DBを再利用する場合も、Publication Readiness Recordは公開世代ごとに新規に作る。

**受入条件**

| 反例 | 受入条件 | テスト |
|---|---|---|
| v1のDBとv2のポリシーの組合せ | 照合で拒否する | SS-17、FA-24 |
| 表示順だけの変更 | DBを再生成せず、SHA-256が不変。判定・安全上の情報が同一 | SS-18、FA-14 |
| ポリシー改版 | Manifest・DB・検証記録・公開設定の同一性が成立する（Iの再統合の手順） | SS §8.3 |

**文書上の解決状況**: RESOLVED（文書）＋追加契約待ち。SSとIの矛盾は除いた。ただし、公開世代の `settings.unknown_region` とDBの `metadata` の一致を、IのPublication Readinessの照合項目として追加する必要がある（SS-C10。Iは変更していない）。

**OWNER判断事項**: 変更の区分ごとの承認の主体（特に、表示順だけの変更の承認の軽重。SS-U6）。

**残るBlocking**: 実装前に、公開世代の構成（SS-C1）とReadinessへの照合項目の追加（SS-C10）。公開前に、世代の切替・照合の検証。

---

### B11-02 — HIGH：Catalogと統合成果物の間に、収録完全性・重複の検証規則がない

**元の指摘**: 成果品・Featureの固定と来歴追跡は要求されていたが、公開対象とした統合データの集合とCatalogの所属集合を照合する規則がなかった。未割当Featureの扱いと、同一Featureの複数 `source_id` への重複登録の扱いもない。CatalogにPだけを登録すると、DBに残るQの深い区域・unknownが返らない。Pを2つのソースに登録すると、同じ原典が「他ソース」として数えられる。`candidate_completeness = not_guaranteed` は所属漏れを許す規則にはできない。

**修正箇所**: SS §3.1（粒度と安全上の情報の関係）、§3.3（`products`・`membership_digest`・空の目録の禁止）、§3.4（新設）、SS-19〜SS-23、SS-U12〜SS-U14、API FA-25

**最小修正内容**

- 用語を定義した: 公開対象集合の正本（公開世代のDBの `zone_record` の全行）、原典ハッシュを含むFeatureキー（`record_key`）、入力成果品集合（Manifestの入力の成果品。除外したものは含まない）、所属割当（成果品の組 → `source_id`）。
- 所属は成果品単位で割り当て、Feature・構成Polygon・unknownは `record_key` → 成果品 → `source_id` で一意に解決する。
- 初期MVPでは、同一成果品（同一Feature）の複数 `source_id` への所属を禁止した。別名・別視点の重複所属は将来の拡張として保留した（SS-U12）。
- **Source Catalog Validate**（CV-1〜CV-9）を定義した。照合の内容は次のとおり。
  - 成果品の集合の一致（CV-1）、重複の禁止（CV-2）
  - Featureの未割当の禁止（CV-3）、`search_target`・`unknown_region` の所属の解決（CV-4）
  - ソースごとのFeatureキー集合のハッシュの一致（CV-5。件数の一致だけでは合格しない）
  - シナリオの一致（CV-6）、管理主体の一致（CV-7）
  - 空の禁止（CV-8）、来歴（CV-9）
- 意図的な除外は、目録ではなくIntegration Manifestの除外（理由とOWNERの承認記録）で行う。目録だけで、DBにあるFeatureを除外・非表示にできない。
- `candidate_completeness = not_guaranteed` は登録外の外部の公表データについての注意であり、所属漏れを許さないと明記した。
- 監査 §5の指摘を反映した。`source_id` の粒度（提供主体単位か成果品単位か）は、安全上の情報の意味を変える。粒度は、所属集合・IDの継続性とあわせて確定する。

**受入条件**

| 反例 | 受入条件 | テスト |
|---|---|---|
| 成果品1つの欠落 | CV-1で拒否 | SS-19 |
| 同件数でのFeatureの差替え | CV-5で拒否 | SS-20 |
| unknownだけを持つFeatureの未割当 | CV-3・CV-4で拒否 | SS-21 |
| 同一Featureの二重所属 | CV-2で拒否 | SS-22 |
| シナリオの混在 | CV-6で拒否 | SS-23 |
| 管理主体の混在 | CV-7で拒否 | SS §3.4 |

**文書上の解決状況**: RESOLVED（文書）＋追加契約待ち。照合の規則は定めた。ただし、Source Catalog Validate RecordをIのPublication Readinessの阻害理由・照合対象に加える必要がある（SS-C3・SS-C10。Iは変更していない）。

**OWNER判断事項**

- `source_id` の粒度（SS-U1）。安全上の情報の意味が変わることを含めて判断する。
- 重複所属の将来の扱い（SS-U12）。
- 意図的な除外の承認（SS-U13）。
- 所属集合が変わる目録の変更の承認と、IDの継続性（SS-U14）。

**残るBlocking**: 実装前に、目録・所属割当・Source Catalog Validate RecordのSchemaと保存先（SS-C2）、`source_id`・`zone_ref` の生成規則（SS-U4）。公開前に、所属漏れ・重複の否定試験。

---

### B11-03 — HIGH：`deeper_in_other_sources` の三値判定が混在ケースで一意にならない

**元の指摘**: 複数ソースをまとめる優先規則がなかった。選択Aが3〜5mで、Bが比較可能な5〜10m、Cが比較不能な体系のとき、`true` と `null` のどちらが優先するか明記されていない。Bが浅くCだけ比較不能の場合も、比較可能な結果だけで `false` にする実装を排除できない。APIの例では、他ソースがunknownのみで `false` になっており、一般規則との接続が不明確だった。

**修正箇所**: SS §7（三値判定の全面改訂）、API §5.1（`deeper_comparison` と例の説明）、§5.6、§8.1、SS-24〜SS-29、API FA-19

**最小修正内容**

- 比較の対象を「選択していない全ソースの全確認済み区域」とした。ソース内の集約の結果ではなく、個別の区域を対象とする。unknown・境界接触は比較の対象にせず、独立して保持する。
- 各区域を `deeper`・`not_deeper`・`incomparable` に分類し、判定の順序（7段階）を定めた。基本の順序は監査の推奨どおりで、(1) 深い区域が1件でもあれば `true`、(2) なければ、比較不能が1件でもあれば `null`、(3) 必要な比較が成立して深い区域がなければ `false` である。
- 先に処理する条件を3つ置いた。選択中に確認済みの該当がない場合は `null`、選択中の `depth` が `null` の場合は `null`、他ソースが0件の場合は `false` である。
- 他ソースに確認済み区域が0件の場合（unknownのみ・該当なし）は `false` とし、`basis` で区別する。
- `false` は「必要な比較の対象について、より深い確認済みの区域がない」の意味であり、「より深い浸水の可能性がない」ではないと明記した。判定できない場合に `false` へ代替しない。
- 応答に `deeper_comparison`（`basis` と区域の件数）を加えた。
- 必須の10ケースの判定表を作った（SS §7）。

**受入条件**: 監査が挙げた6つの組合せ（深い＋比較不能、浅い＋比較不能、unknownのみ、選択中 `depth = null`、集約不能ソース内の深い区域、他ソース0件）に、該当なし・同じ深さだけ・比較の未承認・選択中に該当なしを加えた10ケースで、値と `basis` が一意に決まる（SS §7の表、SS-24〜SS-29、FA-19）。

- ［Phase 2-B.14で訂正（B13-02・B13-04）］判定の順序を「他ソースに確認済み区域0件 → `false`」を深い区域の判定より前に置く形に整理した。比較を実施しない場合（選択中に該当なし・集約不能）の3つの件数は `null` とした。[Phase 2-B.14 再監査対応表](phase2b14-codex-reaudit-remediation.md)

**文書上の解決状況**: RESOLVED（文書）。

**OWNER判断事項**

- ソース間の比較の承認（`deeper_in_other_sources` の資格）と版の同等性の承認（SS-U15。CQ-1・CQ-3の確認後）。未承認の間は全ケースが `null`（`cross_source_comparison_unapproved`）になる。
  - ［Phase 2-B.14で訂正（B13-02）］「全ケースが `null`」は誤り。承認が結果に影響するのは、比較の対象の区域がある場合だけである。他ソース0件・他ソースに確認済み区域0件では、承認の有無にかかわらず `false`。[Phase 2-B.14 再監査対応表](phase2b14-codex-reaudit-remediation.md)
  - ［Phase 2-B.16で補足（B15-01）］上の訂正注記は、選択側の条件の前提を省略していた。Selection契約 第7章の順1・順2を最優先する。選択中のソースに確認済みの該当がない場合は `null`・`selected_has_no_confirmed_match`、集約の `depth` を作れない場合は `null`・`selected_depth_unavailable` で、いずれも3つの件数はすべて `null`。他ソースの件数・比較の承認の有無で選択側の理由を上書きしない。「他ソース0件・他ソースに確認済み区域0件では `false`」と「未承認なら `null`・`cross_source_comparison_unapproved`」は、**選択中のソースに基準の `depth` がある場合に限る**。正本はSelection契約 第7章であり、規則は追加・変更していない。この補足に対するCodexの再監査は未実施。
- 他ソースがunknownのみの場合に `false` とする規則（監査は、定義すれば即座に否定しないとしている）。

**残るBlocking**: 実装前に、CQ-1〜CQ-8の確認と比較の承認。公開前に、説明文言（`false` を「深い浸水の可能性なし」と誤読させない。FA-U4）。

---

### B11-04 — MEDIUM：ソース状態の条件が重複し、`not_evaluated` の位置付けも不明確

**元の指摘**: 比較不能な該当とunknownが同時にある場合、`partial_unknown` と `aggregation_undetermined` の両方の条件を満たし、状態表に優先規則がない。`not_evaluated` を許す一方、全体の状態表にはその扱いがない。読込み失敗についてはAPI第6章が明確であり、全体を `retrieval_failed` とする規則を採用できる。成功結果を返す別の経路として `not_evaluated` を使わせない整理が必要である。

**修正箇所**: SS §5.1（1ソースの失敗で応答全体をエラーにすること）、§5.2（全面改訂）、API §5.4・§5.7・§6、SS-30・SS-31、API FA-20・FA-21

**最小修正内容**

- 事実を独立して保持するようにした: `has_confirmed_match`・`has_unknown`・`has_boundary_contact`・`aggregation`・`evaluation`・`service_region_relation`。APIでも事実を返す。
- `assessment_status` の導出順序（順0〜6）を定めた。集約不能は順2で優先する。そのため、集約不能とunknown・境界接触が同時に成り立っても、状態名は `aggregation_undetermined` の1つに決まる。全理由は `uncertainty_reasons` に残る。
- `not_evaluated` を予約値に移した。ソースごとにサービス対象地域が異なる将来の構成に限って使う。MVPの正常応答には現れない。読込み失敗・異常を `not_evaluated` で表さない。
- 1つのソースでも評価に失敗すれば、応答全体を `retrieval_failed` 等とする（成功したソースだけの成功応答にしない）。
- `overall_status` の決定表を作った。入力は全ソースの状態（`not_evaluated` を含む）で、出力は4値である。`aggregation_undetermined` を含む場合は `partial_unknown` とした。

**受入条件**: 集約不能＋unknown＋境界接触が同時に成り立っても、状態名が1つに決まり、全理由が残る（SS-30、FA-20）。A成功・B失敗では全体が `retrieval_failed` になる（SS-31、FA-21）。許される全ソース状態から `overall_status` を導出できる（SS §5.2の決定表）。

**文書上の解決状況**: RESOLVED（文書）。

**OWNER判断事項**: 集約不能を `overall_status` の独立の値にしないこと（本書は `partial_unknown` に含める提案）。

**残るBlocking**: 実装前に、正式なレスポンスSchema（FA-U1）。

---

### B11-05 — MEDIUM：空のSource Catalogの応答が定義されていない

**元の指摘**: Catalogの最小件数と、空の場合の公開資格・API応答がない。全体の状態表を空集合に適用すると `success`・`no_match_extent_unknown` にできる一方、未公開なら `no_data`、不整合なら `indeterminate` になり、実装に依存する。

**修正箇所**: SS §3.3（目録は1件以上、各ソースは成果品1件以上）、§3.4 CV-8、§3.5（新設）、API §6、SS-32、API FA-22

**最小修正内容**

- 初期MVPでは、空の目録の公開を阻害する（CV-8の不成立。Publication ReadinessをBLOCKEDとする方式を第一候補とする）。
- 4つの状況を区別した（SS §3.5）。
  - 未公開: `no_data`・`flood_not_published`
  - 空の目録: 公開しない。万一読んだ場合は `indeterminate`・`flood_integrity_error`
  - 非空の目録で該当0件: `success`・`no_match_extent_unknown`
    - ［Phase 2-B.14で訂正（B13-01）］状態はSS §5.2で導出する。unknown・境界接触・外縁上があれば `unknown_only`、地域の内部でいずれもなければ `no_match_extent_unknown`。[Phase 2-B.14 再監査対応表](phase2b14-codex-reaudit-remediation.md)
  - 地域外: `no_data`・`outside_service_region`
- 空の目録を「浸水想定なし」と解釈しない。意図的な空の世代は、別の契約とOWNERの承認を必要とする（SS-U16）。

**受入条件**: 上の4ケースが規定どおりに分類される（SS-32、FA-22）。

**文書上の解決状況**: RESOLVED（文書）＋追加契約待ち（Readinessの阻害理由への追加。SS-C3）。

**OWNER判断事項**: 空の目録の公開を阻害する方式の採否。意図的な空の世代の将来の扱い（SS-U16）。

**残るBlocking**: 実装前に、Readinessへの阻害理由の追加（SS-C3）。

---

### B11-06 — MEDIUM：深さ区分の版をAPI上で識別できない

**元の指摘**: 比較の条件は体系ID・版・コードだが、APIの `depth` には体系IDだけが定義されていた。JSON例の `matches[].depth` には体系IDもない。同じ体系ID・コードで版が異なる区域を、利用者が区別できない。

**修正箇所**: SS §5.3（区分の同一性のキーと比較の資格）、§7（`depth_classes_present` の構造）、API §5.1・§5.5・§5.6・§8.1（全 `depth` に `scheme_id`・`scheme_version`・`class_code`）、SS-33、API FA-23

**最小修正内容**

- 区分の同一性のキーを（`scheme_id`, `scheme_version`, `class_code`）とした。ソース内の集約、`matches[]`、`depth_classes_present`、安全上の比較で同じキーを使う。
- 同じID・コードでも、版が異なれば別の区分とし、重複排除でまとめない。版の同等性が承認された場合だけ比較可能にし、その場合もキーは版ごとに返す。
  - ［Phase 2-B.14で訂正（B13-03）］MVPでは版の同等性による比較・集約を行わず、異なる版は常に比較不能とする。版の同等性は将来の拡張（SS-U17）。[Phase 2-B.14 再監査対応表](phase2b14-codex-reaudit-remediation.md)
- 比較の資格を2段階にした。ソース内の集約は同じ体系・同じ版だけを要件とする。安全上の比較（ソース間）は、加えてソース間の比較の承認を要件とする。
  - ［Phase 2-B.14で訂正（B13-03）］比較の資格は、`scheme_id`・`scheme_version`・区分体系の比較規則の3つの一致とした。
- APIの全 `depth`（例を含む）に `scheme_id`・`scheme_version`・`class_code` を持たせた。旧名 `scheme` は `scheme_id` に改めた。
- `depth_classes_present` の各要素に、キー・`label`・区間・`source_ids` を持たせた。並び順の根拠も `ordering` で示す。

**受入条件**: 同じID・コードで版だけ異なる2件が区別される。集約の `depth`・個別の `match`・`overview` で同じ識別規則を使う（SS-33、FA-23）。

**文書上の解決状況**: RESOLVED（文書）。

**OWNER判断事項**: 版の同等性の承認（SS-U15）。

- ［Phase 2-B.14で訂正（B13-03）］版の同等性の承認はMVPの対象外となり、SS-U17（将来の拡張）へ移した。

**残るBlocking**: 実装前に、浸水ランクコードの版の確認（CQ-1）。

---

### B11-07 — MEDIUM：全件保持と応答打切りの接続が未完成

**元の指摘**: 全該当・全unknownの返却を要求する一方、APIは `truncated` と全件数があれば打切りを許していた。どの配列を打ち切るのか、残りをどう取得するのか、`contributing_zones` との参照整合性が未定義である。最深の区域が返却の範囲外になると、寄与区域の詳細を応答から取得できない。黙った切捨ての禁止は明確だが、通知付きの切捨てと全件保証の関係が未完成である。

**修正箇所**: SS §5.1（全対象での計算）、API §5.4（全件返却・上限超過のエラー・`contributing_zones` の参照整合）、§6（`flood_response_limit_exceeded`）、§13 FA-U7、SS-34・SS-35、API FA-17

**最小修正内容**

- 初期MVPでは、全ソース・全確認済み区域・全unknown・全境界接触を1つの応答で返す。`truncated` による通知付きの切捨ても廃止した。
- 受入可能な上限を超える場合は、正常な部分結果として返さず、明示的なエラー（`flood_response_limit_exceeded`）とする。エラーに件数・内部の詳細・診断情報を含めない。上限の値は性能検証の後に確定する（FA-U7）。
- ソース内の集約・`overall_status`・安全上の情報は、常に全対象を使って計算する。成功応答では、`contributing_zones` の参照先がすべて `matches[]` に含まれる。
- 将来の部分返却は、公開世代を固定したカーソル方式など、全件の取得を保証する独立の契約とする（MVPの対象外）。

**受入条件**: 上限の直後に最深の区域・unknown・同じ深さの寄与区域がある場合でも、部分結果を返さない。上限の内側なら全件を返し、要約が変わらない（SS-34・SS-35、FA-17）。

**文書上の解決状況**: RESOLVED（文書）。上限超過のエラーの `status` を `retrieval_failed` とする提案は、共通API契約の分類への当てはめであり、未承認である（SS-C11）。

**OWNER判断事項**: 上限の値（FA-U7）。上限超過のエラーの `status`（SS-C11）。

**残るBlocking**: 実装前に、性能の測定と上限の確定（I OI-15と関係）。

## 3. 必須回帰ケースとの対応

| No | 指示された回帰ケース | 契約上のテスト |
|---|---|---|
| 1 | unknownポリシーv1のDBにv2の設定を結び付ける | SS-17、FA-24 |
| 2 | 表示順だけを変更して同じDBを利用する | SS-18、FA-14 |
| 3 | Catalogから成果品を1つ欠落させる | SS-19 |
| 4 | 所属件数を維持してFeatureキーを差し替える | SS-20 |
| 5 | unknownだけを持つFeatureの所属を欠落させる | SS-21 |
| 6 | 同一Featureを異なる `source_id` へ二重登録する | SS-22 |
| 7 | 選択3〜5m、他5〜10m＋比較不能 | SS-24 |
| 8 | 選択3〜5m、他0.5〜3m＋比較不能 | SS-25 |
| 9 | unknownのみの他ソース | SS-26 |
| 10 | 選択 `depth = null` | SS-27 |
| 11 | 他ソース0件 | SS-28 |
| 12 | 集約不能ソースに深い個別区域が存在 | SS-29 |
| 13 | 集約不能＋unknown＋境界接触が同時成立 | SS-30、FA-20 |
| 14 | A成功・B読込み失敗 | SS-31、FA-21 |
| 15 | 空Catalogと非空Catalogの該当0件 | SS-32、FA-22 |
| 16 | 同一区分ID・コードで版が異なる | SS-33、FA-23 |
| 17 | 応答上限直後に最深区域が存在 | SS-34、FA-17 |
| 18 | 応答上限直後にunknownが存在 | SS-35、FA-17 |
| 19 | 同深度の寄与区域が応答上限外にある | SS-35、FA-17 |
| 20 | Source Selectionを変更しても他ソースの地点判定結果が変わらない | SS-36、FA-05 |

いずれも設計上の受入条件であり、テストコードは作成も実行もしていない。シナリオの混在（SS-23）は、監査の反例14への対応として追加した。

## 4. 監査の必須反例18件のうち、未確定・非一意だったものの扱い

| 監査 No. | ケース | 監査の評価 | 本改訂後 |
|---|---|---|---|
| 4 | 都unknown、国3〜5m、国選択 | 部分的に未確定（`deeper` の一般規則と例の接続） | SS §7の順6で `false`（`no_confirmed_match_in_other_sources`）。都のunknownは `has_unknown_in_other_sources = true`。`overall_status = partial_unknown`。［Phase 2-B.14で訂正］順序の整理により順4（値は同じ） |
| 5 | 都3〜5m、国unknown、都選択 | 部分的に未確定 | No.4と対称で、同じ規則による |
| 7 | 同じソースの比較不能2区分（unknownも重なる場合） | unknownが重なる場合はB11-04 | SS §5.2の順2で `aggregation_undetermined`、理由を全件保持 |
| 9 | 空Catalog | 非一意 | SS §3.5。公開を阻害。読んだ場合は `indeterminate` |
| 14 | 同一 `source_id` に異なるシナリオ | 初期契約の許容外。拒否条件が必要 | CV-6で拒否（SS-23） |
| 16 | 異なる区分体系の重複 | 混在時の三値の集約と区分の識別はB11-03・B11-06 | SS §5.3の同一性のキー、SS §7の判定の順序 |

監査で一意・条件付きで一意とされた他のケースの規則は、変更していない。

## 5. 残る実装前・公開前のBlocking

**本改訂で既存のBlockingが解消されたとは扱わない。** 監査 §8・§9と、Phase 2-B.8・B.10で管理されている条件を継承する。

**実装前**

1. 本改訂を含むSS・APIのOWNER正式承認。
2. `source_id` の粒度・生成・世代間の継続・再利用禁止の条件（SS-U1・SS-U4・SS-U14）。
3. 目録・所属割当・区分の割当・表示設定・Source Catalog Validate Record・承認記録のSchemaと保存先（SS-C2・SS-C7）。
4. CQ-1〜CQ-8、ソース内の集約、体系の同一性・ソース間の比較の承認（SS-U2・SS-U15）。
5. 共通APIとの論点 FA-C1〜FA-C10、SS-C11、正式なレスポンスSchema、HTTPとの対応。
6. 座標系・精度、妥当性モデル、製品の判定器と独立検証の方式、依存の版の固定（Phase 2-B.8）。
7. Flood用のSource Definition、Acquisition・Validate・ReadinessのRecord、資源上限。
8. Publish・Registryへの世代構成の追加（SS-C1）と、Readinessの照合項目・阻害理由の追加（SS-C3・SS-C10）。Flood用の認可プロファイル。
9. 応答の上限の値（FA-U7）と性能の測定。

**公開前**

1. 実装前Blockingの解消と、承認された契約に基づく検証。
2. 全対象入力の忠実性・妥当性・Integration・Integrated Validateの合格。
3. 残り22成果品の有効Polygon、関東地方整備局の残り37成果品を含む選別の再検証。
4. Catalogの所属漏れ・重複、unknownの欠落、混在Feature、N03の異常、索引の漏れの否定試験。
5. Flood用のPublish・Registry・AuthorizationとReadinessの接続。Publish直前の内容ハッシュ・承認の範囲・有効期限・失効の再確認。
6. 世代の切替・障害・復元・並行要求・旧参照の保持の検証。
7. A31a・N03の利用条件、出典・加工表示の解決。`source_organization` の公開の解釈（FA-C3。未承認）。
8. 説明文言の確定とOWNERの明示的な公開承認。

**引き続き禁止・BLOCKED**: 実データの処理（Flood用の認可プロファイルの成立まで）、派生形状の製品利用、L2。

## 6. 本工程で確認していないこと

1. 本書と改訂した2文書は、Codexの再監査を受けていない。
2. 三値判定・状態の導出・所属の照合を実装・試験していない。テストはすべて設計だけである。
3. 浸水ランクコードの版・閾値が東京都と関東地方整備局で同じかは、確認していない（CQ-1・CQ-3）。
4. 応答の大きさの実測と上限の値は、未検討である。
