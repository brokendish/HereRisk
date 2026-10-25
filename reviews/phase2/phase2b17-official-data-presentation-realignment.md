# Phase 2-B.17 Design Contract Realignment — 公式データ忠実提示方式への全面移行

- Task: Design Contract Realignment（公式データ忠実提示方式への全面移行）
- 作成: 2026-10-25（Claude）
- 基準コミット: `bb7c438d6aa04a741f8d3ee867a0df4002512a48`
- 種別: 設計文書の整合化。製品コード・テストコード・調査スクリプト・実データ・Registry実体・VPS・Dockerは変更していない
- Codexの独立監査: **未実施**（別工程）

## 0. OWNERによる仕様変更［確定］

**現在地に関係する公式防災情報を、原典の内容・出典・条件を保持して、複数あればすべて独立して提供する。**

HereRiskは、異なる公式データの正誤・信頼性・優劣を判定しない。複数の公式データを比較し、独自の代表値や危険度を算出しない。利用者にデータの正当性判断を要求しない。公式データ間の違いが存在することを、利用者が認識できるようにする。原典にない説明や結論を付与しない。検索対象として採用・公開されたデータは、欠落なく返却する。unknown・取得失敗・未収録・評価範囲不明を、安全や危険なしに置き換えない。

これはMVPの縮小ではなく、HereRiskの正式仕様の変更である。

## 1. 変更ファイル一覧

| 区分 | ファイル | 変更の内容 |
|---|---|---|
| 新規（現行の正本） | [docs/architecture/flood-official-data-presentation-contract-v0.1.md](../../docs/architecture/flood-official-data-presentation-contract-v0.1.md) | Floodの公式データ提示の正本。方針・正本の分担・廃止した機能・データソースのモデル・目録・所属の完全性・Discovery・ソースごとの地点検索・結果の区別・提示と絞り込み・公開世代・テスト・未決定事項 |
| 新規 | 本書 | 移行の記録 |
| 全面改訂（現行の正本） | [docs/api/flood-api-mvp-contract-v0.1.md](../../docs/api/flood-api-mvp-contract-v0.1.md) | 入力を `lat`・`lon` だけにし、ソースごと・区域ごとの返却、事実の件数、エラーに改めた。廃止した項目は第12章 |
| 改訂（現行） | [docs/architecture/design-principles-v1.0.md](../../docs/architecture/design-principles-v1.0.md) | 第3.1節（方式）・DP-11を追加。適用欄・照合表・未決定事項を更新。DP-01〜DP-10の原則文は変更なし |
| 改訂（現行） | [docs/project-charter.md](../../docs/project-charter.md) | §5.1（データソースごと・区域ごと）、§5.2（候補を特定し、すべて独立して返す）、§7（評価済み範囲を持たないデータで非該当を確定しない）、§8.2 Dataset Selector |
| 改訂（現行） | [docs/api/common-contract-v0.1.md](../../docs/api/common-contract-v0.1.md) | §4.2（根拠データごと・区域ごと。`not_affected` は評価済み範囲を持つデータだけ）、§6（優先順位・代表値・集約・比較を設けない）、§7の注記、§9 C04・C13、§10「データ選択」 |
| 改訂（現行） | [docs/architecture/flood-integration-contract-v0.1.md](../../docs/architecture/flood-integration-contract-v0.1.md) | 第5章 原則4・OI-6（代表ランクを作らない）、第10章に提示の正本への参照 |
| 改訂（現行） | [docs/architecture/dataset-registry-v0.1.md](../../docs/architecture/dataset-registry-v0.1.md) | §6（重複候補の間に優先順位・統合・代表の選択を設けない） |
| 改訂（現行） | [README.md](../../README.md) | Flood設計の索引（現行の正本・移行の記録・履歴資料）を追加 |
| 改訂（現行） | [docs/development/ai-development-policy.md](../../docs/development/ai-development-policy.md) | 第11節「設計文書の正本と履歴文書」を追加 |
| 履歴として隔離 | [docs/architecture/flood-source-selection-contract-v0.1.md](../../docs/architecture/flood-source-selection-contract-v0.1.md) | 冒頭にSUPERSEDED / HISTORICALの表示を追加。本文は変更なし |
| 履歴として隔離 | [docs/architecture/flood-source-priority-contract-v0.1.md](../../docs/architecture/flood-source-priority-contract-v0.1.md) | 表示を更新（後継のSelection契約も履歴になったこと）。本文は変更なし |
| 履歴として隔離 | `reviews/phase2/phase2b9-…`・`phase2b10-…`・`phase2b12-…`・`phase2b14-…` | 冒頭にHISTORICALの表示を追加。監査判定・日時・観測・対応の記録は変更なし |
| 注記の追加 | `reviews/phase2/phase2a1-…`・`phase2a2-…`・`phase2a3-…`・`phase2a4-…` | 代表ランク（最大値方式）の案が廃止されたことの注記を冒頭に追加。調査結果・観測値は変更なし |

