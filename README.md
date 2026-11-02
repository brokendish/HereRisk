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
  - 現行の正本: [Flood Official Data Presentation Contract（案）](docs/architecture/flood-official-data-presentation-contract-v0.1.md)、[Flood Source Catalog / Identity Contract（案）](docs/architecture/flood-source-catalog-identity-contract-v0.1.md)（[検討記録](reviews/phase2/phase2c1-source-catalog-identity-contract.md)）、[Flood API MVP Contract（案）](docs/api/flood-api-mvp-contract-v0.1.md)、[Flood Normalize Contract（案）](docs/architecture/flood-normalize-contract-v0.1.md)、[Flood Integration Contract（案）](docs/architecture/flood-integration-contract-v0.1.md)
  - 方式移行の記録: [Phase 2-B.17 設計の全面整合レビュー](reviews/phase2/phase2b17-official-data-presentation-realignment.md)
  - 履歴資料（**現行仕様ではない。実装根拠として使用禁止**）: [Flood Source Priority Contract](docs/architecture/flood-source-priority-contract-v0.1.md)、[Flood Source Selection Contract](docs/architecture/flood-source-selection-contract-v0.1.md)、Phase 2-B.9〜B.16のレビュー（`reviews/phase2/phase2b9`〜`phase2b14`）
- Phase 2-C 公式データ取得元台帳（5つのAPIの取得可否・利用条件の確認状況。**取得・公開の承認ではない**）: [台帳の設計（案）](docs/architecture/official-source-ledger-v0.1.md)、[台帳JSON](docs/data-sources/official-source-ledger.json)、[調査報告](reviews/phase2/phase2c-official-source-availability-survey.md)、[入力形式・座標精度の方針（案）](docs/architecture/hazard-source-format-precision-policy-v0.1.md)

## Location API v0.1（Phase 3-A サービス骨格）

緯度・経度から、住所・標高・洪水・津波・高潮・土砂災害を1つのJSONで返すAPIの骨格です。契約は [Location API v0.1](docs/api/location-api-v0.1.md) にあります。

- 現状では、すべてのProviderが**未接続**で `not_available` を返します。
- 公式データ・外部APIには接続しません。
- 起動できるのはループバックのアドレスだけです。

```sh
# 起動（既定: 全Provider未接続）
PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001

# 確認
curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.681236&lon=139.767125"

# 画面確認用の合成データ（mode: "sample"、全セクションに synthetic: true）
PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 --sample-data

# テスト
.venv/bin/python -m pytest -q tests/contract/test_location_api.py
```

### 標高APIへの接続（Phase 3-B、ローカル確認）

`elevation` セクションだけを、既存の標高API（Fixtureデータ）に接続します。ほかのProviderは未接続のままです。

```sh
# 1) Fixtureのデータrootを用意してPublishする（初回のみ。詳細は docs/development/phase1a1-download-fixture-usage.md 第3.7節）
DATA_ROOT=$(mktemp -d)
PYTHONPATH=src .venv/bin/python -m hererisk.cli init-fixture-root --data-root "$DATA_ROOT"
PYTHONPATH=src .venv/bin/python -m hererisk.cli pipeline --api elevation --region 13 \
  --source fixture-dem-png-tokyo --fixture tests/fixtures/elevation-fixture --data-root "$DATA_ROOT" --publish

# 2) Bearer Tokenのファイルをリポジトリの外に0600で作る
TOKEN_FILE=$HOME/.hererisk-local/api-token
mkdir -p "$(dirname "$TOKEN_FILE")" && (umask 077; .venv/bin/python -c "import secrets;print(secrets.token_urlsafe(32))" > "$TOKEN_FILE")

# 3) 標高API（Fixture、ループバック）を起動する
PYTHONPATH=src .venv/bin/python -m hererisk.elevation.api.server \
  --data-root "$DATA_ROOT" --host 127.0.0.1 --port 8000 --fixture-demo --auth-token-file "$TOKEN_FILE"

# 4) 別のターミナルで、Location APIを標高API接続モードで起動する
PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 \
  --elevation-api http://127.0.0.1:8000 --elevation-token-file "$TOKEN_FILE" --elevation-fixture

# 5) 問い合わせる（FixtureのCoverage内の地点）
curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.701882&lon=139.713178"
# "elevation": {"status":"available","result":{"elevation_m":81.44,"unit":"m"},"synthetic":true,...}
```

- Fixtureの値は実際の標高ではありません。そのため `--elevation-fixture` を付け、応答に `synthetic: true` が付きます。
- Coverage外の地点（例: 東京駅）は、`not_available`（`reason: "no_coverage"`）になります。
- 標高APIを止めると `error`（`upstream_unreachable`）になり、ほかのセクションはそのまま返ります。

### 住所の接続（Phase 3-C、国土交通省「位置参照情報」）

`address` セクションを、国土交通省「大字・町丁目レベル位置参照情報」（東京都）に接続します。結果は、最寄りの代表点による推定住所です（`is_confirmed_address: false`）。

