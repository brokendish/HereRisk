# Phase 2-C.1 Source Catalog / Identity Contract 検討記録

- Task: Phase 2-C.1 Source Catalog / Identity Contract Finalization
- 作成: 2026-10-25（Claude）
- 基準コミット: `07aeddd4452ca99ebfcbbcef5fa606ff569b8c2f`
- 種別: 実装契約案の作成。製品コード・実データ・Registry実体・Docker・VPSは変更していない
- 上位: [ADR-001](../../docs/decisions/2026-10-25-multiple-official-hazard-results.md)、[Design Principles](../../docs/architecture/design-principles-v1.0.md)、[Flood Official Data Presentation Contract](../../docs/architecture/flood-official-data-presentation-contract-v0.1.md)
- Codexの独立監査: **未実施**

本工程は実装契約案の作成であり、OWNERの正式承認・実データの処理・公開を意味しない。公式の結果の比較・順位付け・代表値・集約・危険度判定は追加していない（ADR-001）。Phase 2-B.9〜B.16の旧方式は根拠にしていない。

## 1. 成果物

| No | 成果物 | 場所 |
|---|---|---|
| 1 | Source Catalogと識別子の設計契約案 | [flood-source-catalog-identity-contract-v0.1.md](../../docs/architecture/flood-source-catalog-identity-contract-v0.1.md)（以下「本契約」） |
| 2 | JSON Schema案 | `docs/architecture/schemas/`: [Catalog](../../docs/architecture/schemas/flood-source-catalog.schema.json)、[割当台帳](../../docs/architecture/schemas/flood-source-identity-ledger.schema.json)、[区分の割当記録](../../docs/architecture/schemas/flood-source-category-assignment.schema.json)、[公開用の来歴の要約](../../docs/architecture/schemas/flood-public-lineage-summary.schema.json)、[Catalog Validate Record](../../docs/architecture/schemas/flood-source-catalog-validate-record.schema.json) |
| 3 | ID生成・維持・参照の規則 | 本契約 第2章・第4章 |
| 4 | 代表的なJSON例（すべて架空） | [Catalog](../../docs/architecture/schemas/flood-source-catalog.example.json)、[公開用の来歴の要約](../../docs/architecture/schemas/flood-public-lineage-summary.example.json)、[割当台帳](../../docs/architecture/schemas/flood-source-identity-ledger.example.json) |
| 5 | 既存契約への影響一覧 | 第3章 |
| 6 | OWNER判断事項 | 第4章 |
| 7 | 実装前Blockingの残件 | 第5章 |
| 8 | Codex独立監査向けの反例と受入条件 | 第6章（本契約 第9章） |

## 2. 設計の要点

- **識別子の責務の分離**（本契約 第2章）: 公開用は `source_id`（公式データの系列）・`zone_ref`（区域）・`product_ref`（成果品への参照）・`lineage_ref`（公開用の来歴の要約への参照）。内部用は `product_id`・`record_key`（既存の定義を置き換えない）。
- **生成方式**（本契約 第4章）:
  - `source_id` は**割当台帳**で割り当てる。同じ系列のデータが更新されても同じ公式データとして識別する必要があり、内容由来では更新のたびに変わるためである。再利用はしない。
  - `product_ref`・`zone_ref`・`lineage_ref` は**内容由来**（ドメインを分けた正規化JSONのSHA-256）。同じ原典なら世代をまたいで同じ値になり、原典の更新で変わる。ファイル名・メンバー名を含まない。
- **粒度**（本契約 第3章）: A（公表主体単位）・B（公表主体×想定条件×配布系列）・C（成果品単位）を比較し、**Bを推奨**した（OWNER承認前）。河川別の探索は属性（`rivers`）で行う。
- **継続性**（本契約 第4.1節）: 同じ系列の更新は同じ `source_id` で `source_revision` を増やす。構造的な変更（分割・統合・移動）は新しい `source_id` とする。提示契約 第10章の「所属が変わったソースに旧IDを再利用しない」が構造的な変更を指すことを、本契約で明確にした（提示契約にも注記を追加）。
- **来歴の追跡**（本契約 第4.5節）: 区域 → `product_ref` → `lineage_ref` が指す要約の成果品の項目、の順に公開用でたどる。内部ではCatalogの `products[]` とLineage Manifest（非公開）に戻る。
- **検証**（本契約 第7章）: 提示契約のCV-1〜CV-9を変えずに維持し、識別子の検証 ID-1〜ID-6 を追加した。

## 3. 既存契約への影響一覧

| 対象 | 本工程での変更 | 提案する差分（未決定。既存契約は変更していない） |
|---|---|---|
| 提示契約 | 正本の分担に本契約を追加（第2章）。第4.1節・第4.3節・第10章・PD-U1・PD-U2・PD-U10に、本契約への参照・「所属の変更」の明確化を追記 | — |
| API MVP契約 | 第5.3節に、識別子の形式・生成規則への参照を追記 | 本契約の採用時に、正式Schema（FA-U1）で形式を確定（CI-7） |
| Data Publish・Dataset Registry・Integration契約 第9.3節 | なし | 公開世代の構成（Catalog・区分の割当記録・割当台帳の版・来歴の要約・`zone_ref` の対応表）（CI-1） |
| データソース定義 §2 | なし | 割当台帳・区分の割当記録・Catalogの保存先の新設（CI-2） |
| Integration契約 第7.3節 | なし | 阻害理由 `source_catalog_validation_failed`（CI-3） |
| Integration契約 第6.2節 | なし | `zone_ref` の対応表の格納先（CI-4） |
| 本番実行認可 | なし | 割当・廃止・区分・Catalogの承認記録のSchema（CI-5） |
| Data Publish（世代の保持） | なし | 来歴の要約の保持の規則の適用の確認（CI-6） |
| Normalize・Integrationの処理、他のハザードの契約、公開認可・ライセンス条件 | なし | なし |