変更していない文書: Normalize契約、Data Publish、本番実行認可、データソース定義、基本アーキテクチャ、標高API契約・パイプライン・運用の文書、決定記録、Phase 0・1・その他のPhase 2のレビュー（第4章で理由を記録）。

## 2. 廃止した機能一覧

正本は [提示契約 第3章](../../docs/architecture/flood-official-data-presentation-contract-v0.1.md)。

| No | 機能 | 旧の所在 |
|---|---|---|
| 1 | 公表主体間の信頼性の順位による自動選択 | Source Priority契約（Phase 2-B.9） |
| 2 | 複数ソースからの唯一の代表浸水深の決定 | 同上、Integration契約 OI-6、Phase 2-A.1〜A.4の `representative_rank` 案 |
| 3 | 異なるソース間の浸水深の大小比較 | Source Selection契約 第7章 |
| 4〜6 | `deeper_in_other_sources`・`deeper_comparison`・`deeper_zones`・`not_deeper_zones`・`incomparable_zones` | Source Selection契約 第7章、API契約 第5.6節 |
| 7 | `cross_source_comparison_unapproved`・比較の承認・`comparison_rule_id`・版の同等性 | Source Selection契約 第5.3節・第7章 |
| 8 | 公式の結果を独自に順位付けする処理 | Source Priority契約 |
| 9 | 独自の最大浸水深・最大ランクの集約（同一ソース内の集約 `deepest_comparable_class` を含む） | Source Selection契約 第5.3節、Integration契約 原則4・OI-6 |
| 10 | 公表の結果から独自の安全・危険判定を生成する処理 | （明示的な機能はなかった。今後も導入しない） |
| 11 | 上記を前提とする状態の導出・比較の資格・版の同等性の契約（`assessment_status`・`overall_status`・`aggregation_undetermined`・`uncertainty_reasons`・`depth_classes_present`） | Source Selection契約 第5.2節・第7章、API契約 第5章 |
| 追加 | サーバ側のソースの選択（`source_id` の入力・`overview`／`single_source`・`selected_by`・`is_selected`・`selected_result_is_exclusive`・状態遷移・関連の入力エラー） | Source Selection契約 第6章、API契約 第3章・第5.2節 |
| 追加 | 全体の該当性の要約（`result.assessment` の `affected`・`undetermined`） | API契約 第5.7節 |

**サーバ側のソースの選択の廃止**は、指示書の廃止リストにない、本工程の判断である。理由は次のとおり。

- 指示書のAPIの基本構造が、座標だけを受け取り、全ソースを返す形である。
- 選択は判定を変えない表示の指定であり、UIの絞り込みで実現できる。
- 選択の状態・エラーの規則が、廃止した比較（「選択中より深い」）の前提だった。

OWNERの確認事項とする（提示契約 PD-U3）。

## 3. 維持した機能一覧

| 機能 | 正本 |
|---|---|
| 原典データの忠実性 | Normalize契約 |
| 原典由来の浸水深区分（コード・定義の文言・区間・版） | 提示契約 第7.2節 |
| 出典・公表主体・対象河川・想定条件・版・来歴 | 提示契約 第4.3節 |
| 地点に対する独立した区域検索 | 提示契約 第7.1節 |
| 複数ソース・複数区域の結果保持（区域ごとに個別に返す） | 提示契約 第7.1節、API契約 第5.3節 |
| unknownと正常な検索結果の区別、同じFeatureの有効部分とunknownの両方の保持 | 提示契約 第7.1節・第8章 |
| 未収録の明示（`candidate_completeness = not_guaranteed`・地域外・未公開） | 提示契約 第6章・第8章 |
| 取得失敗・整合性エラーの明示（1ソースの失敗で応答全体をエラー） | 提示契約 第7.1節、API契約 第6章 |
| Source Catalogの一意性と完全性（CV-1〜CV-9、空の目録の禁止） | 提示契約 第5章 |
| Normalize・Integrationのデータ品質の検証 | Normalize契約・Integration契約（変更なし） |
| Publish・Registry・Authorizationの整合性、Publication Readiness | Integration契約 第7.3節・第9章（変更なし） |
| 利用条件・公開許諾・出典表示 | Integration契約 第9.5節（変更なし）、提示契約 第4.3節 |
| データの世代管理と再現可能性、変更の区分（unknownポリシーの改版は再統合） | 提示契約 第10章、Integration契約 第3.1節・第7.2節 |
| 全件返却と上限超過の明示的なエラー | API契約 第5.4節 |
| 絞り込んでも他の公表結果を参照できること | 提示契約 第9章（APIは常に全ソースを返す） |
| 表示順は信頼性の順位ではない | 提示契約 第9章 |