1. データを取得する。[ダウンロードサービス](https://nlftp.mlit.go.jp/cgi-bin/isj/dls/_choose_method.cgi)で、「都道府県単位」→「東京」→「大字・町丁目」の最新版（2025年版は `13000-19.0b.zip`）を選び、利用約款に同意してダウンロードする。
2. ZIPは**リポジトリの外**（例 `~/hererisk-data/isj/`）に置く。展開しなくてよい。

```sh
# 住所のみ接続
PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 \
  --address-isj ~/hererisk-data/isj/13000-19.0b.zip

# 標高API（上の手順で起動済み）と同時に接続
PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 \
  --address-isj ~/hererisk-data/isj/13000-19.0b.zip \
  --elevation-api http://127.0.0.1:8000 --elevation-token-file "$TOKEN_FILE" --elevation-fixture

curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.681236&lon=139.767125"
# "address": {"status":"available","result":{"display_name":"東京都千代田区丸の内一丁目付近",
#   "precision":"chome","method":"nearest_representative_point","is_confirmed_address":false,"distance_m":36.7,...}}

# 実データでのテスト（データがある場合のみ実行される）
HERERISK_ISJ_DATA=~/hererisk-data/isj/13000-19.0b.zip .venv/bin/python -m pytest -q tests/contract/test_location_address.py
```

- 代表点から遠すぎる地点（他県・海上・国外）では、住所を返しません（`not_available`、`reason: "out_of_coverage"`）。
- ただし、都県境のすぐ外側では都内の住所を返すことがあります。許容距離と根拠は、契約の第8.2節にあります。
- 出典の表示は「位置参照情報 国土交通省」です（利用約款による）。測量・各種証明には使えません。

### 市区町村をN03のPolygonで判定する（Phase 3-D）

国土数値情報 N03（行政区域データ）のPolygonで先に市区町村を決め、その市区町村の代表点だけから町丁目を推定します。隣の市区町村や他県の住所を返さなくなります。

```sh
# shapelyを入れる（初回のみ）
.venv/bin/pip install -e '.[address]'

# N03 2026年版 東京都のZIP（Phase 2-C.3で取得済み。リポジトリの外に置く）
N03_ZIP=~/hererisk-research/phase2c3-hazard-downloads/zips/N03-20260101_13_GML.zip
# 未取得なら https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html の「東京」からダウンロード

PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 \
  --address-isj ~/hererisk-data/isj/13000-19.0b.zip --address-n03 "$N03_ZIP" \
  --elevation-api http://127.0.0.1:8000 --elevation-token-file "$TOKEN_FILE" --elevation-fixture

curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.6347&lon=139.5786"
# "address": {"status":"available","result":{"display_name":"東京都狛江市和泉本町一丁目付近",
#   "municipality_code":"13219","method":"municipality_polygon_and_nearest_point",...}}

# テスト（実データのテストは、パスを指定した場合だけ実行される）
HERERISK_ISJ_DATA=~/hererisk-data/isj/13000-19.0b.zip HERERISK_N03_DATA="$N03_ZIP" \
  .venv/bin/python -m pytest -q tests/contract/test_location_municipality.py
```

- 境界から10m以内の地点は `unknown` になります（候補の市区町村を列挙）。
- 町丁目の代表点が遠い地点では、市区町村までを返します（`precision: "municipality"`）。
- N03は、メタデータにある測量法の複製承認の記載の扱いが未確認です。そのため、ローカルでの検証に限ります（詳細は契約の第8.3節）。

### 複数の都道府県を登録する（Phase 3-E）

都道府県ごとのデータを、地域ファイル（JSON、**リポジトリの外**）に登録します。東京都と神奈川県で確認済みです。

```sh
# ~/hererisk-data/regions.json（相対パスはこのファイルの場所が基準）
cat > ~/hererisk-data/regions.json <<'JSON'
{"regions": [
  {"prefecture_code": "13", "address_isj": "isj/13000-19.0b.zip", "address_n03": "n03/N03-20260101_13_GML.zip"},
  {"prefecture_code": "14", "address_isj": "isj/14000-19.0b.zip", "address_n03": "n03/N03-20260101_14_GML.zip"}
]}
JSON

PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 \
  --address-regions ~/hererisk-data/regions.json \
  --elevation-api http://127.0.0.1:8000 --elevation-token-file "$TOKEN_FILE" --elevation-fixture

curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.4658&lon=139.6223"   # 横浜駅
# "address": {"status":"available","result":{"display_name":"神奈川県横浜市西区南幸一丁目付近","municipality_code":"14103",...}}

# 実データでのテスト（地域ファイルがある場合のみ実行される）
HERERISK_ADDRESS_REGIONS=~/hererisk-data/regions.json .venv/bin/python -m pytest -q tests/contract/test_location_regions.py
```

**地域の追加手順（3県目以降。コードの変更は不要）**

1. 位置参照情報を取得する。[ダウンロードサービス](https://nlftp.mlit.go.jp/cgi-bin/isj/dls/_choose_method.cgi)で「都道府県単位」→ 対象の県 →「大字・町丁目」の最新版を選び、利用約款に同意してダウンロードする（例: 埼玉県は `11000-19.0b.zip`）。
2. N03を取得する。[N03のページ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html)から、対象の県のZIPをダウンロードする（例: `N03-20260101_11_GML.zip`）。
3. 2つのZIPを、リポジトリの外（例 `~/hererisk-data/isj/`・`~/hererisk-data/n03/`）に置く。展開しなくてよい。
4. 地域ファイルに1件追加する: `{"prefecture_code": "11", "address_isj": "isj/11000-19.0b.zip", "address_n03": "n03/N03-20260101_11_GML.zip"}`
5. Location APIを再起動する。

- コードの不一致（ファイル名・ファイルの中身と `prefecture_code` の不一致）、重複、データの不正があれば、起動しません（終了コード3。理由を表示）。
- 地域ファイルには、ローカルのパスが入ります。Gitに入れないでください。

## Data Inventory（Phase 3-F、データ管理の見える化・読み取り専用）

登録済みのデータを、地域・種類・年度・ファイルの状態・出典・利用条件・公開承認の別に一覧表示します。

情報は、それぞれの正本から読むだけです。

| 情報 | 読む先 |
|---|---|
| 地域とファイル | 地域ファイル |
| 取得元・利用条件・取得記録のSHA-256 | [取得元台帳](docs/data-sources/official-source-ledger.json) |
| ファイルの有無・サイズ | その場で実測 |

Inventory独自の「状態」は持ちません。

```sh
# 一覧（表）。地域ファイルに県を追加すれば、一覧にも自動で増えます
PYTHONPATH=src .venv/bin/python -m hererisk.data_inventory --regions ~/hererisk-data/regions.json

# JSON
PYTHONPATH=src .venv/bin/python -m hererisk.data_inventory --regions ~/hererisk-data/regions.json --format json

# SHA-256の実測（ファイル全体を読むため、明示した場合だけ）
PYTHONPATH=src .venv/bin/python -m hererisk.data_inventory --regions ~/hererisk-data/regions.json --hash

# ブラウザで見る（127.0.0.1のみ・読み取り専用）→ http://127.0.0.1:8090/  （JSONは /inventory.json）
PYTHONPATH=src .venv/bin/python -m hererisk.data_inventory --regions ~/hererisk-data/regions.json --serve --port 8090
```

**表示の意味**

- **SHA-256（記録）**: 取得元台帳の取得記録の値です。**SHA-256（実測）**: `--hash` を指定したときに計算した値です。両者は区別して表示します。
- **利用条件**: 取得元台帳の状態です（承認済み／要確認／禁止／未確認）。台帳に記載がないデータは「未確認（台帳に記載なし）」です。
- **公開承認**: 台帳が「承認済み」で、かつOWNERの承認記録（`approval_ref`）を参照している場合だけ「承認済み」になります。それ以外はすべて「未確認」です。
- **API接続**: 地域ファイルに登録されていれば「設定あり」です。実行中のAPIが読み込んでいるかは分からないため、「実行中かは不明」と表示します。
- **公開状態**: 住所データはDataset Registryで公開していないため、「Registry未参照」と表示します。
- 画面から、データの取得・更新・削除・公開はできません。画面から任意のファイルを読む機能もありません。

実データのProviderへの切替え方は、契約の第8章に書いています。

## 洪水浸水想定区域（Phase 4-A、Flood Provider・ローカル検証）

`hazards.flood` を、国土数値情報 A31a（洪水浸水想定区域・**想定最大規模**）に接続します。公式データごとに独立して検索し、該当した区域を原典の浸水深区分のまま返します。比較・代表値・安全／危険の判定はしません。設計の正本は [提示契約（案）](docs/architecture/flood-official-data-presentation-contract-v0.1.md)・[Flood API契約（案）](docs/api/flood-api-mvp-contract-v0.1.md)、Location APIでの形は [契約 第8.5節](docs/api/location-api-v0.1.md) です。

**利用条件が未承認（取得元台帳 `review_required`）のため、ローカルでの検証に限ります。** 応答の各ソースにも `data_use.scope: "local_verification_only"`・`public_approval: "unconfirmed"` が入ります。

**1. データを置く（Gitの外。展開しない）**

[A31aのページ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31a-2025.html) のGeoJSON版ZIPを、データディレクトリ（例 `~/hererisk-data/a31a/`）に置きます。東京都で確認したのは次の3つです。ZIP名の `_10`／`_20` は河川の種別で、想定（シナリオ）ではありません。想定最大規模は、ZIPの中の `20_想定最大規模` フォルダだけを読みます。

| ファイル | 公表 | SHA-256（取得時） |
|---|---|---|
| `A31a-25_13_10_GEOJSON.zip` | 東京都（洪水予報河川・水位周知河川） | `ecef23e95ac75554bfd42e6156800291b7af27bca49198002eab6f0394fe9f93` |
| `A31a-25_13_20_GEOJSON.zip` | 東京都（その他の河川） | `3101bac42ebb9693f7c9f92d994b7eb60a2cfe2bf2659a21dfb2a0886885e0b4` |
| `A31a-25_83_10_GEOJSON.zip` | 関東地方整備局（東京都以外の区域も含む） | `e66542cecda1c2ed9e7cf74d3333512a65bdb334557410389e521e7c259bca35` |

**2. 地域ファイルに登録する**（`~/hererisk-data/regions.json` に `flood_sources` を追加。相対パスはこのファイルが基準）

```json
"flood_sources": [
  {"source_id": "local-a31a-2025-13", "organization": "東京都",
   "title": "洪水浸水想定区域（想定最大規模）東京都管理河川", "category": "flood_inundation",
   "format": "ksj-a31a-geojson", "scenario": "maximum", "data_year": "2025", "river_manager_code": "13",
   "service_region": {"prefecture_codes": ["13"]},
   "files": [{"path": "a31a/A31a-25_13_10_GEOJSON.zip", "distribution_code": "13", "ledger_entry": "ksj-a31a-2025-13-10"},
             {"path": "a31a/A31a-25_13_20_GEOJSON.zip", "distribution_code": "13", "ledger_entry": "ksj-a31a-2025-13-20"}]},
  {"source_id": "local-a31a-2025-83", "organization": "国土交通省 関東地方整備局",
   "title": "洪水浸水想定区域（想定最大規模）関東地方整備局管理河川", "category": "flood_inundation",
   "format": "ksj-a31a-geojson", "scenario": "maximum", "data_year": "2025", "river_manager_code": "83",
   "service_region": {"prefecture_codes": ["13"]},
   "files": [{"path": "a31a/A31a-25_83_10_GEOJSON.zip", "distribution_code": "83", "ledger_entry": "ksj-a31a-2025-83-10"}]}
]
```

- `distribution_code` は配布単位（`83` は関東地方整備局）で、都道府県コードではありません。検索する範囲は `service_region` の都道府県のN03（`regions` に登録が必要）で決まります。
- `river_manager_code` は、全地物の `A31a_203`（河川管理者）と一致しなければなりません。
- 登録すると、Data Inventoryにもファイルごとに表示されます（例「東京都 / 洪水浸水想定区域 / 2025年版 / 国土交通省 関東地方整備局 / ファイルあり / API接続設定あり / 利用条件: 要確認 / 公開承認未確認」）。
- **神奈川県などの追加**: 対象県のA31a ZIPを置き、`flood_sources` に1件追加する（関東地方整備局分を神奈川県でも検索するなら、その `service_region` に `"14"` を加える）→ 索引を作り直す。コードの変更は不要です。

**3. 検索用の索引を作る**（登録を変えたら作り直す。関東地方整備局分を含めて約2〜3分）

```sh
# Docker（索引はボリューム hererisk-flood-index に入る。データはRead Only）
docker compose --profile init run --rm flood-index
docker compose up -d            # Location APIが索引を読む（起動時に登録・ZIP・N03のSHA-256を照合）

# Dockerを使わない場合
PYTHONPATH=src .venv/bin/python -m hererisk.flood build --regions ~/hererisk-data/regions.json \
  --output ~/.hererisk-local/flood-index.sqlite
PYTHONPATH=src .venv/bin/python -m hererisk.location.server --port 8001 \
  --address-regions ~/hererisk-data/regions.json --flood-index ~/.hererisk-local/flood-index.sqlite
```

```sh
curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.681236&lon=139.767125"   # 東京駅
# "flood": {"status": "available",
#   "results": [{"source": {"source_id": "local-a31a-2025-13", "organization": "東京都", ...},
#                "river_name_in_source": "隅田川", "original_class": {"code": "1", "label": "0～0.5m未満"}, ...}],
#   "sources": [{"source_id": "local-a31a-2025-13", "zones": [...], "unknowns": [], ...},
#               {"source_id": "local-a31a-2025-83", "zones": [], "unknowns": [{"river_name_in_source": "荒川",
#                "reason": "invalid_geometry", "unknown_level": "L1", ...}, ...], ...}], ...}

# 区域の内部の追跡（原典のZIP・メンバー・地物番号。APIの応答には出さない）
PYTHONPATH=src .venv/bin/python -m hererisk.flood trace --index ~/.hererisk-local/flood-index.sqlite --zone-ref <loc-zn-...>
```

- `available`: どれかのソースに該当区域がある（全ソースの全区域を返す）。`no_match`: 対象地域の内部で、全ソースを検索して区域・判定保留・境界接触がない（**浸水しないことを意味しない**。A31aは評価済みの範囲を持たない）。`unknown`: 判定保留（無効形状）の範囲・区域の境界上・対象地域の境界上。`not_available`: 対象地域の外。`error`: 処理の失敗・件数の上限超過（部分結果は返さない）。
- 無効形状は修復しません。判定保留の範囲は、その構成の外接矩形（L1）です。**関東地方整備局の荒川などの大きな無効形状のため、東京都東部の多くの地点が `unknown` になります**（東京都の無作為な3,000地点で `unknown` 1,016・`available` 468・`no_match` 1,516）。派生形状による解消は、契約上BLOCKED（OWNER承認待ち）です。
- 妥当性の検査はGEOSの1つだけです（契約は独立した2つを求める）。そのため `candidate_completeness: "not_guaranteed"` と `limitations` を応答に入れています。

### 原典との照合・自動検証（Phase 4-B）

Flood Providerの結果を、公式A31aの原典ZIPと機械的に照合します。期待結果は、索引・Provider・索引生成の処理を使わず、原典ZIP（とN03）を別の実装で直接読んで計算します（`hererisk.flood.verify`）。

```sh
# Docker（データ・索引はRead Only、レポートは ~/.hererisk-local/reports。Linuxではこのディレクトリをuid 10001が書けるようにする）
mkdir -p ~/.hererisk-local/reports
docker compose --profile verify run --rm flood-verify
docker compose --profile verify run --rm flood-verify python -m hererisk.flood verify --regions /data/regions.json \
  --index /var/lib/hererisk-flood/flood-index.sqlite --report-dir /reports --source local-a31a-2025-13 --point 35.625065,139.573836

# Dockerを使わない場合
PYTHONPATH=src .venv/bin/python -m hererisk.flood verify --regions ~/hererisk-data/regions.json \
  --index ~/.hererisk-local/flood-index.sqlite --report-dir ~/.hererisk-local/reports [--source ID] [--per-category 40] [--per-rank 10] [--seed 20261102] [--point LAT,LON]
```

1. **来歴**: 原典ZIPのSHA-256（今の値と索引作成時の値）、登録内容、プログラム・GEOSの版、入力条件。
2. **原典と索引の照合（全件）**: 成果品ごとの地物数・構成Polygon数・無効形状の数。地物数は、行の解析とは別に、バイト列中の `"type":"Feature"` の数でも数える。索引の全行について、地物・構成の番号、属性、浸水深区分、外接矩形、形状（完全一致）、判定保留の理由を確認する。対象地域から10m以内に関係しうる地物が、索引から欠けていないことも確認する。
3. **地点の照合（抽出）**: 固定のSeedで、原典から地点を区分ごとに抽出する。区分は、有効な区域の内部（浸水深区分ごとにも抽出）、同じソース内の重なり、浸水深区分が異なる重なり、2つのソースの重なり、穴、区域の頂点（境界）、無効形状の外接矩形、対象地域内の該当なし、対象地域外、対象地域の境界。

| 判定 | 意味 |
|---|---|
| `PASS` | 原典から確定できる結果と一致 |
| `FAIL` | 原典から確定できる結果と不一致（状態・区域・浸水深区分・河川・判定保留の集合のいずれか） |
| `INDETERMINATE` | 一致したが、無効形状の範囲が地点を覆うため、原典からも確定できない（PASSに数えない） |
| `OUT_OF_SCOPE` | 登録した対象地域の外で、Providerも対象外と返した |
| `ERROR` | 検証の処理自体の失敗 |

- 標準出力に要約を表示します。`--report-dir` には `summary.json`（来歴・照合・集計）、`points.jsonl`（全地点。再現用の座標を含む）、`cases.json`（原因ごとの代表例）を保存します。
- `INDETERMINATE` の地点では、無効形状を3つの読み方（偶奇規則・GEOSの `make_valid`・外周だけ）で見た結果も参考として出力します。**判定や浸水深には使いません。**
- 終了コードは次のとおりです。0: FAIL・ERRORがなく、照合も一致。1: FAILまたは照合の不一致。2: 引数の誤り。3: 検証の処理の失敗。
- 抽出した地点の一致は、全区域の正しさを保証するものではありません。別の都道府県でも、登録と索引があれば同じコマンドで検証できます。

**東京都での結果（2026-11-02、Docker、Seed 20261102、732地点、約5分）**

- 原典と索引の照合は、2つのソースとも一致した（東京都 261,706行、関東地方整備局 126,442行の全行。原典の地物 261,312・2,438,935、無効の構成 1,943・40,853。対象地域の10m以内に関係する地物の欠落なし）。3つのZIPのSHA-256も、索引の作成時と一致した。
- 地点: `PASS` 179、`FAIL` 0、`INDETERMINATE` 435、`OUT_OF_SCOPE` 118、`ERROR` 0。`INDETERMINATE` の原因は、すべてGEOSの無効形状である（関東地方整備局の「Ring Self-intersection」（頂点での自己接触）、東京都の「Interior is disconnected」と自己接触）。
- 狛江市東和泉（35.625065, 139.573836）: 原典の有効な区域には該当がない。関東地方整備局の無効な9つの構成（多摩川・浅川・大栗川）の外接矩形に入るため、`unknown` になる。そのうち3つ（3河川のランク3「3.0～5.0m未満」）は、参考の3つの読み方がすべて「内部」と読む。自己接触の位置は地点から1.5〜3km離れている。つまり、原典に区域がないのではなく、無効形状のため確定できない。

### 無効Polygonの局所解析 PoC（Phase 4-C、診断専用）

無効Polygonについて、地点を中心に小さな範囲から解析範囲を広げ、原典の頂点だけで内外を読めるかを調べるPoCです（`hererisk.flood.local_analysis`）。**Flood Providerの判定・応答、索引、原典は変更しません。** 結果は診断情報であり、確定した浸水深としては使いません。

```sh
docker compose --profile verify run --rm flood-local-analysis       # 指定地点 35.625065,139.573836 を含む
PYTHONPATH=src .venv/bin/python -m hererisk.flood local-analysis --regions ~/hererisk-data/regions.json \
  [--index <index.sqlite>] [--settings <flood-settings.json>] [--source ID] [--per-category 30] [--per-rank 5] \
  [--defect-points 40] [--seed 20261102] [--point LAT,LON] [--report-dir ~/.hererisk-local/reports]
```

**方式（`local`）**: 輪郭を切ったり、つないだり、作り直したりはしない。

- 構成ごとに、事前に次を求める（データ登録時に移せる処理）。
  - 線分
  - 各リングの向き（符号付き面積）
  - 問題箇所: 隣接しない線分が接する・交わる位置。自己接触、交差、リング同士の接触を含む
- 地点ごとに、半径 5 → 10 → 25 → 50 → 100 m の順で次を判定する。

| 状況 | 結果 |
|---|---|
| 半径内に問題箇所がある | 判定不能 `defect_within_radius` |
| 半径内に輪郭がない | 次の半径へ（最大半径でもない場合は `no_boundary_within_max_radius`） |
| 最寄りの輪郭がある | 輪郭のどちら側にあるかと、遠方を含む全輪郭の回転数（外周＋穴）が一致したときだけ inside / outside。一致しなければ `inconsistent_winding` |

局所的に輪郭が正常であることだけを、内部の根拠にはしない。

**比較する読み方（診断用）**: 次の読み方を、地点ごとに記録します。

- GEOS `make_valid`
- 偶奇規則（Phase 4-B）
- 外周だけ
- 回転数
- 解析範囲で切り出した形状（`clip_rect`）
- 比較専用の方針 `local_plus_far`: 最大半径でも輪郭がないとき、遠方の回転数を採用する

**対照**: 同じ地点の有効な構成も同じ方式で解析し、GEOSの `contains` と比べる。

**設定**: `{"local_analysis": {"enabled": false, "initial_radius_m": 5, "expansion_radii_m": [10, 25, 50, 100], "max_radius_m": 100}}` の形式です（`hererisk.flood.settings`）。

- すべてのキーが必須です。
- 半径は昇順で、最大半径は最後の半径と等しくします。
- `enabled: true` は現版では拒否します。
- `describe()` が、将来のData Managerの画面向けに項目の定義を返します。
- Flood Providerはこの設定を読みません。

**レポート**: `--report-dir` に次を保存します。

- `summary.json`
- `points.jsonl`: 全地点・全構成・半径ごとの結果
- `cases.json`: 代表例
- `svg/`: 原典の輪郭・問題箇所・解析半径の図

**終了コード**:

- 0: 正常
- 1: 対照の不一致、半径による読みの反転、Providerの `unknowns` と解析対象の不一致
- 2: 引数・設定の誤り
- 3: 処理の失敗

同じ環境（同じイメージ）では、同じSeedで同じ地点を抽出します。MacのホストとLinuxのコンテナでは、GEOSの演算のわずかな差により、重なりの形状から抽出する区分の途中から地点が変わることがあります。

**東京都での結果（2026-11-02、Docker、Seed 20261102、601地点、約4.5分）**

- **指定地点（35.625065, 139.573836）**: 無効な9構成の内訳は次のとおり。
  - ランク3の3構成（多摩川・浅川・大栗川）: 25mの半径で、19m先の輪郭の内側と読めた。回転数は1。最寄りの問題箇所は212〜234m先（4-BでGEOSが示した1か所は、最初に見つかった問題箇所にすぎない）。
  - ランク2の3構成: 100mの半径で、55〜57m先の輪郭の外側と読めた。
  - 残るランク3の3構成: 100m以内に輪郭がなく、`local` では決まらない。遠方の回転数は0（外部）。
  - したがって `local` では地点全体を確定できない。`local_plus_far` なら、3河川とも「3.0～5.0m未満」になる。
- **無効構成と地点の組（2,113組）**:
  - `local` で決まったのは1,008組（outside 681・inside 327）。決まった組は、make_valid・偶奇規則と全件一致した。
  - 決まらなかった組の内訳は、100m以内に輪郭なし 976、半径内に問題箇所 67、輪郭上 46、最寄りの輪郭が複数で側が一致しない 16。
  - 半径で読みが反転した組は0件。
- **地点（無効構成を含む357地点）**: すべての構成が決まったのは、`local` で64地点（17.9%）、`local_plus_far` で273地点（76.5%）。
- **対照**: 有効な構成1,104組で、決まった891組はGEOSの `contains` と全件一致した。
- **Providerとの照合**: Providerの `unknowns` と解析対象は601地点すべてで一致した。Providerの応答は変わらない。
- **処理時間**（無効構成を含む地点）:
  - 地点あたり: 中央値1.8ms、p95 5.7ms、最大13.6ms
  - 1半径あたり: 中央値 約0.05ms
  - 事前処理（線分化・問題箇所の検出）: 構成あたり中央値0.3ms、最大0.7s（35万線分）
  - `make_valid` の初回: 最大2.7s
- **メモリ**: 事前処理の結果は1,486構成で379MiB。ピークは約2.5GiBで、大半は検証用に原典を全件読む部分。

### 無効Polygonのオフライン前処理と軽量局所検索（Phase 4-D、診断専用）

Phase 4-Cの局所解析を、データ準備（オフライン）と地点検索に分けたPoCです（`hererisk.flood.diag`）。**Flood Provider・Location APIの応答、flood索引、原典ZIPは変更しません。** 結果は診断情報であり、公式の浸水深としては返しません。

```sh
docker compose --profile init run --rm flood-diag-build          # 前処理（flood索引の作成後・更新後に1回）
docker compose --profile verify run --rm flood-diag              # 指定地点 35.625065,139.573836 の診断
docker compose --profile verify run --rm flood-diag compare --flood-index /var/lib/hererisk-flood/flood-index.sqlite \
  --baseline /reports/flood-local-analysis-<日時> --report-dir /reports   # Phase 4-Cの結果との照合
docker compose --profile verify run --rm flood-diag bench --points /reports/flood-diag-compare-<日時>/bench-points.json
docker compose --profile verify run --rm flood-diag cases --cases /reports/flood-diag-compare-<日時>/regression-cases.json
```

**前処理（`diag build`）**

- **入力**: flood索引の判定保留の行（`usable = 0`）。Providerが `unknown` と答える構成そのもので、Phase 4-Bで原典と全行照合済み。作成時に原典ZIPのSHA-256を計算し直し、flood索引の記録と一致しなければ作成しない。
- **処理**: Phase 4-Cの方式（`local_analysis.Prepared`）で、リングごとの線分・向き・問題箇所と、その種類（接触・辺上の接触・重なり・交差）を求める。
- **保存先**: 独立したボリューム `hererisk-flood-diag` のSQLite。
- **保存形式**:
  - 線分: リングの64線分ごとの頂点列（float64）
  - 空間索引: 構成・頂点列・問題箇所それぞれにR-tree
  - `meta`: 形式と方式の版、元のflood索引の識別情報（作成日時・ZIPのSHA-256・ファイルのSHA-256）、登録内容、検証結果、状態
- **作成後の検証**: 全リングを頂点列から組み立て直し、flood索引の形状と一致することを確認する。
- **書き込み**: 一時ファイルに書き、完成してから置き換える。失敗しても既存のファイルは残る。

**地点検索（`DiagIndex`）**

- 原典ZIPもshapelyも使わず、起動時に何も読み込まない。
- 半径ごとに、その範囲の頂点列と問題箇所だけを読む。輪郭の側が分かったときは、構成の外接矩形から一番近い方向へ1本の光線を伸ばし、その上の頂点列だけで回転数を数える。
- 判定規則と計算は4-Cと同一。
- 次の場合は使用を拒否する。
  - `status` が `complete` でない
  - 形式または方式の版が違う
  - `--flood-index` を指定したとき、別のflood索引から作られている
- 半径は `local_analysis` の設定から読む。`compare` では、4-Cのレポートと半径が異なると拒否する（終了コード2）。

**終了コード**: 0 正常、1 4-Cとの不一致・ケースの不一致、2 引数・設定の誤り、3 索引の拒否・処理の失敗。

**東京都での結果（2026-11-02、Docker、4-CのSeed 20261102のレポートを基準）**

- **前処理**: 5,070構成（全件が判定保留の行と一致）、610万線分、21.7万頂点列、問題箇所52,602（すべて頂点での接触）。所要27秒、最大メモリ297MB、ファイル148MB。リングの組み立て直しの不一致は0。
- **4-Cとの一致**: 2,113組の全項目（半径ごとの結果・最終結果・到達半径・輪郭と問題箇所の距離・回転数・遠方の読み・浸水深区分・河川・ソース・線分数・問題箇所数）が一致した。保存した2,113件のケースの再実行も全件一致。
- **候補の構成**: 外接矩形だけで選ぶと、70地点で4-Cより多くなる。いずれも対象地域の判定をProviderが行うためで、地点検索ではProviderの `unknowns` を渡す。
- **A. make_valid と偶奇規則の不一致（15組・14構成）**: すべて地点がちょうど輪郭上（距離0）。GEOSの `contains` は境界を含めず、偶奇規則の光線は境界を内側に数える、という違い。局所解析は15組すべてを判定不能（輪郭上12・問題箇所が5m以内3）としており、機械的に判定不能と分類できる。
- **B. 半径を広げると判定不能になる組**:
  - 4-Cの668組は、無効な構成521組と、有効な構成（対照）147組の合計だった。対照の問題箇所は外周と穴の正当な接点で、GEOSの `contains` で判定される。
  - 521組の問題箇所はすべて頂点での接触。最初の結果に対して、make_valid・偶奇規則・回転数は521組すべてで一致した。
  - 「外周だけ」の読みが食い違う151組は、すべて「外部」と判定した組（穴の中の地点を、穴を無視して内部と読んだもの）。
  - 問題箇所までの距離と輪郭までの距離の比は、中央値8.1、最小1.2（2未満は44組）。
  - 最初の結果を維持する案（頂点での接触で、全読み方が一致: 370組）は記録するが、採用しない。
- **性能（軽量検索だけのプロセス、357地点）**:

| 項目 | Phase 4-C（メモリ上） | Phase 4-D（永続化索引） |
|---|---|---|
| 地点検索時の原典ZIPの読込 | 必要 | 不要 |
| 線分・問題箇所の準備 | 実行時 | オフライン（27秒） |
| ピークメモリ | 2.5GiB（検証プロセス全体） | 51MB（軽量検索だけ） |
| 地点あたりの応答時間 | 中央値1.8ms・p95 5.7ms・最大13.6ms | 中央値3.7ms・p95 11.4ms・最大16ms |
| 同じ地点の繰り返し（200回） | — | 中央値2.9ms・最大5.1ms |
| 起動 | 原典の読込に約2.3分 | 0.1ms |

### 診断結果の分類とLocation APIへのShadow統合（Phase 4-E、診断専用）

無効Polygonの診断結果を、`candidate`・`undetermined`・`rejected` に機械的に分類し、理由コードを付けます（`hererisk.flood.adoption`）。そのうえで、Location APIの洪水検索に並べて実行します（Shadow、`hererisk.location.flood_shadow`）。**正式な洪水判定と応答は変えません。** `candidate` は診断上の候補にすぎず、正式な区域への昇格でも浸水深でもありません。規則と理由コードの一覧は [Location API契約 8.6](docs/api/location-api-v0.1.md) にあります。将来の提示形式の案は [Stage 3案](docs/api/flood-diagnosis-stage3-draft.md) です（未実装）。

**設定**（`--flood-settings`、Phase 4-Cの形式と後方互換）

```json
{"local_analysis": {"enabled": false, "initial_radius_m": 5, "expansion_radii_m": [10, 25, 50, 100], "max_radius_m": 100},
 "diagnosis": {"shadow_enabled": false}}
```

- `local_analysis.enabled`（正式判定への組み込み）は引き続き拒否します。
- `diagnosis.shadow_enabled`（並行して診断するだけ）は許可します。
- `diagnosis` を省略した場合は無効です。

**受入手順**

```sh
docker compose build && docker compose --profile init run --rm flood-diag-build
# 1. 自動検証（4-Cの固定Seedの地点と、4-Dのケース。生成した地点だけを記録する）
docker compose --profile verify run --rm flood-shadow-verify \
  --baseline /reports/flood-local-analysis-<日時> --cases-dir /reports/flood-diag-compare-<日時>
# 2. Shadowを有効にしたAPI（127.0.0.1:8011）と通常のAPI（127.0.0.1:8001）の応答を比べる
docker compose --profile shadow up -d location-api-shadow
curl -s 'http://127.0.0.1:8011/api/v1/diagnostics/flood-shadow'     # 件数のみ（位置は含まない）
docker compose --profile shadow rm -sf location-api-shadow          # 確認後に止める（常駐させない）
```

`shadow-verify` の終了コード: 0 全項目合格、1 不合格の項目あり、2 引数の誤り、3 入力の拒否・処理の失敗。

**東京都での結果（2026-11-02、Docker）**

- **正式応答**: 4-Cの601地点で、FloodProvider単体とShadow経由の洪水セクションが全件一致しました。8スレッドの並列実行でも全件一致です。
  - HTTPでは、通常のAPIとShadowを有効にしたAPIで、2回×601地点の1,202件の応答全体（`evaluated_at` を除く）が一致しました。
- **診断対象**: 601地点すべてで、Providerの `unknowns` と同じでした（4-Cの対象とも一致）。
- **分類**: 2,113組のうち、`candidate` 473・`undetermined` 1,640・`rejected` 0です。
  - `candidate` 473件は、オフラインの `make_valid` と全件一致しました。`exterior_only` が異なるのは69件で、穴を無視する読み方のためです。
  - `undetermined` の理由別の内訳です。

| 理由 | 組数 |
|---|---:|
| `no_local_boundary` | 976 |
| `defect_within_max_radius` | 521 |
| `defect_within_decision_radius` | 67 |
| `service_region_boundary` | 56 |
| `on_boundary` | 46 |
| `ambiguous_nearest` | 16 |

- **4-Dのケース**:
  - A15組は、すべて `undetermined` です（`on_boundary` 12・`defect_within_decision_radius` 3）。
  - B521組も、すべて `undetermined`（`defect_within_max_radius`）です。1組には `service_region_boundary` も付きます。
- **性能**:
  - HTTPの応答時間: 通常は中央値1.75ms・p95 2.59ms、Shadowでは中央値1.86ms・p95 2.54ms。
  - 診断用スレッド: 1地点あたり中央値5.7ms・最大26ms。
  - メモリ: 575MiB対581MiB。診断索引を開いても常駐メモリはほとんど増えません。
  - 起動時の検証: 診断索引の `meta` とflood索引の `meta` を比べるだけです（ハッシュの再計算なし）。
  - 並列のバースト（8スレッド×601地点）では、キュー（64件）があふれた分の診断を省略し、件数として記録しました。正式な応答は待たせていません。
- **異常時**: 診断索引がない・壊れている・別のflood索引から作られている場合、Shadowを有効にしたAPIは起動しません（終了コード3）。実行中の失敗は `state: "error"` と件数で示します。

### Polygon判定理由の共通仕様と日本語メッセージ（Phase 4-F）

Polygon由来の判定で「判定できた範囲」と「判定できない理由」を日本語で伝えるための共通カタログです（`hererisk.common.polygon_reasons`）。仕様は [Polygon判定理由の共通仕様 v0.1](docs/api/polygon-reason-catalog-v0.1.md) にあります。**正式なLocation APIの応答とShadowの分類は変えません。**

- **理由コード**: 機械判定用の安定したコードで、既存のコード名をそのまま使います。文言は一か所で管理し、`message_version` で版を付けます。各コードは次の属性を持ちます。
  - 短い文言（`message_ja`）と詳しい説明（`detail_ja`）
  - category（geometry・coverage・data・processing・result）
  - 共通の概念（内側・外側・境界上・形状の不整合・境界の解釈が不確定・局所情報不足・対象地域の境界・データの不整合・処理の失敗・情報不足）
  - 代表メッセージの優先度
- **共通とハザード固有の分離**: 共通の文言は「対象区域」「区域データ」という中立の表現です。洪水は `hererisk.flood.reason_messages` で「浸水想定区域」の文言だけを登録します。津波・高潮・土砂災害も、同じ方法で自分の文言を登録できます。共通部分は、浸水深や警戒区域の区分を解釈しません。
- **解決**: `resolve_reason(code, hazard_type, locale)` は、ハザードの文言、共通の文言、汎用の文言の順に探します。未知のコードもそのまま保持し、`known: false` を付けます。`resolve_reasons` は全コードを保持したまま、代表メッセージを優先度で選びます（配列の順序には依存しません）。
- **洪水診断との接続**: `explain(record)` は、Phase 4-Eの分類記録を「利用者向け」と「技術詳細」の2層に分けます。技術詳細には、全理由コード・`source_id`・`zone_ref`・診断方式・版・`official: false` を含めます。
- **東京都での確認（2026-11-02）**:
  - `shadow-verify` の分類・理由・ソース別・4-Dのケース・`make_valid` との照合は、Phase 4-Eと同一でした。
  - 2,113組の理由コードは、すべてカタログで説明できました。
  - 代表メッセージの内訳です。

| 代表メッセージ | 組数 |
|---|---:|
| 周辺の境界情報だけでは、浸水想定区域内かどうかを確実に判定できません。 | 936 |
| 元の区域データの境界に不整合があるため、正確に判定できません。 | 520 |
| 参考の解釈です。正式な判定ではありません。 | 473 |
| 判定に必要な範囲で、区域データの形状に不整合が見つかりました。 | 66 |
| 提供データの対象地域の境界付近にあるため、判定できません。 | 56 |
| 浸水想定区域の境界上にあるため、区域内かどうかを確定できません。 | 46 |
| 周辺の区域境界が複雑なため、判定結果を確定できません。 | 16 |

### 洪水の参考解析API（Phase 4-G、初期値は無効）

1地点について、公式データによる洪水の判定と、HereRiskが無効Polygonを独自に解析した参考情報を、別々の情報として返すAPIです（`GET /api/v1/diagnostics/flood?lat=&lon=`）。契約は [洪水の参考解析API v0.1](docs/api/flood-diagnostic-api-v0.1.md) にあります。**`/api/v1/location` の応答とShadowは変えません。正式な洪水判定への採用は対象外です。**

- **分離**: `official_assessment` は `/api/v1/location` の `hazards.flood` と同じセクションです。参考解析は `diagnostic.interpretations[]` に、区域（`source_id`・`zone_ref`）ごとに入れます。公式の `zones` には混ぜません。区域・ソースをまとめた全体の判定や最大値は作りません。
- **対象**: 公式の検索で判定保留（`unknowns`）になった区域だけです。分類はPhase 4-E、文言はPhase 4-Fのカタログを使います。結果の文言（「この浸水深の想定区域に含まれる可能性があります。」「参考解析では、この想定区域の外側と解釈されました。」）は、理由コードとは別の種類としてカタログに登録しました。浸水深は、`candidate` で内側と読めたときだけ、原典の区分をそのまま示します。
- **上限**: 診断索引の接続2本（同時に使えるのは各1リクエスト）、1地点32区域、1秒です。超えたときは `busy`・`limit_exceeded`・`timeout` と理由を返し、一部だけの一覧は返しません。公式の判定はどの場合も返します。
- **有効化**: 設定 `diagnosis.api_enabled: true`（省略時は無効）と `--flood-diag-index` を指定します。Composeでは検証用の `location-api-diagnostic`（`--profile diagnostic-api`、`127.0.0.1:8012`）です。リバースプロキシにはつないでいません。
- **東京都での確認（2026-11-02、601地点・2,113組）**:
  - `/api/v1/location` は、APIの有効・無効で601地点すべて同一でした。`official_assessment` も `hazards.flood`・Flood Providerの答えと601地点すべてで一致しました。
  - 解釈の対象はすべて `unknowns` と一致しました。分類・理由・内外もPhase 4-Eとすべて同一でした。ケースA（15組）・ケースB（521組）はすべて `undetermined` のままです。

| 解釈 | 組数 |
|---|---:|
| `candidate_inside`（原典の浸水深区分を表示） | 118 |
| `candidate_outside` | 355 |
| `undetermined` | 1,640 |
| `rejected` | 0 |

  - 応答時間（HTTP、逐次）: 参考解析APIは中央値1.4ms・p95 10.7ms・最大17ms、`/api/v1/location` は中央値1.5msです。1地点の対象は最大15区域でした（上限32）。
  - 並列: HTTPで8・32並列の601リクエストは、すべて逐次と同じ答えでした。プロセス内の32並列では、601件中31件が `busy` を返しました（答えの変化はありません）。
  - メモリ: コンテナで577MiB（通常のLocation APIは583MiB）。診断索引の接続を開いても、常駐メモリはほとんど増えません。

**受入手順**

```sh
docker compose build && docker compose --profile init run --rm flood-diag-build   # 診断索引がなければ
# 1. 自動検証（4-Cの固定Seedの地点と、4-Dのケース。生成した地点だけを記録する）
docker compose --profile verify run --rm flood-diag-api-verify \
  --baseline /reports/flood-local-analysis-<日時> --cases-dir /reports/flood-diag-compare-<日時>
# 2. 参考解析APIを有効にしたAPI（127.0.0.1:8012）
docker compose --profile diagnostic-api up -d location-api-diagnostic
curl -s 'http://127.0.0.1:8012/api/v1/diagnostics/flood?lat=35.681236&lon=139.767125'
docker compose --profile diagnostic-api rm -sf location-api-diagnostic   # 確認後に止める（常駐させない）
```

`diag-api-verify` の終了コード: 0 全項目合格、1 不合格の項目あり、2 引数の誤り、3 入力の拒否・処理の失敗。

## Docker Compose（Phase 3-G、開発・実行環境）

Location API・標高API・Data Inventoryを、それぞれコンテナで起動します。MacとLinux VPSで同じ [compose.yaml](compose.yaml) と [Dockerfile](deploy/app/Dockerfile) を使います。

| サービス | Compose名 | ホスト側 | 備考 |
|---|---|---|---|
| Location API | `location-api` | `127.0.0.1:8001` | 標高APIへは `http://elevation-api:8000`（Composeネットワーク内） |
| 標高API | `elevation-api` | `127.0.0.1:8000` | Fixtureデータのみ（応答は `synthetic: true`）。Bearer Token必須 |
| Data Inventory | `data-inventory` | `127.0.0.1:8090` | 管理用。`--profile admin` のときだけ起動。別ネットワーク |

**データ・秘密情報の置き場所（どちらもGit・イメージの外）**

| 内容 | ホスト側（既定） | コンテナ内 |
|---|---|---|
| 地域ファイルと住所データ（`regions.json`・`isj/`・`n03/`） | `~/hererisk-data`（`HERERISK_DATA_DIR` で変更） | `/data`（Read Only） |
| Bearer Token（`api-token`） | `~/.hererisk-local/secrets`（`HERERISK_SECRET_DIR` で変更） | `/run/secrets/api_token`（Read Only） |
| 標高のFixture公開データ | Dockerボリューム `hererisk-elevation-data` | `/var/lib/hererisk`（APIからはRead Only） |
| 洪水の検索用索引（A31aから作成） | Dockerボリューム `hererisk-flood-index` | `/var/lib/hererisk-flood`（APIからはRead Only） |

`regions.json` の相対パスは、ファイルの場所が基準です。`isj/13000-19.0b.zip` は、コンテナ内では `/data/isj/13000-19.0b.zip` になります。データを複製・改名する必要はありません（[上の Phase 3-E](#複数の都道府県を登録するphase-3-e) の `regions.json` をそのまま使います）。

イメージに入るのは、アプリのコード・設定・[取得元台帳](docs/data-sources/official-source-ledger.json)・標高のFixtureだけです（[許可リスト](deploy/app/Dockerfile.dockerignore)）。コンテナは非root（uid 10001）・読み取り専用のファイルシステムで動きます。

```sh
# 初回のみ: Bearer Tokenを作る（既にファイルがあれば作らない）
mkdir -p ~/.hererisk-local/secrets && chmod 700 ~/.hererisk-local ~/.hererisk-local/secrets
docker compose --profile init run --rm token

# 初回のみ: 標高のFixtureを公開データとしてボリュームに入れる（2回目以降は「変更なし」）
docker compose build
docker compose --profile init run --rm elevation-init

# 初回のみ（洪水の登録を変えたら再実行）: 洪水の検索用索引を作る（上の「洪水浸水想定区域」の節）
docker compose --profile init run --rm flood-index

# 起動・状態・ログ・停止
docker compose up -d --build
docker compose ps
docker compose logs -f
docker compose down          # ボリュームと ~/hererisk-data は消えない（-v は付けない）

# 管理画面も起動する → http://127.0.0.1:8090/
docker compose --profile admin up -d --build
docker compose --profile admin down

# 確認
curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.4658&lon=139.6223"     # 横浜駅: 住所
curl -s "http://127.0.0.1:8001/api/v1/location?lat=35.701882&lon=139.713178" # Fixture範囲: elevation 81.44, synthetic: true
docker compose --profile admin exec data-inventory python -m hererisk.data_inventory --regions /data/regions.json   # 管理画面と同じ一覧（CLI）
```

- ソースコードを変えたら、`docker compose up -d --build`（管理画面も使うなら `--profile admin` を付ける）で作り直します。地域ファイルやデータを変えたときは、`docker compose restart location-api` で読み直します。
- `docker compose ps` で `healthy` になるまで、Location APIは数十秒かかります（N03・洪水の索引の読み込み）。メモリは約550MBです。ヘルスチェックは、既存のエンドポイント（`POST /api/v1/elevation`・`GET /api/v1/location`・`GET /inventory.json`）を使います。
- 標高APIは、Fixtureが未投入なら起動しません（未検証のデータでは応答しない）。先に `elevation-init` を実行してください。
- Linux（VPS）では、Tokenのファイルは実行ユーザー（uid 10001）の所有で0600である必要があります。`token` サービスで作れば、そうなります。
- VPSでも同じ `compose.yaml` を使います。`--profile admin` は付けず、管理画面は一般公開しません。使うときは、VPS上で一時的に起動し、SSHのポート転送（`ssh -L 8090:127.0.0.1:8090 <VPS>`）で見ます。一般向けの公開経路（リバースプロキシ）には、Location APIだけをつなぎます。
- Dockerを使わない起動方法（上の各節）も、そのまま使えます。

## 開発方針

- UNIX哲学
- 疎結合
- 小さなMVP
- 独立検証
- 不明を安全と判定しない

## 設定・データの責務分離

共有設定は `conf/common/`、API固有設定は `api/<api>/conf/` に配置し、commonのConfiguration Managerで読み込み・検証・解決します。[標高の取得定義](api/elevation/conf/sources.json)と[Schema](api/elevation/conf/sources.schema.json)を配置済みです。

API別データ領域・権限・設定発見の契約は[基本アーキテクチャ](docs/architecture/basic-architecture-v0.1.md)、改訂内容と確認結果は[API独立性改訂レビュー](reviews/phase0/api-isolation-contract-revision-v0.1.md)を参照してください。
