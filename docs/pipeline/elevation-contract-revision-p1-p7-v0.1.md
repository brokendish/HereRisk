# 標高 契約改訂案 P1〜P7 v0.1（採用推奨・OWNER未承認）

- Task ID: `phase1f-elevation-production-readiness`
- 状態: **改訂案（採用推奨）。OWNERの正式な承認はまだない。** 本書は上位契約の本文を改訂しない。上位契約の本文は、OWNERが承認した時点で本書の差分を反映する。
- 起点: [Phase 1-D.3〜1-E 実装仕様](elevation-publish-api-v0.1.md) 第5章
- 方針: 既存の実装（コミット `76fbc56`）に合わせ、上位契約の変更は最小限にする。実装の変更は不要である（第3章）。

## 1. 承認判断表

| ID | 提案 | 推奨 | 変更が必要な上位契約 | 互換性への影響 | OWNER判断 |
|---|---|---|---|---|---|
| P1 | 公開実体は、Validate済みの整数cm JSON | 採用 | 標高API契約 §6.1、§6.2、§9（T10・T12）、§11 | 公開形式の変更。API応答には影響しない | 未判断 |
| P2 | Coverageは、XYZタイル参照で表す | 採用 | Dataset Registry §3.4、標高API契約 §6.1 | UNDECIDEDだった項目の確定。既存データへの影響はない | 未判断 |
| P3 | 元データの基準日を確認できない場合は `data_reference_date = null` | 採用（確認的） | 標高API契約 §4.1（文言の明確化のみ） | なし（現契約と同じ挙動） | 未判断 |
| P4 | 未定義のAPIパスは404（`not_found`） | 採用 | 標高API契約 §5 | エラーコードの追加。既存のコードの意味は変わらない | 未判断 |
| P5 | API設定は設定ファイル（`api/elevation/conf/api.json`）で管理する | 採用（確認的） | 標高API契約 §7（ファイル名とSchemaの明記のみ） | なし（§7の値・範囲と同じ） | 未判断 |
| P6 | 現行Registryは、ポインタの原子的な置換で切り替える | 採用 | Data Publish §5・§6・§10、標高API契約 §7に「標高APIでの方式」を追記 | 汎用方式は固定しない。Generation（§7）とは独立 | 未判断 |
| P7 | Publishの認可には、ライセンスと出典URLが必要 | 採用 | Dataset Registry §5、Data Publish §6（手順2） | 認可を厳しくする方向のみ（従来の許可が新たに拒否されることはありうる） | 未判断 |

「OWNER判断」の欄は、OWNERが記入する。本書の作成者は承認を記入しない。

## 2. 提案ごとの内容

### P1 公開実体はValidate済みの整数cm JSON

- **採用理由**
  - Validateに合格したバイト列（`hererisk-elevation-cm-json-v0.1`）を、そのまま公開できる。
  - APIでPNGを再び復号する必要がなくなり、APIの依存（pypngとPNGの検査コード）が減る。
  - 公開実体のchecksumが、Validateの対象と完全に一致する（Dataset Registry §5-3「検証対象と公開実体が対応している」を直接満たす）。
- **差分**
  - 標高API契約 §6.1
    - 旧: 「最小の公開単位候補は『1件のDEM10B/Z14 PNGタイルを1データセット』とする」
    - 新: 「最小の公開単位は、1件のDEM10B/Z14タイルを1データセットとする。公開実体は、そのタイルのPNGを正規化・Validateした整数cm JSON（`publication.format = hererisk-elevation-cm-json-v0.1`）とし、Validateが検査したバイト列を変更せずに公開する。取得したPNGは取得証跡として保持し、公開しない」
  - 標高API契約 §6.2: 復号式はNormalize工程の規則とする。APIは整数cmを100で割って `elevation_m` を返すだけで、PNGを復号しない。
  - 標高API契約 §9: T10の「PNGが欠落」とT12の「破損PNG」は、それぞれ「公開実体（JSON）が欠落」「公開実体がprofileに違反」と読み替える。
- **互換性**: API応答の7キー・statusは変わらない。公開済みのデータはない（fixture・テストのみ）ため、移行は不要。

### P2 CoverageはXYZタイル参照

- **採用理由**: 1データセットが1タイルなので、タイル番号で範囲を一意に表せる。選択の境界規則（半開区間）が、ルックアップの規則と同じになる。
- **差分**: Dataset Registry §3.4に、標高APIでの値を追記する。
  - `coverage.ref = "xyz:<z>/<x>/<y>"`
  - `coverage.mode = "xyz_tile"`
  - `coverage.bbox`: EPSG:4326 の `[west, south, east, north]`（タイルの外接矩形。選択には使わない）
  - `coverage.crs = "EPSG:4326"`
  - `coverage.prefectures`: 公開したRegistryの都道府県
  - 選択: 地点のタイル（データセットのzoom）が `coverage.ref` と等しい場合だけ、その地点を覆う。Web Mercatorの範囲外は、どのデータセットにも覆われない。
