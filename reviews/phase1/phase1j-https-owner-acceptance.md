# Acceptance Record — Phase 1-J HTTPS / Caddy Integration（OWNER）

## Metadata

- Task: Phase 1-J 既存CaddyによるHTTPS接続の追加と受入
- 実施者: **OWNER**（DNS・Caddyの設定変更と確認を、VPS上でOWNERが実施）。本記録の結果はOWNERの実機確認によるもので、Claude自身が検証した結果ではない
- 記録者: Claude（OWNERの報告に基づく文書化のみ。VPS・DNS・Caddyへの操作はしていない）
- 前提: [Phase 1-I VPS受入](phase1i-vps-owner-acceptance.md)（PASS）
- 実施日: 2026-10-17〜18（JST）
- **判定: PASS（HTTPS主要機能受入）／運用上の未実施項目あり**

## 構成

```text
Mac
  |
  | HTTPS + Bearer Token
  v
hererisk.brokendish.org
  |
  v
Caddy :443
  |
  v
127.0.0.1:18080
  |
  v
HereRisk Elevation API
  |
  v
Fixture Registry
```

DNSとCaddyの設定は、OWNERがVPS上で変更・管理している。**リポジトリ内のファイル（`deploy/fixture-vps/` 等）ではない。** Phase 1-Iで作成したDockerfile・Composeは変更していない。

## Results

| 項目 | 結果 |
|---|---|
| DNS Aレコード | 133.18.148.169 |
| 外部DNSでの確認 | 1.1.1.1 / 8.8.8.8 ともに成功 |
| Caddyの構文検証 | PASS |
| Caddyのreload | exit 0 / active |
| TLS証明書 | Let's Encryptで取得に成功（Caddy TLSログに `certificate obtained successfully`） |
| MacからのHTTPS接続 | PASS（SSHトンネルなし） |
| MacからBearer Token付きPOST | HTTP 200 / 81.44 m |
| Macから認証なしPOST | HTTP 401 |
| VPSからHTTPSで認証付きPOST | HTTP 200 / 81.44 m |
| HTTPS `GET /.env` | HTTP 401 |
| OnHighGround2 | 6コンテナが稼働を継続 |
| HereRisk | healthy |

- 証明書の検証を無効にする `curl -k` は使用していない。
- 不正なBearer Tokenによる401は、Phase 1-IでVPSのlocalhost経由で確認したものである。**外部HTTPS経由での不正Tokenの試験は、本受入では実施していない。**
- Caddyに `OCSP stapling` の警告があった。TLS証明書は正常に取得され、HTTPS通信も成功している。

## Security Observations

- 公開の直後に、自動スキャンと思われる `GET /.env` のアクセスを観測した。
  - HTTP（ポート80）では308（HTTPSへのリダイレクト）
  - HTTPS（ポート443）でOWNERが別途実行した `GET /.env` は401
  - この事実だけでは、アクセス元の意図やアクセスの全履歴は確定できない
  - 秘密ファイルの内容が返却されたことは確認されていない
- APIログの確認した範囲では、Bearer Token・認証ヘッダー・緯度経度の露出は見られなかった。**Caddyのアクセスログ全体についての機密情報の監査は完了していない。**

## Operational Constraints / Open Items

- VPSに配置しているのはFixtureデータだけである。実GSI DEM10Bは配置していない。
- 実GSI DEM10Bの利用条件について、国土地理院へ問い合わせ済みである（回答待ち）。
- 実GSIデータの一般公開は、引き続きBLOCKEDである。
- HereRisk APIはインターネットからHTTPSで到達できるが、Bearer Tokenのないアクセスは拒否する。
- 未実施: 負荷試験、長期の連続稼働、Caddyアクセスログ全体の監査、外部HTTPS経由での不正Tokenの試験。
- VPSはSwapの使用が多いため、リソースの監視を継続する。
- MacにコピーしたBearer Tokenと認証ヘッダーファイルは、Git管理外とする。
