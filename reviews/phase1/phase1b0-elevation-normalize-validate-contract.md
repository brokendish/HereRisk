# Phase 1-B.0 Normalize / Validate 契約設計レビュー

- Task ID: `phase1b0-elevation-normalize-validate-contract`
- 担当: Codex（設計・自己確認。独立検証ではない）
- 日付: 2026-10-17
- 基準コミット: `b783025173ee24befa28e37c30c8069a135915e8`
- 確認対象: 未コミットの文書。開始時HEADは基準と一致、作業ツリーclean。
- 判定: **PASS WITH FINDINGS（文書の静的自己確認に限定）**
- OWNER承認: 契約案・実装方針は未承認。今回commit/pushなし。

## 変更

[設計書](../../docs/pipeline/elevation-normalize-validate-contract-v0.1.md)を新規作成。Downloadの全要求成功と固定証拠を入力とし、Normalizeによる変換、Validateによる候補の受入検査を分離した。

内部形式は整数cm/null配列のJSONを推奨。バイナリ＋mask案と比較し、初版の実装量・確認容易性を優先する。公開形式には確定しない。候補・工程別証跡、既存ModuleResult/Artifactの再利用案、失敗・再実行、上限、fixture受入仕様を記載した。FIXEDは継承制約、追加仕様はPROVISIONAL、採否と後続課題はUNDECIDEDとして区別した。

公開変更は設計書と本レビューのみ。非公開報告は指定のworkspace配下。既存文書・Python・テスト・設定・Dockerは変更していない。

## 確認結果

| 確認 | 結果 |
|---|---|
| 必読文書・Downloadと共通基盤の照合 | 実施。責務・成功ゲート・固定設定・取得証拠・公開境界を維持 |
| 公式仕様 | 国土地理院の[標高タイル詳細仕様](https://maps.gsi.go.jp/development/demtile.html)を2026-10-17に参照。符号化規則とHereRisk独自形式を区別。タイル取得なし |
| 文書内ローカルMarkdownリンク | 存在確認。外部リンクは今回参照した公式ページのみ確認 |
| 合成画素の数式・表現容量 | 記載6例を独立した算術で照合。65536値の最大compact JSONが1 MiB以内であることを確認。実装テストではない |
| Git差分・公開文書の秘密情報・非公開報告除外 | 確認。指定した新規Markdownのみ、workspaceはignore対象 |
| Normalize/Validate単体・統合・障害・メモリ試験 | **NOT RUN**。未実装。設計書の受入仕様は将来の試験項目 |
| 既存pytest・過去独立試験 | **NOT RUN**。コード変更のない文書設計であり、過去PASS件数を今回の実測として使用しない |
| 実GSI・本番・journald・電源断 | **NOT RUN**。対象外 |

## Findingsと既存契約との差異

| ID | 内容 | 扱い・期限 |
|---|---|---|
| D01 | 標高API契約は単一PNG公開/要求時復号を暫定提案。本書は中間JSONを推奨 | 公開形式はUNDECIDED。Publish/API読取の詳細設計で原PNGと正規化候補の関係を承認。既存契約を変更しない |
| D02 | 保存層の現行allowlistに後段領域がない。Orchestrator/fixture認可はdownloadのみ | 共通基盤を変更なしで利用可能とは主張しない。3領域・工程別アクセス範囲・明示的認可と逐次呼出しの限定拡張案。実装前に承認 |
| D03 | Artifactは現在取得物用、success文言もDownload専用 | 形は維持し工程別record_ref/hashの意味を明示する案。固定messageとVALIDATION_FAILED追加を共通契約としてレビュー。実装前に承認 |
| D04 | Download文書のrename案に対して受入済み実装はlink+unlink。回復も自動化されていない | 現行のno-clobber保存・未確定時停止を継承。新しいrename実装や自動回復を作らない |
| D05 | 全欠損SUCCESS・符号化範囲検査は実地形品質や本番公開の保証ではない | fixture限定profileとして提案。欠損率・地形範囲・実Coverage・鉛直基準は実データ検証前に決定 |
| D06 | R2-F01、後段候補の長期容量、デコーダーの展開上限 | 初版は専用rootの直列fixture。PNG依存と上限保証は復号器実装前、容量/排他は長期・並行運用前に対応 |

新たな既存契約の上書きは行っていない。追加仕様はOWNER判断待ちであり、独立した実装監査を完了した判定ではない。

## 次工程

OWNERが内部形式・欠損方針・I/O/証跡・共通基盤の限定拡張を承認後、1タイルのPNG→整数cm/null変換と候補検査から実装する。次にDownload証拠との接続、最後にOrchestratorの逐次制御・中断回帰を行う案。fixture成功から本番Publishへ自動的には進めない。