独自の比較・集約の廃止によって、上の保証を弱めていない。比較・集約のための規則だけを除き、所属の完全性・全件返却・失敗時の全体エラー・世代の照合はそのまま引き継いだ。

## 4. 旧仕様の検出箇所と処理結果

検索語: `deeper_in_other_sources`・`deeper_comparison`・`selected_depth`・`aggregation_undetermined`・`representative`・`representative_depth`・`source_priority`・`priority_order`・`max_rank`・`最大ランク`・`代表浸水深`・`代表値`・`深さ比較`・`ソース間比較`・`同等性承認`・`comparison_rule_id`・`assessment_status`・`overall_status`・`source_selection`・`信頼性順位`・`自動優先`・`危険判定`・`安全判定`。加えて、同じ意味の `代表ランク`・`最大値方式`・`優先順位`・`ソース間の比較`・`depth_classes_present`・`incomparable`・`single_source` 等。製品コード・テストコード（`src/`・`tests/`）には該当がなかった。

区分: **A** 現行の規範文書を新仕様に修正、**B** 現行文書から旧仕様への参照を修正、**C** 過去の記録として残し現行仕様ではないことを明示、**D** 無関係のため維持

| ファイル | 検出内容 | 区分 | 処理 |
|---|---|---|---|
| `docs/api/flood-api-mvp-contract-v0.1.md` | `representative`系・`deeper_*`・`assessment_status`・`overall_status`・`selection`・`depth`の集約 等（57行） | A | 全面改訂。廃止した項目は第12章に一覧化（禁止の文脈だけで残る） |
| `docs/architecture/flood-source-selection-contract-v0.1.md` | 比較・集約・状態の導出・選択（85行） | C | HISTORICALの表示。引き継ぐ規則は提示契約へ移した |
| `docs/architecture/flood-source-priority-contract-v0.1.md` | 優先順位・代表結果・集約（52行） | C | HISTORICALの表示を更新 |
| `docs/architecture/design-principles-v1.0.md` | 適用欄の `assessment_status`・`deeper_in_other_sources`・Selection契約への参照、C-6〜C-8 | A・B | 適用欄・照合表を更新。DP-11を追加 |
| `docs/project-charter.md` | §5.1「想定浸水深」（単数）、§5.2「適切なデータセットを選択」、§7、§8.2 Dataset Selector（同じ意味の記述） | A | 改訂 |
| `docs/project-charter.md` | §6「独自の総合危険度スコア」（MVP 0で実装しない機能） | D | 新仕様と整合（独自の危険度を作らない）のため維持 |
| `docs/api/common-contract-v0.1.md` | §6「複数データセットの優先順位、集約…はUNDECIDED」、§4.2 `affected`・`not_affected`、C13「承認された選択契約」、§10「重複優先順位・集約」 | A | 改訂 |
| `docs/api/common-contract-v0.1.md` | §4.1「標高値から独自の危険度・安全判定を生成しない」、§4.2「架空の代表値を作らない」、§3.1「エラーコード体系の優先順位」 | D | 新仕様と整合、または無関係（エラーの分類）のため維持 |
| `docs/architecture/flood-integration-contract-v0.1.md` | 第5章 原則4「最大ランク方式は候補」、OI-6 | A | 「代表ランクを作らない」に改訂 |
| `docs/architecture/flood-integration-contract-v0.1.md` | 第7.3節「優先順位で1つに絞らない」（阻害理由）、第10章「unknownを安全判定に変換しない」 | D | 無関係、または新仕様と整合のため維持。第10章には提示の正本への参照を追加 |
| `docs/architecture/flood-normalize-contract-v0.1.md` | 「unknownを安全判定に変換しない」、資源上限の「最大値」 | D | 新仕様と整合、または無関係 |
| `docs/architecture/dataset-registry-v0.1.md` | §6「重複候補の優先順位・統合・競合時の扱いは未決定」 | A | 「優先順位・統合・代表の選択を設けない」に改訂 |
| `docs/architecture/basic-architecture-v0.1.md` | 設定の上書きの優先順位、「最大値・最新優先等で独断選択しない」 | D | 設定の階層の優先順位は無関係。独断選択の禁止は新仕様と整合 |
| `docs/architecture/data-source-definition-v0.1.md` | 「コード順は処理順・優先順位を意味しない」 | D | 無関係 |
| `docs/api/elevation-contract-v0.1.md` | 「全国拡張時の複数ソース優先順位」は後続判断 | D | 標高の正当な処理であり、洪水の比較の廃止だけを理由に変更しない。複数の標高データを扱う時点でDesign Principlesに照合する（Design Principles C-9・DP-U7） |
| `README.md` | Floodの文書の索引がなかった | B | 現行の正本・履歴資料を区別した索引を追加 |
| `docs/development/ai-development-policy.md` | 正本と履歴文書の扱いの規定がなかった | B | 第11節を追加 |
| `reviews/phase2/phase2b9-…`・`phase2b10-…`・`phase2b12-…`・`phase2b14-…` | 優先順位・比較・集約・状態の導出の対応（多数） | C | HISTORICALの表示 |
| `reviews/phase2/phase2a1-…`・`phase2a3-…` | `representative_rank`・最大値方式を第一候補 | C | 廃止の注記 |
| `reviews/phase2/phase2a2-…`・`phase2a4-…` | 代表ランクの方式（O-7・U-4）、「該当点での最大ランクの分布」（観測値） | C | 廃止の注記。観測値は改変しない |
| `reviews/phase2/phase2b6-…` | 「unknownを安全判定に変換しない」 | D | 新仕様と整合 |
| `reviews/phase2/phase2b8-…` | 「優先順位で1つに絞らない」（阻害理由） | D | 無関係 |
| `reviews/phase0/common-hazard-api-contract-v0.1.md`・`basic-architecture-design-v0.1.md` | 「複数根拠と地域境界の優先順位」は未決定（当時の検証サマリー）、設定の優先順位の例外 | C・D | 当時の検証記録であり、共通API契約の現行の正本（§6）が改訂済み。変更しない |
| `reviews/phase1/phase1b3a-…` | 「65536要素の最大値の表現」 | D | 無関係（標高のデータの大きさ） |

