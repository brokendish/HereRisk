# HereRisk

Know the risk where you are.

HereRiskは、現在地の災害リスクを調べ、
利用者の判断を支援するWebサービスです。
全国対応を前提とした防災リスク判定支援サービスとして設計し、東京都のデータから検証を開始します。

## ドキュメント

- [プロジェクト定義書](docs/project-charter.md)
- [Design Principles v1.0](docs/architecture/design-principles-v1.0.md)（共通設計の最上位原則。共通API契約・各ハザードの個別契約はこれと整合させる）
- [ADR: 複数の公式防災情報を独立して提示する理由（2026-10-25）](docs/decisions/2026-10-25-multiple-official-hazard-results.md)（公式データ間の差異を隠さず、独自の唯一の答えを作らない設計判断）
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
- [Phase 1-G 個人実験環境](reviews/phase1/phase1g-private-experiment.md): [運用区分と個人実験の契約](docs/architecture/private-experiment-v0.1.md)、[Mac・VPS本人専用Runbook](docs/operations/elevation-private-experiment-runbook-v0.1.md)（一般公開はBLOCKEDのまま。APIは共通Bearer Token認証: [検証サマリー](reviews/phase1/phase1g-api-bearer-auth.md)）
- [Phase 1-H 実GSI個人実験の準備](reviews/phase1/phase1h-gsi-private-acceptance.md): [決定記録](docs/decisions/2026-10-17-private-experiment-operation.md)、[Mac受入手順（1タイル）](docs/operations/elevation-private-acceptance-mac-v0.1.md)
- Phase 1-I Fixture VPS受入: **PASS（VPS Fixture実機受入、OWNER 2026-10-17〜18）** — [OWNER受入記録](reviews/phase1/phase1i-vps-owner-acceptance.md)、[Mac事前検証](reviews/phase1/phase1i-fixture-vps-deploy.md)、[VPS Runbook（Docker Compose）](docs/operations/elevation-fixture-vps-runbook-v0.1.md)
- Phase 1-J HTTPS / Caddy: **PASS（HTTPS主要機能受入）／運用上の未実施項目あり** — [OWNER受入記録](reviews/phase1/phase1j-https-owner-acceptance.md)。VPSにはFixtureデータのみ。実GSIデータの一般公開はBLOCKED（国土地理院の回答待ち）
- Phase 2 洪水（Flood）設計（**契約案。正式採用・実装・公開は未承認**）。方式は**公式データ忠実提示方式**: 公式データを原典の内容・出典・条件のまま、複数あればすべて独立して返し、比較・代表値・順位付け・独自の安全／危険判定を行わない
  - 現行の正本: [Flood Official Data Presentation Contract（案）](docs/architecture/flood-official-data-presentation-contract-v0.1.md)、[Flood API MVP Contract（案）](docs/api/flood-api-mvp-contract-v0.1.md)、[Flood Normalize Contract（案）](docs/architecture/flood-normalize-contract-v0.1.md)、[Flood Integration Contract（案）](docs/architecture/flood-integration-contract-v0.1.md)
  - 方式移行の記録: [Phase 2-B.17 設計の全面整合レビュー](reviews/phase2/phase2b17-official-data-presentation-realignment.md)
  - 履歴資料（**現行仕様ではない。実装根拠として使用禁止**）: [Flood Source Priority Contract](docs/architecture/flood-source-priority-contract-v0.1.md)、[Flood Source Selection Contract](docs/architecture/flood-source-selection-contract-v0.1.md)、Phase 2-B.9〜B.16のレビュー（`reviews/phase2/phase2b9`〜`phase2b14`）

## 開発方針

- UNIX哲学
- 疎結合
- 小さなMVP
- 独立検証
- 不明を安全と判定しない

## 設定・データの責務分離

共有設定は `conf/common/`、API固有設定は `api/<api>/conf/` に配置し、commonのConfiguration Managerで読み込み・検証・解決します。[標高の取得定義](api/elevation/conf/sources.json)と[Schema](api/elevation/conf/sources.schema.json)を配置済みです。

API別データ領域・権限・設定発見の契約は[基本アーキテクチャ](docs/architecture/basic-architecture-v0.1.md)、改訂内容と確認結果は[API独立性改訂レビュー](reviews/phase0/api-isolation-contract-revision-v0.1.md)を参照してください。
