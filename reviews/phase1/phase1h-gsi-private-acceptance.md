# Verification Summary

## Metadata

- Task ID: `phase1h-gsi-private-acceptance`
- Task: Phase 1-H 実GSI個人実験の準備・受入手順（1タイル: `gsi-dem10b-candidate`、地域13、Z14、X 14552、Y 6451、照会地点 35.681236, 139.767125）
- Implementer: Claude（記録・補助コマンド・テスト・文書・commit・push）
- Reviewer: Claude（自己検証。Codexは使用しない指示）
- Target Commit: 本サマリーと同じコミット（基準main `6a71d75755a8029ec235075a1ca525833aa45668`。開始時とcommit前にfetchし、HEADとorigin/mainの一致を確認した）
- Status: **自己テストPASS**（Fixtureと通信モックのみ）
- OWNER Approval: OWNERの確定方針（2026-10-17）の記録。**実GSIへの通信、実データのPublish、VPSの変更・デプロイは行っていない。承認記録・利用条件確認記録・トークンは作成していない（テストの一時ファイルのみ）。取得の実行許可は確定していない**

## Changes

| ファイル | 内容 |
|---|---|
| `docs/decisions/2026-10-17-private-experiment-operation.md`（新規） | OWNER方針D-1〜D-9、公式資料で確認した事項、未確定事項Q-1〜Q-5（測量法上の手続の要否は未解決）、記録類の位置付け（許諾・適法性の証明ではない） |
| `src/hererisk/elevation/private_ops.py`（新規） | private base の作成、private Source Definition の生成（リポジトリ外）、承認の登録・更新・失効、状態の表示。承認はOWNERの値と `--confirm` で登録した時点で初めて生じる。Publishの承認には、同じ承認によるValidate SUCCESSのrunが必要 |
| `src/hererisk/cli.py` | `private-init`・`private-definition`・`approval-register`・`approval-revoke`・`private-status`。`pipeline --private-base`・`approval-check --private-base`（private_experiment のみ。明示のパスとの併用は不可） |
| `src/hererisk/elevation/api/server.py` | `--private-base`（`--private-experiment` と併用。data root とトークンを導出） |
| `tests/contract/test_private_ops.py`（新規、33件） | 補助コマンドの全手順（モックのGSI）と拒否 |
| 文書 | [Mac受入手順](../../docs/operations/elevation-private-acceptance-mac-v0.1.md)（新規、8段階）、個人実験Runbook・チェックリスト・READMEのリンク |

ProductionAuthorizer・承認ストアの検査・承認記録のSchema・Bearer Token認証・Private/Publicの分離は変更していない。committedの `sources.json` は変更していない（承認の参照はnullのまま）。

## Verification

| Check | Result |
|---|---|
| 全テスト | 1026 passed（既存993 + 新規33） |
| 補助コマンドの全手順（モック） | private base の作成 → 定義 → 登録前はBLOCKED（通信0回）→ 取得の承認 → 3工程SUCCESS（1回だけ取得）→ Publishの承認（確認したrun）→ 再開してPublish（再取得なし）→ Bearer Token付きAPIで12.34 m、トークンなしで401 → 失効後はBLOCKED |
| 抜け道がないこと | 取得とPublishを1回の登録で承認できない（確認したrunが必要）。存在しないrun、FAILED・productionのrun、他の承認のrunは拒否。`--confirm` の不一致、`<…>`・空・`test-only` の承認者・根拠、期限1〜30日の外、対象外の地域、publish以外への公開条件、既存の記録の暗黙の上書き → 拒否。定義を変えると、既存の承認は一致しなくなる |
| 秘密・実データの扱い | private base はリポジトリ外のみ（相対パス・symlink・リポジトリ内は拒否）。トークンは0600で画面に出さず、状態表示・監査記録・CLI出力にトークン・座標を含まない。committedの定義は不変 |
| 既存の安全境界 | Private/Publicの分離、Bearer Token、未承認操作の拒否、既存のfixtureのE2Eは、既存のテストでPASS |
| ミューテーション | 補助コマンドの安全装置10点を1つずつ無効化し、すべて検出（当初未検出の2点はテストを追加して解消） |
| 手動確認（Mac、zsh、通信なし） | 受入手順の手順1・2・3（登録まで）・8を、本書のとおりに実行。`<…>` の値は拒否。登録後のDry-runで3操作がGRANTED。`--private-base` でAPIを起動し、トークン付きで応答、トークンなしで401 |

## Limitations

- 測量法上の手続の要否（決定記録のQ-1〜Q-3）、出典文言（Q-4）、第三者の権利（Q-5）は未確定である。**取得の実行許可は確定していない。** OWNERが判断し、利用条件確認記録に書いてから手順3を実行する。
- 出典文言・ライセンス表記・鉛直基準の記述は、受入手順に「案」として示した。国土地理院の確認は受けていない。
- 手順3・6（実GSIへの通信）と手順7の実データでの値は、OWNERの実行時に初めて確認される。
- 一般公開はBLOCKEDのままである。

## Conclusion

1タイルの個人実験の準備は、OWNERの判断事項を除いて完了した。OWNERは、受入手順の8段階を、JSONの手編集・SHA-256の計算・ファイルのコピーなしで実行できる。承認は常にOWNERの明示の操作で生じ、取得とPublishは別の承認段階である。
