# Verification Summary

## Metadata

- Task ID: `phase1f-elevation-production-readiness`
- Task: Phase 1-F 本番化準備（契約改訂案 P1〜P7、GSI利用条件・公開資格、Production Authorizer、本番形式の統合確認）
- Implementer: Claude（契約整理・実装・テスト・commit・push）
- Reviewer: Claude（自己検証。Codexは使用しない指示）
- Target Commit: 本レビューと同じコミット（基準main `76fbc56b2d9d3f56276547b4396957613040f845`。作業開始時とcommit前にfetchし、HEADとorigin/mainの一致を確認した）
- Status: **自己テストPASS**（実GSIへの通信なし。この自己テストは最終受入ではない）
- OWNER Approval: Git運用ルールに基づきcommit・push。**実GSIの本番取得・実データPublish・デプロイは実施していない。本番の承認記録は作成していない。P1〜P7はOWNER未承認。公開資格はBLOCKED。**

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/common/approval_store.py`（新規） | 承認ストアの読込み・信頼境界（所有者・権限・symlink・hardlink・リポジトリ外・fixtureマーカー）、承認記録と失効一覧のSchema、`record_digest` |
| `src/hererisk/common/authorization.py` | `ProductionAuthorizer(approval_root, protected_roots, clock)`: 既定で拒否。記録を照合して、操作ごとに認可する。引数なしの場合は従来どおり常に拒否 |
| `src/hererisk/common/orchestrator.py`、`storage.py` | 本番の実行で、fixtureのマーカー（内容を問わない）を持つデータrootを拒否 |
| `src/hererisk/cli.py` | `pipeline --approval-root`、`approval-check`（事前確認）、`approval-digest`（digestの表示のみ） |
| `docs/architecture/schemas/*.json`（新規） | 承認記録・失効一覧のSchema（コードと一致することをテストで確認）、記入例（有効な記録ではない） |
| `tests/contract/test_production_authorizer.py`（新規、42件）、`tests/e2e_support.py` | 実 `ProductionAuthorizer` とテスト専用ストアによる認可・E2Eのテスト |
| `tests/contract/test_elevation_api.py` | APIプロセスが承認ストアを読み込まないことの確認を追加。`World` とfixtureの作業ディレクトリを分離 |
| 文書（新規） | [契約改訂案 P1〜P7](../../docs/pipeline/elevation-contract-revision-p1-p7-v0.1.md)、[GSI利用条件チェックリスト](../../docs/operations/gsi-dem10b-usage-checklist-v0.1.md)、[本番認可設計](../../docs/architecture/production-authorization-v0.1.md)、[本番化Runbook](../../docs/operations/elevation-production-runbook-v0.1.md) |

FixtureAuthorizer、committedの `sources.json`（`approval_ref=null`）、上位契約の本文は変更していない。

## Verification

| Check | Result |
|---|---|
| 全テスト | 923 passed（既存881 + 新規42） |
| E2E（偽GSI → Download → Normalize → Validate → Publish → Registry → API、実 `ProductionAuthorizer`） | 12.34 m・0 m・−1.2 m・欠損・範囲外を確認。公開版・出典（license・URL・文言）が承認記録の値でAPI応答に入ることを確認。Publish前はAPIから見えない |
| 認可の許可 | 記録に列挙された4操作を、それぞれ別々に許可。Download方針・公開条件が記録から導出される |
| 認可の拒否（いずれも通信0回・書込み0件） | ストアなし・欠落、操作の未列挙（4操作それぞれ）、地域・タイル・取得元・Source Definitionの不一致、地域の拡大要求、タイル数・ホストの上限、Source Definitionの変更、`approval_ref` の不一致、有効期間前・期限切れ、失効、2件の一致、改ざん（digest不一致）、symlink・hardlink・group書込み可のファイル/ディレクトリ・world書込み可のルート、想定外のファイル、ファイル名とIDの不一致、fixtureマーカー、`eligibility_status` が approved 以外、fixture形式の記録、リポジトリ内のストア、出典文言の不一致 |
| 既存の公開状態の保護 | 承認を失効させた後の再実行はBLOCKEDで、データrootは変化せず、APIは旧公開版を返す |
| Runbookの手順 | 2段階（取得・検証 → 記録にpublishを追加して再開）をテストで確認。再開時に新たな通信はない。`approval-check`・`approval-digest`・PoCの計画表示を、通信なしで実行して確認 |
| CLI | committedのSource Definitionでは、ストアがあってもBLOCKED（exit 3、書込みなし）。`--approval-root` をfixtureと組み合わせるとINVALID_INPUT。出力にストアのパスを含まない |
| APIプロセス | 認可・承認ストア・Orchestratorを読み込まない |
| ミューテーション | 認可・ストアの20の判定を1つずつ無効化し、すべてテストで検出（当初未検出の1件は、テストを強化して解消） |

## Findings

1. **本番のデータrootでfixtureマーカーを見落とす可能性（修正済み）**: 既存の `has_fixture_marker` は内容が一致する場合だけtrueを返すため、内容が違うマーカーの本番データrootを受け付けていた。本番では、マーカーの有無だけで拒否するようにした。
2. **テストの作業ディレクトリの共有（修正済み）**: APIテストの `World` が、fixtureハーネスと同じデータrootを使っていた。新しい拒否で顕在化したため、分離した。
3. **想定外のファイルの検出テストが不十分（修正済み）**: 想定外のファイルが不正なJSONだったため、別の検査で拒否されていた。有効な記録の写しを想定外の名前で置くテストにした。

## Limitations

- `record_sha256` は改ざん・部分編集の検出であって署名ではない。真正性はOSのファイル所有者・権限と、管理者の手順に依拠する（設計 第6章）。単一ホストを前提とする。
- GSIの利用条件のうち、事前取得・保存・加工・API提供についての測量法上の手続の要否、HereRiskでの出典文言、第三者の権利は未確認である。公開資格はBLOCKEDのままである（チェックリスト 第2章）。DEM10Bは2025年の標高成果改定の対象外であり、測量時期は国土地理院でも完全には把握していないとされている。
- P1〜P7は採用推奨の改訂案であり、OWNERの承認はない。上位契約の本文は改訂していない。
- 実GSIへの通信、本番の承認記録の作成、実データのPublish、デプロイは行っていない。Codexの独立検証は未実施である。

## Conclusion

自己テストの範囲で、Production Authorizerは既定で拒否し、明示的な承認記録に列挙された範囲だけを許可する。本番形式のE2Eは、実 `ProductionAuthorizer` で成立する。正式な実GSIの取得・Publishに進むには、OWNERが[Runbook](../../docs/operations/elevation-production-runbook-v0.1.md) 第0章の前提（測量法上の手続、出典文言、鉛直基準・測量時期の了承、P1〜P7の採否、取得対象、実行環境）を判断する必要がある。

## Addendum（2026-10-17）

本サマリーの作成時点で「未承認」としていた改訂P1〜P7は、2026-10-17 にOWNERがすべて正式採用し、上位契約へ反映した（[決定記録](../../docs/decisions/2026-10-17-elevation-p1-p7.md)、[反映の検証サマリー](phase1f-owner-approval-p1-p7.md)）。本文は作成時点の記録として変更していない。実GSIの本番取得・公開資格は、引き続きBLOCKEDである。
