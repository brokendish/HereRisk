# Verification Summary

## Metadata

- Task ID: `phase1g-private-experiment`
- Task: Phase 1-G 個人実験環境（`private_experiment`）の実装。Mac・VPSの本人専用運用。一般公開とは分離し、一般公開はBLOCKEDのまま維持
- Implementer: Claude（実装・テスト・文書・commit・push）
- Reviewer: Claude（自己検証。Codexは使用しない指示）
- Target Commit: 本サマリーと同じコミット（基準main `d4d02b2cc7717ec8b9eabf5a5e8c6c9e82f5cd74`。開始時とcommit前にfetchし、HEADとorigin/mainの一致を確認した）
- Status: **自己テストPASS**（合成データと通信モックのみ。この自己テストは最終受入ではない）
- OWNER Approval: OWNER方針（2026-10-17）に基づく実装。commit・pushはGit運用ルールに基づく。**実GSIへの通信、Private Publish、VPSの変更・デプロイは行っていない。個人実験の承認記録・確認記録は作成していない**

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/common/authorization.py` | `ExecutionContext.PRIVATE_EXPERIMENT`、3区分の定義。`ProductionAuthorizer(context=…)` は1区分だけを扱い、記録の `execution_context` が一致する記録だけを照合する。Publishの資格を区分ごとに再確認 |
| `src/hererisk/common/approval_store.py` | 記録のSchema: `execution_context` に `private_experiment` を追加。区分ごとのIDの空間（`apr-private-*`）、`publication.private_use`（private のみ）と `eligibility_*`（public のみ） |
| `src/hererisk/common/storage.py` | 個人実験rootの印（`.hererisk-private-experiment-root`）、`init_private_data_root`、印の検査 |
| `src/hererisk/common/orchestrator.py` | データrootの検査を区分ごとに分けた（第3章の表） |
| `src/hererisk/elevation/download/{download,gsi_transport,transport}.py`、`normalize/stage.py`、`validate/stage.py` | private を実データの区分として扱う（パイプライン版・profileは本番形式、記録の区分の列挙） |
| `src/hererisk/elevation/api/{published,server}.py` | `--private-experiment`（private root のみ、ループバックのみ、`--fixture-demo` と排他）。public のモードは private root を拒否 |
| `src/hererisk/cli.py` | `pipeline --private-experiment`、`init-private-root`、`approval-check --context` |
| `tests/contract/test_private_experiment.py`（新規、32件）、`tests/e2e_support.py` | 個人実験の契約・回帰・E2E |
| 文書 | 新規: [運用区分と個人実験の契約](../../docs/architecture/private-experiment-v0.1.md)、[Mac・VPS Runbook](../../docs/operations/elevation-private-experiment-runbook-v0.1.md)、[個人実験の承認記録の記入例](../../docs/architecture/schemas/private-experiment-approval-record.example.json)。更新: [GSI利用条件チェックリスト 第5章](../../docs/operations/gsi-dem10b-usage-checklist-v0.1.md)、本番認可設計、Schema、README、使い方 |

公開API契約（入力・7キー・status）と標高の計算、FixtureAuthorizer、committedの `sources.json` は変更していない。

## Verification

| Check | Result |
|---|---|
| 全テスト | 955 passed（既存923 + 新規32） |
| Private の4工程 | 実 `ProductionAuthorizer(context=private_experiment)` とテスト専用の承認記録で、Download → Normalize → Validate → Publish がSUCCESS。各記録の `execution_context = private_experiment` |
| Private Registryからの標高 | private のAPIで12.34 m・0 m・−1.2 m・2.56 m・欠損・範囲外。公開版・出典が承認記録の値 |
| Public から見えない | public のモードのAPI・サーバーは private root で起動しない。public root は空のまま（コピー・昇格なし） |
| Public は BLOCKED | 承認なし、ストアなし、private の承認だけ、のいずれもBLOCKED（通信0回・書込み0件） |
| 区分の継承なし | private の記録で public の実行（Publishを含む）はBLOCKED。public の記録で private の実行はBLOCKED。同じストアに両方があっても、各認可器は自分の区分の記録だけを使う |
| 資格の流用なし | private の記録に `eligibility_*`、`private_use` の欠落・値の違い、IDの空間の違い、public の記録に `private_use` や `apr-private-*` → いずれも拒否。Schemaを迂回して認可器を直接呼んでも拒否（多重の防御） |
| 不一致・期限切れ・失効・改ざん | Source Definitionのハッシュ不一致、期限切れ、失効、記録の改ざん、publishの未列挙 → BLOCKED |
| データrootの取り違え | private の実行: 印なし・印の内容違い・fixtureの印 → INVALID_INPUT。public の実行: private の印 → INVALID_INPUT。fixture の実行: private の印 → INVALID_INPUT |
| API の起動拒否 | private のモード: public root・fixture root・fixtureの印のある private root・Registryの破損 → 起動しない。非ループバック（0.0.0.0・192.0.2.1・::）→ 起動しない。`main` はexit 3 |
| 実GSIへのHTTPSなし | E2Eは偽のGSI接続のみ（テスト全体で、ソケット接続・名前解決を禁止している） |
| ミューテーション | 区分の分離の判定15点を1つずつ無効化し、すべて検出（当初の未検出5点は、テストを強化して解消） |
| 手動確認（Mac、通信なし） | `init-private-root`、private のモードでループバック起動（`lsof` で127.0.0.1のみ）、curlで `no_coverage`、ログに座標なし。同じrootの public のモード・非ループバックはexit 3 |

## Findings

1. **一部の判定がテストで単独に確認されていなかった（追加済み）**: 認可器での資格の再確認、IDの空間、private root のfixtureの印、`--fixture-demo` との排他は、別の検査が先に拒否するため、単独では検出されなかった。それぞれを単独で確認するテストを追加した。
2. **ミューテーション試験の一つが停止しなかった（試験手順の問題）**: ループバックの検査を外すと、`main` が0.0.0.0で待受けを続けたため、該当のpytestを停止した。この判定はテストで検出されている（変異は検出 = KILLED）。ファイルは元に戻っていることを確認した。

## Limitations

- 個人実験の利用条件は、[チェックリスト 第5章](../../docs/operations/gsi-dem10b-usage-checklist-v0.1.md)のとおり**未確認**である。私的利用・内部利用の区分に当たるかは公式資料で確定できず、照会を推奨している。`private_use` の記録は適合の証明ではない。
- 本人限定は、ループバックでの待受けとSSHトンネルによる。アプリケーションの認証はない（方針どおり）。
- VPSの手順・systemdの設定例は、文書として作成した。実機では検証していない。
- 実GSIの取得・Private Publish・HTTPでの実値の確認は、OWNERが実行する（未実行）。

## Conclusion

自己テストの範囲で、個人実験の環境は、認可・データroot・Registry・APIのすべてで一般公開から独立して成立する。privateからpublicへ流出する経路（承認の継承、資格の流用、rootの共用、APIによる参照、コピー・昇格）は、いずれも拒否されることを確認した。一般公開はBLOCKEDのままである。

## Addendum（2026-10-17）

OWNERの方針変更により、個人実験APIのアクセス制御を、SSHトンネル必須の方式から共通Bearer Token認証に変更した（[検証サマリー](phase1g-api-bearer-auth.md)）。本文の「本人限定は、ループバックでの待受けとSSHトンネルによる」は作成時点の記録である。現在は、ループバックでの待受けとBearer Tokenにより、SSHトンネルは保守用の代替手段である。