再検索の結果（現行の文書）: 廃止した項目の名前は、提示契約 第3章・API契約 第5.1節冒頭と第12章・FA-07などの「廃止・禁止」の文脈にだけ現れる。Design Principles・AI作業規約・README・共通API・プロジェクト定義書にも、「行わない」という禁止の記述として現れる。それ以外の現行の文書には現れない。

## 5. 現行・履歴文書の区分一覧

| 区分 | 文書 |
|---|---|
| **現行（最上位）** | Design Principles |
| **現行（プロジェクト）** | プロジェクト定義書、AI共通作業規約、README |
| **現行（共通）** | 共通API契約、基本アーキテクチャ、Dataset Registry、Data Publish、データソース定義、本番実行認可、個人実験の契約 |
| **現行（Flood。契約案）** | Flood Official Data Presentation Contract、Flood API MVP Contract、Flood Normalize Contract、Flood Integration Contract |
| **現行（標高）** | 標高API契約、標高のパイプライン・運用の文書、決定記録（変更なし） |
| **履歴（SUPERSEDED / HISTORICAL。実装根拠として使用禁止）** | Flood Source Priority Contract、Flood Source Selection Contract、Phase 2-B.9・B.10・B.12・B.14のレビュー |
| **記録（調査・監査の記録。現行の規則の正本ではない）** | Phase 2-A.1〜A.4（代表ランクの案は廃止の注記つき）、Phase 2-B.2〜B.8のレビュー、Phase 0・1のレビュー |

Phase 2-B.11・B.13・B.15・B.16の監査結果・修正は、OWNERとの会話とB.12・B.14の対応表・コミットに記録されている。B.16の修正（コミット `bb7c438`）はAPI契約とB.12対応表への追記だった。いずれも、廃止した機能に関するものである。

## 6. 未決定事項とBlocking

### 6.1 未決定事項（現行）