- **互換性**: UNDECIDEDだった項目を、標高APIについてだけ確定する。他APIの形式は拘束しない。

### P3 `data_reference_date` は確認できない場合null

- 標高API契約 §4.1は、すでに「MVP 0では常にnull」としている。実装もnullを返す。
- **差分（明確化のみ）**: 「元データの基準日（測量時期）を公式資料で確認できない場合はnullとする。取得日・公開日・HereRisk公開版で代替しない」
- DEM10Bの測量時期は、公式資料ではまだ確認できていない（[GSI利用条件チェックリスト](../operations/gsi-dem10b-usage-checklist-v0.1.md) B-10）。

### P4 未定義のAPIパスは404

- **採用理由**: §5の表には、パスが存在しない場合のコードがない。§5は「no_dataはAPI経路やリソースの不存在ではないため404にしない」としており、パスの不存在に404を使うことと整合する。
- **差分**: §5の表に1行追加する: 「定義されていないパス | 404 | invalid_request | not_found | このエンドポイントはありません。」。検査順序の先頭（パス → メソッド → …）に位置付ける。
- **互換性**: 追加のみ。既存のコードの意味は変わらない。

### P5 API設定は設定ファイルで管理

- 標高API契約 §7は、すでに `request_body_max_bytes`（1024、256〜4096）と `evaluation_timeout_ms`（3000、100〜10000）を `api/elevation/conf` で定義するとしている。
- **差分（明確化のみ）**: ファイル名 `api/elevation/conf/api.json`、Schema `api.schema.json`、Configuration Managerの種別 `api` を明記する。管理画面・リクエストからは変更できない（変更なし）。

### P6 現行Registryポインタの原子的な切替

- **採用理由**: Data Publish §5・§6は「原子的に切り替える」「失敗時は旧Registryを維持する」ことを要求するが、方式は固定していない。標高APIでは、次の方式でこれを満たす。
- **差分**: 標高APIでの実装方式として追記する（Data Publishの一般方式は固定しない）。
  - 公開実体 `rel/versions/pub-<run_id>/<dataset_id>.json`、Registry改訂 `rel/registry/<pref>/revisions/rev-<run_id>.json` はどちらも新規作成のみで、上書きしない。
  - 現行ポインタ `rel/registry/<pref>/current.json`（`registry_revision`、`registry_sha256`、`previous_revision`）だけを、同じディレクトリ内でのrenameによって原子的に置換する。これが公開点である。
  - 都道府県ごとの公開ロックで、同時Publishによる更新喪失を防ぐ（Data Publish §10）。
  - 旧改訂・旧実体は削除しない。Generation・Restore（Data Publish §7・§8）は別途設計する。
  - APIは起動時に、ポインタ → 改訂のchecksum → 全実体のchecksumを検証したスナップショットを持つ（標高API契約 §7の「承認済み再起動で切り替える」と同じ）。
- **互換性**: 複数都道府県にまたがる原子的な切替（Data Publish §10）は、引き続きUNDECIDEDである。現在の実装は、1回のPublishで1都道府県だけを扱う。

### P7 Publishの認可にはライセンス・出典URLが必要

- **採用理由**: Dataset Registry §5-4（出典・利用条件・再配布条件の確認）を、認可の段階で機械的に確認する。
- **差分**: Data Publish §6の手順2「公開資格を確認する」に、次を追加する。
  - Publishの認可には、`license` と `attribution_url` が必要である。本番では、これに加えて承認記録に `attribution_text`（Source Definitionの出典文言と一致すること）と、`eligibility_status = approved` の公開資格が必要である（[本番認可設計](../architecture/production-authorization-v0.1.md)）。
  - これらが欠ける場合はAPPROVAL_REQUIREDで、公開領域に何も書かない。
- **互換性**: 制限を厳しくする方向のみ。

## 3. 実装への影響

P1〜P7はすべて、コミット `76fbc56` の実装と一致する。改訂を採用しても、実装の変更は不要である。Phase 1-F では、P7 を本番の承認記録（publication・eligibility）に拡張した。

## 4. FIXED契約との衝突の確認

- P1は、§6.1の「候補」を確定するものであり、FIXEDの項目を覆すものではない。
- P2は、Dataset RegistryのUNDECIDED項目を、標高APIについてだけ確定する。
- P4は追加のみ、P3・P5は既存の文言の明確化である。
- P6は、Data Publishが「固定しない」とした方式を、標高APIについてだけ定める。
- P7は制限を加える方向のみ。

重大な衝突はない。