## 4. OWNER判断が必要な事項

本契約 第10章の CI-U1〜CI-U8。特に次のとおり。

1. **CI-U1**: `source_id` の粒度をB（公表主体×想定条件×配布系列）とすること。
2. **CI-U2**: `source_id` を割当台帳で管理し、割当・廃止にOWNERの承認を要すること。他の公開用の参照は内容由来とすること。
3. **CI-U3**: 同じ系列の更新（成果品の追加・削除を含む）を「所属の変更」に含めない解釈。
4. **CI-U4**: `product_ref` の採用と、公開用の来歴の要約に原典の配布ファイル名を含めないこと（含める場合は、共通API契約 §5「ファイル名を公開しない」との関係を判断する）。
5. **CI-U5**: ハッシュの長さ（`product_ref` 16桁・`zone_ref` 20桁）。衝突は検証で不合格にする。
6. **CI-U6**: `zone_ref` の対応表を公開世代のsidecarに置く案。
7. **CI-U7・CI-U8**: 追加契約（保存先・公開世代の構成・承認記録）の設計の進め方、原典の基準日の扱い。

いずれも本書では承認済みとして扱っていない。

## 5. 実装前Blockingの残件

**本工程で解消したとは扱わない**もの:

1. 本契約・提示契約・API契約のOWNERの正式承認（CI-U1〜CI-U8を含む）。
2. 公開世代の構成・保存先・Readinessの阻害理由・承認記録のSchemaの追加契約（CI-1〜CI-3・CI-5・CI-6。提示契約 PD-C1〜PD-C4）。
3. 正式なレスポンスSchemaとHTTPの対応（API契約 FA-U1・FA-U10）。
4. Phase 2-B.8の実装前Blocking（[対応表](phase2b8-codex-audit-remediation.md) 第5章）。妥当性モデル・判定器・独立検証の方式・依存の版、Normalize・IntegrationのSchema・ハッシュ形式、資源上限、RTree方式、地域定義など。**本工程の変更はこれらを解消しない。**
5. Flood用のSource Definition・各Record・認可プロファイル（Integration契約 OI-17）。
6. 公開前の条件: A31a・N03の利用条件、出典・加工表示（`attribution.license`・`url` が `null` のままでは公開できない）、全対象入力の検証、OWNERの公開承認。実データの処理・派生形状・L2は引き続きBLOCKED。

## 6. Codex独立監査向けの反例と受入条件

反例 CE-1〜CE-10と受入条件（許容する状態・拒否する状態・検証箇所）は、本契約 第9章が正本である。監査で確認してほしい観点は次のとおり。

- 識別子の責務（本契約 第2章）に重複・欠落がないか。公開用の参照から内部の識別子・ファイル名が導けないか。
- `source_id` の割当台帳と、内容由来の参照の組合せで、世代の切替・原典の更新・構造的な変更（CE-4・CE-5・CE-10）が一意に扱えるか。
- CV-1〜CV-9（提示契約）とID-1〜ID-6（本契約）の組合せで、CE-6〜CE-9が必ず検出されるか。
- 本文の項目表（本契約 第5章）とSchema案の型・必須性・nullが一致しているか。
- 比較・順位付け・集約・危険度判定が持ち込まれていないか。
- 既存のRegistry・Publish・Authorizationの正式仕様を変更・確定していないか。

## 7. 本工程で行った確認（実施したもの）

プロジェクトの既存の依存（`.venv` の `jsonschema` 4.26.0）を使い、作業用ディレクトリの確認用スクリプトで次を確認した。スクリプトはリポジトリに追加していない。

| 確認 | 結果 |
|---|---|
| 5つのSchema案の妥当性（Draft 2020-12） | 全件PASS |
| 3つのJSON例のSchemaへの適合 | 全件エラー0 |
| 例の `product_ref`・`lineage_ref`・割当台帳の内容ハッシュを、本契約 第4章の規則で再計算 | 一致 |
| 公開用の来歴の要約の例に、`product_id`・ZIPメンバー名・`zip_member` が含まれない（ID-6） | 含まれない |
| 反例のSchemaでの拒否: 空の目録、目録の `unclassified`、他のシナリオ、意味を持つ `source_id`、廃止した項目（`deeper_in_other_sources`）、要約への `product_id`・`zip_member` の追加、`retired_at` を持つ `active` のエントリ | 全件拒否 |

これらはSchema案と例の自己整合の確認である。製品の実装・実データでの検証ではない。Schemaで表せない検証（二重登録・一意性・ハッシュの再計算・集合の照合・漏えい）は、Source Catalog Validateの実装と試験で確認する必要がある（本契約 第6章の注記）。

## 8. 本工程で確認していないこと

1. Codexの独立監査は未実施である。
2. 実データでの識別子の生成・衝突の評価は行っていない（CI-U5）。
3. 本書は実装契約案であり、OWNERの正式承認・実装の開始・実データの処理・公開を意味しない。
