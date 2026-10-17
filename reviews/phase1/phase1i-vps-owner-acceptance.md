# Acceptance Record — Phase 1-I VPS Fixture実機受入（OWNER）

## Metadata

- Task: Phase 1-I VPS Fixture Deployment の実機受入
- 実施者: **OWNER**（VPS上で実行・確認）。本記録の結果はOWNERの実機確認によるもので、Claude自身がVPSで検証した結果ではない
- 記録者: Claude（OWNERの報告に基づく文書化のみ。VPSへの接続・操作はしていない）
- 実装コミット: `b983d5c58c0a5029ea30f5365c30f3db9b04e522`
- 実施日: 2026-10-17〜18（JST）
- 環境: KAGOYA VPS / Debian 13 / Docker 29.7.2 / Compose v5.5.1
- VPS上のリポジトリ: `/home/debian/Development/GitHub/HereRisk`
- 手順: [Fixture VPS Runbook](../../docs/operations/elevation-fixture-vps-runbook-v0.1.md)
- Mac上の事前検証（Claude）: [phase1i-fixture-vps-deploy.md](phase1i-fixture-vps-deploy.md)
- **判定: PASS（VPS Fixture実機受入）**

## Results

| 項目 | 結果 |
|---|---|
| Git Clone / Commit一致 | PASS |
| Compose構文検証 | PASS（exit 0） |
| Docker Build | PASS（約7.7秒） |
| API Token生成 | PASS（UID/GID 10001、0600） |
| Fixture初期化 | PASS（Download / Normalize / Validate / Publish） |
| API起動 | PASS（healthy） |
| ホストの待受け | `127.0.0.1:18080` |
| 有効なBearer Token | HTTP 200 |
| 認証なし | HTTP 401 |
| 不正なBearer Token | HTTP 401（VPSのlocalhost経由で確認） |
| Fixture標高 | 81.44 m |
| 再起動後のデータ保持 | PASS |
| Publication Versionの維持 | PASS |
| 既存のOnHighGround2コンテナ | 6個すべて稼働を継続 |
| VPSリポジトリ | Gitの作業ツリーはclean |

- Fixture初期化のRun ID: `17f8badd-72c6-4224-a071-36b3288bf8ae`
- Publication Version: `pub-17f8badd-72c6-4224-a071-36b3288bf8ae`

## Resources（OWNER実測）

| 項目 | 値 |
|---|---|
| APIのメモリ | 23.5 MiB / 上限256 MiB |
| CPU | 0.01%（測定時点） |
| VPSのavailableメモリ | 約1.3 GiB |
| Swapの使用 | 約1.6 GiB |

## Observation

- 再起動の直後、最初のcurlがHTTP 000（connection reset）になった。この時点のコンテナの状態は `health: starting` であった。再試行でHTTP 200となり、その後のhealthcheckはhealthyであった。**起動準備中の一時的な事象として記録する。** Runbook第5章に、`healthy` になってから確認する旨を追記した。

## Scope / Not Covered

- VPSに配置したのはFixture（合成データ）だけである。実GSI DEM10Bは配置していない。
- 負荷試験・長期の連続稼働は未実施である。
- VPSはSwapの使用が多いため、リソースの監視を継続する。
