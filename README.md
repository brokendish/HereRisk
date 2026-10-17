# HereRisk

Know the risk where you are.

HereRiskは、現在地の災害リスクを調べ、
利用者の判断を支援するWebサービスです。
全国対応を前提とした防災リスク判定支援サービスとして設計し、東京都のデータから検証を開始します。

## ドキュメント

- [プロジェクト定義書](docs/project-charter.md)
- [AI共通作業規約](docs/development/ai-development-policy.md)
- [公開検証サマリー](reviews/README.md)
- [Dataset Registry設計書 v0.1](docs/architecture/dataset-registry-v0.1.md)
- [Data Publish設計書 v0.1](docs/architecture/data-publish-v0.1.md)
- [基本アーキテクチャ設計書 v0.1](docs/architecture/basic-architecture-v0.1.md)
- [Common Hazard API契約書 v0.1](docs/api/common-contract-v0.1.md)
- [MVP 0 標高API詳細契約案 v0.1](docs/api/elevation-contract-v0.1.md)
- [データソース定義・全国対応設計 v0.1](docs/architecture/data-source-definition-v0.1.md)

- [Phase 1-A Download / Acquisition Record実装契約案 v0.1](docs/pipeline/elevation-download-contract-v0.1.md)
- [Phase 1-A.1 Download Fixture MVP 使い方](docs/development/phase1a1-download-fixture-usage.md)（[検証サマリー](reviews/phase1/phase1a1-elevation-download-fixture-mvp.md)）
- [Phase 1-D.3〜1-E 本番形式パイプライン・Data Publish・公開API 実装仕様 v0.1](docs/pipeline/elevation-publish-api-v0.1.md)（[検証サマリー](reviews/phase1/phase1d3-to-1e-elevation-integration.md)、起動手順は[使い方 第3.7節](docs/development/phase1a1-download-fixture-usage.md)）
- [Phase 1-F 本番化準備](reviews/phase1/phase1f-elevation-production-readiness.md): [契約改訂案 P1〜P7](docs/pipeline/elevation-contract-revision-p1-p7-v0.1.md)、[本番認可設計](docs/architecture/production-authorization-v0.1.md)、[GSI利用条件チェックリスト](docs/operations/gsi-dem10b-usage-checklist-v0.1.md)、[本番化Runbook](docs/operations/elevation-production-runbook-v0.1.md)
- [決定記録: 標高 契約改訂P1〜P7の正式採用（2026-10-17）](docs/decisions/2026-10-17-elevation-p1-p7.md)（[反映の検証サマリー](reviews/phase1/phase1f-owner-approval-p1-p7.md)）

## 開発方針

- UNIX哲学
- 疎結合
- 小さなMVP
- 独立検証
- 不明を安全と判定しない

## 設定・データの責務分離

共有設定は `conf/common/`、API固有設定は `api/<api>/conf/` に配置し、commonのConfiguration Managerで読み込み・検証・解決します。[標高の取得定義](api/elevation/conf/sources.json)と[Schema](api/elevation/conf/sources.schema.json)を配置済みです。

API別データ領域・権限・設定発見の契約は[基本アーキテクチャ](docs/architecture/basic-architecture-v0.1.md)、改訂内容と確認結果は[API独立性改訂レビュー](reviews/phase0/api-isolation-contract-revision-v0.1.md)を参照してください。