| 管理先 | 事項 |
|---|---|
| 提示契約 PD-U1〜PD-U9 | `source_id` の粒度・ID生成と継続性・サーバ側の絞り込みの要否（PD-U3。本工程の判断の確認を含む）・原典の区分の表現の確認事項・文言・表示設定の承認・`other` の資格・重複所属・除外と空の世代 |
| API契約 FA-U1・FA-U4〜FA-U12、FA-C1・C3・C4・C6・C9・C11 | 正式Schema・文言・unknownの区域のランク・上限値・公開停止の区別・座標系・エンドポイント・内水のみの成果品・`not_included_notice`、共通APIとの論点 |
| 提示契約 PD-C1〜PD-C5 | 公開世代の構成・目録の保存先・Readinessの阻害理由と照合項目・承認記録のSchema・unknownの区域のランク |
| Design Principles DP-U1・DP-U3〜DP-U7 | プロジェクト定義書との上下関係、視点の実現、違いの理解の支援、不確実性の正式な表現、UIの見せ方、他のハザードへの適用 |
| Normalize・Integration契約の ON-*・OI-* | 変更なし（OI-6は廃止） |

### 6.2 Implementation Blocking（実装前）

1. 本工程を含む設計の**OWNERの正式承認**（Design Principlesの改訂、提示契約、API契約、プロジェクト定義書・共通APIの改訂）。
2. Phase 2-B.8の実装前Blocking（[対応表](phase2b8-codex-audit-remediation.md) 第5章）。妥当性モデル・判定器・独立検証の方式・依存の版、Schema・ハッシュ形式、資源上限、RTree方式、地域定義など。
3. 目録・所属割当・区分の割当・表示設定・Source Catalog Validate Record・承認記録のSchemaと保存先（PD-C2・PD-C4）。
4. 公開世代の構成の追加契約（PD-C1）と、Publication Readinessの阻害理由・照合項目の追加（PD-C3）。
5. `source_id` の粒度・生成規則（PD-U1・PD-U2）。
6. 正式なレスポンスSchema・HTTPとの対応・エンドポイント（FA-U1・FA-U10）、共通APIとの論点（FA-C*）。
7. API入力の座標系・精度（FA-U9）、応答の上限値と性能評価（FA-U7）。
8. Flood用のSource Definition・各Record・認可プロファイル（Integration契約 OI-17）。

### 6.3 Publication Blocking（公開前）

1. 実装前Blockingの解消と、承認された契約に基づく検証。
2. 全対象入力の忠実性・妥当性・Integration・Integrated Validateの合格。残り22成果品の有効Polygonと、関東地方整備局の残り37成果品を含む。
3. 所属漏れ・重複・unknownの欠落・混在Feature・N03の異常・索引の漏れの否定試験。
4. Flood用のPublish・Registry・AuthorizationとReadinessの接続。Publish直前のハッシュ・承認の範囲・期限・失効の再確認。
5. 世代の切替・並行要求・障害・復元・旧参照の保持の検証。
6. **A31a・N03の利用条件、出典・加工表示の解決**（Integration契約 第9.5節・OI-10・OI-11）。`source_organization` の公開の解釈（FA-C3。未承認）。
7. 説明文言の確定（FA-U4・PD-U5）と、OWNERの明示的な公開承認。

**引き続き禁止・BLOCKED**: 実データの処理（Flood用の認可プロファイルの成立まで）、派生形状の製品利用、unknownのL2。本工程はこれらを解除していない。

## 7. 今回の変更で対象がなくなった旧Findingの扱い

**廃止した機能に対する旧Findingは、新仕様のImplementation Blockingとして残さない。** 監査判定・日時・観測は、各記録のまま改変していない。

