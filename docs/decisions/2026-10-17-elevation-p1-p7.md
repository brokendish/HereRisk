# 決定記録: 標高 契約改訂 P1〜P7 の正式採用（2026-10-17）

- 決定日: 2026-10-17
- 決定者: OWNER
- 決定: [契約改訂案 P1〜P7](../pipeline/elevation-contract-revision-p1-p7-v0.1.md) をすべて正式採用する
- 反映作業: Task `phase1f-owner-approval-p1-p7`（Claude。文書の反映のみ。コードの変更なし）
- 根拠となった実装: コミット `76fbc56`（Phase 1-D.3〜1-E）、`757d66d`（Phase 1-F）

| ID | 内容 | 反映先 |
|---|---|---|
| P1 | 公開実体はValidate済み整数cm JSON | [標高API契約](../api/elevation-contract-v0.1.md) §6.1・§6.2・§11、[Dataset Registry](../architecture/dataset-registry-v0.1.md) 末尾 |
| P2 | CoverageはXYZタイル参照 | 標高API契約 §6.1、Dataset Registry §3.4・末尾 |
| P3 | 元データ基準日を確認できない場合はnull | 標高API契約 §4.1 |
| P4 | 未定義のAPIパスは404（`not_found`） | 標高API契約 §5 |
| P5 | API設定は設定ファイル（`api/elevation/conf/api.json`） | 標高API契約 §7 |
| P6 | 現行Registryポインタの原子的な切替 | 標高API契約 末尾、[Data Publish](../architecture/data-publish-v0.1.md) 末尾、Dataset Registry 末尾 |
| P7 | Publish認可にはライセンス・出典URLが必要 | Data Publish §6・末尾、Dataset Registry §5・末尾 |

## この決定に含まれないもの

- 実GSIデータの本番取得・Publish・一般公開の承認。**公開資格は引き続きBLOCKED**である（[GSI利用条件チェックリスト](../operations/gsi-dem10b-usage-checklist-v0.1.md)）。
- 本番の承認記録の作成・登録（[本番化Runbook](../operations/elevation-production-runbook-v0.1.md)）。
- 標高API契約 第12節のO01〜O09、およびP1〜P7以外のUNDECIDED・PROVISIONALの項目。
- 上位契約のFIXEDの事項の変更（変更していない）。

## 実装との整合

P1〜P7は、いずれも既存の実装と一致する（[実装仕様](../pipeline/elevation-publish-api-v0.1.md)）。反映時に、全テストがPASSすることを確認した。
