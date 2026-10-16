# Verification Summary

## Metadata

- Task ID: `api-isolation-contract-revision-v0.1`
- Date: 2026-10-16
- Implementer: Codex（契約改訂・設定移動）
- Reviewer: Codex（自己確認。独立検証ではない）
- Target Commit: 未コミット
- Status: PASS WITH FINDINGS（契約・設定の静的確認のみ）
- OWNER Approval: API独立性と責務別設定配置への変更は承認済み。詳細方式の提案はレビュー対象。2026-10-16にOWNERからcommit・pushの許可を取得。共有許可は残る詳細方式の最終承認とは区別する。

## 旧契約と新契約

| 項目 | 旧契約 | 新契約 |
|---|---|---|
| 定義・デフォルト | ルートconfへ全設定を集約 | conf/commonとapi/<api>/confへ責務別配置 |
| 標高定義 | conf/sources/elevation.json | api/elevation/conf/sources.json |
| 標高Schema | conf/sources/elevation.schema.json | api/elevation/conf/sources.schema.json |
| 読込・解決 | 共通の設定読み込み | commonのConfiguration Managerを維持し、スコープ・API識別・種別で発見する案を追加 |
| 階層 | デフォルト・運用値・許可された要求値 | 3階層を維持。別APIへの上書き・内部参照を禁止 |
| データ | API別領域の統一契約なし | /data/<api>/のdl、work、rel/versions、recordsを論理的に分離 |
| 世代 | 公開世代の原則3世代 | 公開世代を維持し、元DLも別系列で原則3世代。使用中参照を保護 |
| 権限 | 公開処理とAPIを分離 | 配置と実行権限を明確に区別。共通管理処理は認可されたAPI領域・操作だけ |

## Changes

- [Charter](../../docs/project-charter.md)：P7・P11・設定配置・API独立性。
- [基本アーキテクチャ](../../docs/architecture/basic-architecture-v0.1.md)：配置改訂、設定発見・解決順、データ所有・バックアップ・復元・権限。
- [データソース設計](../../docs/architecture/data-source-definition-v0.1.md)：移動先リンク・Schema参照・検証手順・Record領域。
- [Publish](../../docs/architecture/data-publish-v0.1.md)、[Registry](../../docs/architecture/dataset-registry-v0.1.md)：責務別配置、API領域、DL/公開世代の区別。既存公開資格は維持。
- [標高API契約](../../docs/api/elevation-contract-v0.1.md)：設定配置・自API公開データ参照のみ変更。HTTP/JSON案は維持。
- [AI作業規約](../../docs/development/ai-development-policy.md)、[README](../../README.md)：新配置と共通管理の規則・参照。
- [移動後JSON](../../api/elevation/conf/sources.json)・[Schema](../../api/elevation/conf/sources.schema.json)：相対Schema名だけ更新。移動元は削除、二重管理なし。
- [過去のデータソースレビュー](data-source-definition-v0.1.md)：リンク切れを避けるため移動先リンク2件と移動注記だけ変更。当時の判定は保持。
- 本レビューと同一Task IDの非公開報告書を追加。

## Verification

| 確認 | 結果 |
|---|---|
| JSON構文・Schema | PASS：厳密JSON解析、Draft 2020-12 meta-schema、FormatChecker付きSchema検証 |
| 移動の同一性 | PASS：HEADの移動元と比較し、JSON/Schemaとも相対Schema名の置換以外はバイト一致。旧ファイルなし |
| 47都道府県 | PASS：01～47の欠落・重複なし、名前とコード対応、13だけtargeted=true、他46件false/空参照 |
| 未承認値 | PASS：取得元候補・tiles/pipeline/利用条件/承認等のnullを維持 |
| 相対Schema参照 | PASS：sources.jsonの$schemaとSchema内constが同一ディレクトリのsources.schema.jsonに一致 |
| Markdown / 旧配置 | PASS：README・docs・reviewsの相対リンクを確認。旧配置文字列は本レビューの改訂前一覧のみ。過去の非公開報告書・Git履歴の旧記載は履歴として保持 |
| 既存契約 | PASS WITH FINDINGS：設定の全ルート集約規則を明示改訂。公開資格・原子的公開・実行status・Generation/Restore・API応答を維持。共通API契約は変更不要 |
| MVP 0 / scope | PASS：機能追加なし。新規APIの空設定・コード・データ領域・Docker変更なし |
| Security / Git | PASS：差分と新規ファイルの目視・代表秘密情報パターン確認で候補なし。報告書はignore適用・非追跡 |
| Unit / Integration / Runtime | NOT RUN：設定発見、認可、マウント、世代保持・復元等の実装なし。Schema静的確認を動作試験とみなさない |
| Independent review | NOT RUN：自己確認のみ |

## Findings / 未決定事項

設定発見の識別子・許可集合の格納形式、永続運用値の保存・反映・競合方式、Registryの物理配置、DLと公開世代の安全な回収・証跡保持・バックアップ方式、Docker Volume/bind mount・UID/GID・権限は詳細設計対象。標高の候補条件や既存API案の未決定事項を配置変更で承認済みにしていない。

Schema参照変更で定義原文hashは変化する。取得条件は同一のためdefinition_revisionはdraft-1を維持し、将来の取得記録は実際の設定スナップショット/hashを保持する。版ラベルだけで同一性を判定しない。

## Limitations / Conclusion

静的自己確認はPASS WITH FINDINGS。実装・データ取得・独立検証なし。共有前にローカル全参照から到達可能な履歴56オブジェクト（blob・commit等）と公開対象変更を代表パターンで検査し、秘密情報候補なし。完全性保証ではない。OWNERの共有許可に基づき本記録を含む変更をcommit・pushする。