| 旧Finding | 内容 | 新仕様での扱い |
|---|---|---|
| B11-01 unknownポリシーの改版と再統合 | DBと公開設定のポリシーの一致 | **維持**（提示契約 第10章）。現行のBlocking（PD-C3の照合項目） |
| B11-02 Catalogの所属の完全性 | CV-1〜CV-9 | **維持**（提示契約 第5章）。現行のBlocking（PD-C2・PD-C3） |
| B11-03 `deeper_in_other_sources` の三値判定 | ソース間の比較 | **対象消滅**（機能を廃止） |
| B11-04 ソース状態の導出順序 | `assessment_status`・`overall_status` | **対象消滅**（派生状態を廃止）。要求のうち「1ソースの失敗で応答全体をエラー」「読込み失敗を正常な状態にしない」は提示契約 第7.1節に維持 |
| B11-05 空のSource Catalog | 公開の禁止・4状況の区別 | **維持**（提示契約 第5章・第8章） |
| B11-06 浸水深区分の版の識別 | `scheme_id`・`scheme_version`・`class_code` | **一部維持**: 区域ごとの区分の識別（提示契約 第7.2節）は維持。比較の資格・重複排除・overviewの一覧は対象消滅 |
| B11-07 全件返却と応答上限 | 部分返却の禁止・上限超過のエラー | **維持**（API契約 第5.4節） |
| B13-01 該当0件とunknownの状態の矛盾 | 状態名の導出 | **対象消滅**（状態名を廃止）。趣旨（unknown・境界・外縁上を「該当なし」にしない）は提示契約 第8章の5つの区別で維持 |
| B13-02 比較未承認時の三値判定 | ソース間の比較の承認 | **対象消滅** |
| B13-03 異なる版の比較・集約 | 版をまたぐ比較・ソース内の集約 | **対象消滅**。異なる版を別の区分として返すことは維持（提示契約 第7.2節） |
| B13-04 選択depth=null時の比較件数 | `deeper_comparison` の件数 | **対象消滅** |
| B15-01 選択depthの優先条件の省略 | `deeper_in_other_sources` の要約 | **対象消滅** |
| Phase 2-B.8 B7-01〜B7-09 | Normalize・Integrationの契約 | **影響なし**（変更していない） |

旧の未決定事項の移行: SS-U1→PD-U1、SS-U4→PD-U2、SS-U5→PD-U7、SS-U6→PD-U6、SS-U7→PD-U5、SS-U12→PD-U8、SS-U13・SS-U16→PD-U9、SS-U14→提示契約 第10章。SS-U2・SS-U3・SS-U9・SS-U15・SS-U17と、Source Priority契約のSP-U*は対象消滅。SS-U11（境界接触を確認済みの該当にしない）は、提示契約 第7.1節で `boundary_contacts` を `zones` と分けて維持。既存契約との論点の移行: SS-C1→PD-C1、SS-C2→PD-C2、SS-C3・SS-C10→PD-C3、SS-C7→PD-C4、SS-C8→PD-C5。SS-C4・SS-C5・SS-C6・SS-C9・SS-C11は、共通API契約の改訂（§4.2・§6）またはAPI契約 FA-C9・FA-C11で扱う。

## 8. Codex独立監査向けの確認対象

**主対象**

1. [提示契約](../../docs/architecture/flood-official-data-presentation-contract-v0.1.md)（新規の正本）
2. [API MVP契約](../../docs/api/flood-api-mvp-contract-v0.1.md)（全面改訂）
3. [Design Principles](../../docs/architecture/design-principles-v1.0.md)（第3.1節・DP-11・適用欄）

**整合の確認**

4. プロジェクト定義書 §5.1・§5.2・§7・§8.2
5. 共通API契約 §4.2・§6・§7・§9・§10
6. Integration契約 第5章 原則4・第10章・OI-6
7. Dataset Registry §6
8. README・AI共通作業規約 第11節
9. 履歴の表示: Source Selection契約・Source Priority契約・Phase 2-B.9／B.10／B.12／B.14の冒頭、Phase 2-A.1〜A.4の注記

**確認してほしい観点**

- 現行の文書に、廃止した比較・集約・順位付け・状態の導出・独自の安全／危険判定が、規範として残っていないか。
- 原典の忠実性・全件返却・unknownの区別・所属の完全性・世代の照合・失敗時の全体エラーの保証が、移行で弱まっていないか（第3章）。
- 5つの区別（提示契約 第8章）が、派生状態なしで一意に表せるか。
- 正本の分担（提示契約 第2章）に重複・矛盾がないか。
- サーバ側のソースの選択の廃止（第2章の追加の判断）が、DP-04・DP-06・DP-08と整合するか。
- 履歴文書が、現行の実装根拠として参照されていないか。
- 既存のBlocking（利用条件・公開認可・幾何の独立検証・派生形状・L2）が無断で解除されていないか。

## 9. 本工程で確認していないこと

1. Codexの独立監査は未実施である。
2. 実装・テスト・実データでの検証は行っていない。テストケースはすべて設計だけである。
3. 本工程は設計文書の整合化であり、OWNERの正式承認・実装の開始・実データの処理・公開を意味しない。
