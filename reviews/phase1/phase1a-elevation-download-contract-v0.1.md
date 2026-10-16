# Phase 1-A Download / Acquisition Record契約レビュー v0.1

- Task ID: `phase1a-elevation-download-contract-v0.1`
- 日付: 2026-10-17
- 作成・自己検証: Codex（独立検証ではない）
- 対象: 未コミットの作業ツリー
- 基準main: `680e2eadcefd0717a4b7bc21f681178c2b6f0471`（作業開始時fetch後HEADとorigin/main一致、作業ツリーclean）
- 判定: **PASS WITH FINDINGS（文書・静的確認の範囲）**。実装承認・実取得成功・公開成功を意味しない。

## 変更ファイル

- [実装契約案](../../docs/pipeline/elevation-download-contract-v0.1.md): 入出力、取得記録、確定/回復、権限、通信候補、世代管理9ケース、試験仕様。
- [README](../../README.md): 設計書へのリンク追加。
- 本レビュー。
- 非公開作業報告: `workspace/reports/codex/phase1a-elevation-download-contract-v0.1-report.md`（Git管理対象外）。

既存契約・sources.json・Schema・コード・CLI・Docker・conf・env・Registryは変更していない。

## 設計上の推奨

Downloadはworkの不変取得候補とRecordを確定して終了する。raw currentへの交代はValidate成功後にOrchestratorがGeneration Managerへ依頼する案を推奨。Phase 1-A単独ではcurrent交代を実装しない。取得成功後のNormalize/Validate失敗でも、取得事実を改変せず候補を保護する。

不変Record・原本・確定マーカーを照合して消費可否を判断する。複数ディレクトリを一操作で原子的更新できるとは仮定せず、停止点ごとの回復を必要とする。元DLと公開データは別系列で保持・復元し、公開確定はPublishだけが担当する。

## 静的確認

| 対象 | 結果・方法 |
|---|---|
| 既存JSON/Schema | PASS: Python json、jsonschema Draft202012Validator + FormatChecker。Schema自体もcheck_schema |
| 全国定義 | PASS: 01～47の集合と47名称を照合。13のみtargeted=true、他46はfalse/source_refs空 |
| Schema相対参照 | PASS: sources.jsonの$schemaが実在ファイルへ解決 |
| 契約JSON例 | PASS: 4例の構文、成果物とRecordのID/hash/size、異常status、未知元データ情報nullを確認。新RecordのJSON Schema検証ではない |
| Markdown | PASS: 変更・新規Markdownのローカルリンク先を確認。外部公式資料2ページは閲覧確認。外部全リンクの巡回検査は未実施 |
| Git差分・機密情報 | PASS: 変更範囲、diff --check、新規文書を含む秘密パターンと内容を確認。履歴全体の秘密監査ではない |
| 実装・単体・契約・障害注入・実GSI統合・実機ログ | NOT RUN: 今回は文書のみ。記載したF01～F22は将来実装の仕様であり実行済みではない |
| commit / push | NOT RUN: 今回の変更に対する許可なし |

タイル取得・世代交代・復元・Registry切替を行っていない。静的検査用の一時Python実行をパイプライン実装テストと扱わない。

## 発見事項・既存契約との整合

1. 標高API契約O01は方式全体を未決定とする旧記述を残す。今回OWNER指示ではPNG事前取得がFIXED。DEM10B/Z14・具体タイル・鉛直基準・利用条件は引き続き未承認。既存文書は変更していない。
2. sources.jsonは構造上有効でもtiles/pipeline/承認等がnullであり実行BLOCKED。実装時に値を暗黙補完しない。
3. 本案の通信ポリシーキーは現行Schemaに追加できない。配置・Schema改訂・数値の承認が別途必要。
4. Recordの正式化は既存データソース設計の不変記録方針を具体化する提案。Registryの既存フィールド・公開資格・唯一の更新主体は変更しない。
5. 元DLのretention_keyは未決定のDataset公開単位と調整が必要。API/都道府県/source_refと同一視しない。
6. 3世代は安定時の目標とし、使用中保護・整理失敗時の一時超過を提案。元DL/公開系列の連動削除は禁止を維持する。

## OWNER判断事項

実装前: Input/Output・終了コード・Record・確定/回復・排他・fixture試験範囲の承認。

実取得前: DEM種/Z/タイル集合・鉛直基準・利用条件/出典・pipeline版・実行承認・通信上限と設定配置。

世代管理実装前: Validate後交代案、retention_key、圧縮方式、保存保証、候補保持期限/容量、使用中参照とバックアップ/復元。

独立レビュー・OWNER受入は未実施。詳細は実装契約第11節を参照する。
