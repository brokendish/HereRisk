# Phase 1-B.2 Validate Core 独立検証

- Task ID: `phase1b2-elevation-validate-core-verification`
- 日付: 2026-10-17 / 実装: Claude / 独立検証: Codex
- 対象コミット: `80a93009f407bd03babf88b88b478ccef88e2b97`
- **判定: PASS WITH FINDINGS。fixture Validate Coreは受入可能、Phase 1-B.3へ進行可能。**
- OWNERの最終受入とは別。今回commit/pushなし。

## 範囲・実測

開始時HEADは対象コミットと一致、作業ツリーclean。変更4ファイルと直接依存の型・定数・タイル検査を確認。[契約](../../docs/pipeline/elevation-normalize-validate-contract-v0.1.md)、[実装](../../src/hererisk/elevation/validate/core.py)、[テスト](../../tests/unit/test_validate_core.py)、[自己レビュー](phase1b2-elevation-validate-core-mvp.md)を照合した。受入済みDownload/Normalize/共通保存層の再監査は行っていない。

環境: 既存venv、Python 3.14.3 / macOS、pytest 9.1.1。

| 実行 | 結果 |
|---|---|
| 既存pytest全件（無変更） | **393 passed / 44.89秒**（既存320＋Validate73） |
| 独立追加の受入試験 | **27件PASS**：固定統計7、不正値8、構造7、固定タイル不一致3、Normalize出力接続1、副作用禁止1 |
| 引数境界の診断 | **1件でLOW指摘を再現**。正しい拒否のPASSとは区別 |
| 追加pytestの表示 | **28 passed / 0.14秒**。27受入試験＋1再現診断の合計 |

独立コードはGit外の一時領域に置き、Claudeのテストヘルパーや期待値生成関数を使わず、固定値で照合した。既存試験・追加試験ともsocket/DNS拒否を設定。外部通信、実GSI取得、依存インストール、本番操作なし。

## 必須条件の確認

| 条件 | 根拠・結果 |
|---|---|
| 正常候補 | 合成PNGをNormalizeした候補でvalid=32768、nodata=32768、min=max=0を固定期待値として確認 |
| 形式・キー・tile・寸法・配列長 | 独立の不正入力7種を拒否。既存73件でも欠落・未知キー・長さの過不足等を確認 |
| 欠損・0・負値 | Noneのみ欠損。全0はvalid=65536、全負値も有効。型の暗黙変換なし |
| 統計 | 8値パターン8192反復でvalid=49152/nodata=16384/min=−8388607/max=8388607。末尾だけ有効、減少・増加順、両符号化端点も確認 |
| 全欠損 | valid=0/nodata=65536、min/max=None、warning=ALL_NODATA |
| 不正値 | bool、float、NaN、−Inf、文字列、±域外整数を独立に拒否。既存試験で入れ子・int subclass・複数位置も拒否 |
| 固定タイル照合 | 妥当な整数expected_tileに対しz/x/yそれぞれの不一致を拒否、一致は受理。未検証expected_tileの制限は下記 |
| 不変性・独立性 | 成功時の入力deepcopy一致と配列同一性、失敗時の入力保持を確認。open、Normalize復号/変換、Download.executeを禁止してもValidate成功。呼出し経路は型検査と計数のみ |
| 回帰 | 393件PASS。実装コード・既存テスト・設定に検証作業による変更なし |

ValidateはNormalizeの定数と `_check_tile` を参照するが、PNG復号・変換処理は実行しない。min/max更新では初回の有効値で両端を初期化し、その後の比較で0やNoneのtruthinessを使わない。符号化範囲の受理は、実地形品質・公開資格の保証とは区別されている。

## Finding・後続課題

**B2-F01 / LOW / 後続対応可。今回のfixture受入は非阻害。**

該当: [core.py](../../src/hererisk/elevation/validate/core.py) 81–86行。candidate.tileは厳密検査する一方、expected_tileは `dict(expected_tile)` とPythonの値比較のみ。

最小再現: 正常候補のtileを `{z:1,x:1,y:0}` とし、expected_tileに `{z:1.0,x:True,y:False}` を渡すと受理する。expected_tile=7ではCandidateRejectedではなくTypeErrorになる。候補側へbool/floatを入れた場合は拒否されるため、不正候補の型検査を迂回する問題ではない。

成立条件は、呼出元が検証していない固定計画引数を渡すこと。検証済み整数計画を渡した場合の異なるタイルは拒否され、統計誤りもない。現段階の純粋コアを阻害する指摘ではないが、**Phase 1-B.3の固定計画接続前**に前提を確定する。

最小方針: expected_tileにも既存 `_check_tile` を適用して型・キー・範囲を検査し、失敗をCandidateRejected(tile)へ揃える、または管理入口で検証済み計画のみ渡す契約と接続試験を明示する。新しい検証基盤は不要。今回コード修正なし。

その他の後続事項:

- CandidateRejectedは既存INVALID_INPUTを使い、契約案のVALIDATION_FAILEDは未追加。この差異は自己レビューにも明記されている。純粋コアでは受入可とし、工程別ModuleResult/CLIへ接続する前にOWNER判断で対応を固定する。
- privateタイル検査関数の再利用は規則の二重化を避けている。公開名への整理は今回の修正必須事項ではない。
- B1-F01は既存Normalizeの後続課題として保持し、本検証では再監査しない。

## 結論

修正必須の指摘はない。必須条件は検証済み固定計画を渡すfixtureコアの範囲で満たす。**PASS WITH FINDINGS、Phase 1-B.3へ進行可能**とする。進行時はB2-F01の引数前提とエラー分類の接続を確認する。

候補JSON読取・hash照合・証跡・Orchestrator・公開・実データ品質は未実装/対象外でありNOT RUN。本レビューはそれらの合格を意味しない。

成果物は本公開レビューと `workspace/reports/codex/phase1b2-elevation-validate-core-verification-report.md`（非公開）。Git変更範囲、リンク、秘密情報パターン、非公開報告のignoreを確認。commit/pushは未実施。
