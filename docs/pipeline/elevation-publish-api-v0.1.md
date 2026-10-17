# Phase 1-D.3〜1-E 標高 本番形式パイプライン・Data Publish・Dataset Registry・公開API 実装仕様 v0.1

- 状態: **実装済み（モック・テスト専用の承認での自己テストのみ）**。実GSIの本番取得、実データのPublish、一般公開・デプロイは**未実施**であり、本書はそれらの完了を意味しない。
- 対象: Phase 1-D.3（本番形式パイプライン）、Phase 1-D.4（Data Publish・Dataset Registry）、Phase 1-E（`POST /api/v1/elevation`）
- 上位契約: [標高API詳細契約案](../api/elevation-contract-v0.1.md)、[Data Publish設計書](../architecture/data-publish-v0.1.md)、[Dataset Registry設計書](../architecture/dataset-registry-v0.1.md)、[Download契約](elevation-download-contract-v0.1.md)、[Normalize/Validate契約](elevation-normalize-validate-contract-v0.1.md)
- 上位契約との差分は第5章に「改訂提案」として列挙する。OWNERの承認まで、上位契約は改訂されていない。

## 1. 実装範囲とBLOCKEDの範囲

| 範囲 | 状態 |
|---|---|
| 本番コンテキストのDownload → Normalize → Validate（→ Publish）の連結 | 実装済み。**本番承認がないため、実行すると必ずBLOCKED（APPROVAL_REQUIRED、exit 3）** |
| 実GSI HTTPクライアントのパイプラインへの接続（`GsiHttpTransport`） | 実装済み。テストは偽の接続のみ。実GSIへの通信は一度も行っていない |
| Data Publish（不変の公開実体、Registry改訂、原子的な切替、旧Registryの保持） | 実装済み。fixtureのデータrootと、テスト専用承認のモック本番形式データで検証 |
| 公開API（HTTP、起動時検証、地点選択、7キー応答） | 実装済み。ループバックでのみ動作確認 |
| 本番承認ストア（本番の`Authorizer`） | Phase 1-F で実装（[本番認可設計](../architecture/production-authorization-v0.1.md)）。**本番の承認記録は存在しない**ため、本番の実行は引き続きBLOCKED |
| 実GSIの本番取得・実データPublish・一般公開・デプロイ | **未実施**（第6章の承認事項が必要） |
| Generation、Restore、Rollback、管理UI | 対象外（未実装） |

## 2. Phase 1-D.3 本番形式パイプライン

### 2.1 実行コンテキストと認可

- `run_pipeline(request, *, context)` は、全工程（download・normalize・validate・publish）の認可を**通信・書込みより前に**、同じコンテキスト・同じ工程名で取得する。1工程でも認可が得られなければ、その工程名でBLOCKEDを返し、何も書かない。
- 本番コンテキストの認可は `ProductionAuthorizer` だけが出す。これは常に `APPROVAL_REQUIRED` を返す（本番承認ストアは未実装）。
- fixtureの認可（`FixtureAuthorizer`）は本番コンテキストを出さない。fixture承認でPRODUCTIONを実行しようとするとBLOCKEDになる。
- Source Definitionの `approval_ref` が `null` の取得元（`gsi-dem10b-candidate` を含む）は、認可層が何であってもDownloadの前提条件でBLOCKEDになる。committedの `sources.json` は変更していない（`approval_ref=null`、`tiles=null` のまま）。
- テストの成功系は `tests/e2e_support.py` の `TestOnlyProductionAuthorizer` と、一時ディレクトリに作るSource Definitionの**テスト専用コピー**を使う。承認IDは `test-only-not-an-approval-*` である。本番コードからは使えず、本番承認ではない。

### 2.2 通信

- 外部へ通信するモジュールは `src/hererisk/elevation/net/gsi_http.py` だけである（Phase 1-D.1の `gsi_poc/http_fetch.py` を移動。旧パスは再エクスポートのみ）。定数は `net/gsi_limits.py` にある。
  - ホスト `cyberjapandata.gsi.go.jp`、HTTPS、ポート443
  - 接続・読込・全体のタイムアウトは5・10・30秒。本文は最大1 MiB
  - リダイレクトは追跡しない。`image/png` のみ受け付ける。Content-Encodingは拒否する。宛先がプライベートアドレスの場合は拒否する
- `GsiHttpTransport` は本番コンテキスト専用で、`^https://cyberjapandata\.gsi\.go\.jp/xyz/dem_png/<z>/<x>/<y>\.png$` だけを受け付ける。fixtureのURLや他レイヤーは拒否する。
- CLIは `--production --allow-network` の両方を指定した場合だけ実transportを組み立てる。`--allow-network` を単独またはfixtureと組み合わせて指定するとINVALID_INPUT（exit 2）になる。
- 自動再試行・並列取得・定期取得はしない。

### 2.3 証跡

- Download記録の `pipeline` は、本番コンテキストでは `elevation-download` / `0.1` である（fixtureは従来の値）。
- Normalize・Validateの記録の `execution_context` は `production` になる。Validateのprofileは `elevation-normalized-v0.1` である（fixtureは従来のprofile）。
- 再実行（`--resume-run-id`）は既存の証跡を再検証して再利用する。新たな通信はしない。

## 3. Phase 1-D.4 Data Publish・Dataset Registry

### 3.1 公開単位と形式（改訂提案P1）

- 1データセット = 1つのZ/X/Yタイル。`dataset_id = <source_ref>-z<z>-<x>-<y>`
- 公開実体は、Validateに合格した正規化JSON（`hererisk-elevation-cm-json-v0.1`）を**バイト単位で同一のまま**コピーしたものである。標高API契約 §6.1 はPNGの公開を想定しているが、APIでの再復号を避け、検証済みの値をそのまま提供するためにJSONを公開する（改訂提案P1）。
- `coverage`: `ref = "xyz:<z>/<x>/<y>"`、`mode = "xyz_tile"`、`bbox`（EPSG:4326のタイル範囲）、`prefectures`、`crs = "EPSG:4326"`（改訂提案P2）

### 3.2 配置

```text
<data_root>/elevation/rel/versions/pub-<run_id>/<dataset_id>.json      公開実体（不変）
<data_root>/elevation/rel/registry/<pref>/revisions/rev-<run_id>.json   Registry改訂（不変）
<data_root>/elevation/rel/registry/<pref>/current.json                  現行ポインタ（唯一の置換対象）
<data_root>/elevation/records/publications/<run_id>.json                公開記録
<data_root>/elevation/work/locks/publish-registry-<pref>.lock          都道府県ごとの公開ロック
```

現行ポインタ: `{schema_version, prefecture_code, registry_revision, registry_sha256, previous_revision}`

### 3.3 手順

1. 認可（`publish`）の公開条件（`license`・`attribution_url`）がそろっていること。ない場合はAPPROVAL_REQUIRED
2. 同じrunのValidate結果がSUCCESSであること。リージョンは1つだけ
3. 証跡を最初から再検証する: Downloadの照合、Validate・Normalizeの記録とハッシュ、候補ファイルのhash、`validate_candidate` の再実行、統計の一致
4. 都道府県ごとの公開ロックを取得する（待機あり）
5. 公開記録が既にある場合は、再検証して再利用する（何も書かない）
6. 現行Registryが既にこのrunの改訂を指している場合（切替後・記録前に中断したケース）は、記録だけを作って完了する
7. 公開実体を新規作成する（上書きしない。再開時に同名の実体があれば、同一であることを確認する）
8. 新Registry = 現行Registryのデータセットのうち今回のIDと重複しないもの + 今回のデータセット。Schemaを検査し、参照するすべての実体のchecksumを確認する
9. 改訂ファイルを新規作成し、ロック下で現行ポインタが変わっていないことを再確認する
10. `replace_pointer` で現行ポインタを原子的に置換する（同一ディレクトリ内でrename。**ここが公開点**）
11. 公開記録を新規作成する。失敗した場合はRECORD_COMMIT_FAILED（公開自体は有効。再実行すると手順6で記録が補完される）

- 手順10より前に失敗した場合、現行Registryは変わらない（旧Registry・旧実体はそのまま提供され続ける）。
- 旧改訂・旧実体は削除しない。`previous_revision` で直前の改訂を辿れる（Rollback機能は未実装）。
- ロックにより、同時のPublishによる更新喪失はない（テストで、ロックを外すと更新が失われることを確認した）。
- 保存層の権限: Download・Normalize・Validateの領域ビューからは `rel/` に書けない。Publishだけが `rel/versions`・`rel/registry`・`records/publications` に書ける。上書きできるのは `rel/registry/<pref>/current.json` だけである。

## 4. Phase 1-E 公開API `POST /api/v1/elevation`

### 4.1 起動

```sh
PYTHONPATH=src .venv/bin/python -m hererisk.elevation.api.server --data-root <DATA_ROOT> [--host 127.0.0.1] [--port 8000] [--fixture-demo]
# またはインストール後: hererisk-elevation-api --data-root <DATA_ROOT>
```

- 起動時に `rel/registry/*` のすべての現行ポインタ → 改訂のchecksum → Schema → ID重複 → 全実体のchecksum → `validate_candidate` を検証する。1つでも失敗すると起動しない（exit 3。パスや例外文は出力しない）。
- fixtureマーカーのあるデータrootは拒否する。`--fixture-demo` を指定した場合だけ受け付けるが、ループバックアドレスでのみ指定できる。
- 起動後のスナップショットは固定である。新しい公開を反映するには再起動する。
- 読み取るのは `rel/` だけで、書込み権限はない。API プロセスは Download・Normalize・Validate・Publishの工程、PoC、通信モジュールを読み込まない（テストで確認）。
- 設定は `api/elevation/conf/api.json`（Schemaあり）: `request_body_max_bytes = 1024`、`evaluation_timeout_ms = 3000`

### 4.2 検査順序（最初の失敗で終了）

パス（404）→ メソッド（405、`Allow: POST`）→ Content-Type（`application/json`、パラメータは `charset=utf-8` のみ）・Content-Encoding（`identity` のみ）（415）→ 本文サイズ（413）→ クエリ文字列（400）→ JSON構文（UTF-8、BOM不可、重複キー・NaN・Infinity不可）→ キーが `lat`・`lon` ちょうど → 型（数値。boolは不可）・有限 → 範囲（±90・±180。丸め・wrap・入替えなし）→ 選択 → 実体の整合性 → 読取・品質 → 欠損または値

HTTPアダプタでは、`Transfer-Encoding` 付き、または不正な `Content-Length` は415として扱う。本文は最大+1バイトまでしか読まない。

### 4.3 選択と応答

- データセットは、地点のタイル（データセットのzoom、ルックアップと同じ半開区間）が `coverage.ref` と一致する場合だけ地点を覆う。Web Mercatorの範囲外は何にも覆われない。都道府県が一致するだけでは選択しない。
- 応答は常に7キー: `hazard`、`location`、`status`、`result`、`dataset`、`error`、`evaluated_at`。ヘッダは `Content-Type: application/json`、`Cache-Control: no-store`。

| 状況 | HTTP | status | error.code | dataset |
|---|---|---|---|---|
| 標高値あり（0・負値を含む） | 200 | success | — | あり |
| 公開データの範囲外 | 200 | no_data | no_coverage | null |
| 欠損画素 | 200 | no_data | elevation_nodata | あり |
| 実体の読取I/O失敗・評価タイムアウト | 503 | retrieval_failed | data_unavailable | あり |
| 実体の欠落 | 500 | indeterminate | published_data_missing | null |
| 実体のchecksum不一致 | 500 | indeterminate | dataset_integrity_error | null |
| 実体の品質検査不合格 | 500 | indeterminate | data_quality_error | あり |
| 複数データセットが同じ地点を覆う | 500 | indeterminate | ambiguous_dataset | null |
| 入力不正・クエリあり | 400 | invalid_request | invalid_input | null |
| 本文が大きすぎる | 413 | invalid_request | request_too_large | null |
| メソッド不可 | 405 | invalid_request | method_not_allowed | null |
| 形式不可 | 415 | invalid_request | unsupported_media_type | null |
| パス不明 | 404 | invalid_request | not_found（改訂提案P4） | null |
| 想定外の例外 | 500 | retrieval_failed | internal_error | null |

- `invalid_request` では `location` と `evaluated_at` はnullである。それ以外では、`location` は入力値そのもの、`evaluated_at` はミリ秒のUTC。
- `dataset` は公開情報だけを返す: `id`、`publication_version`、`source{provider, page_url}`、`published_at`（ミリ秒のUTC）、`data_reference_date`（null。改訂提案P3）、`attribution{text, license, url}`。内部パス・checksum・Registry改訂名は返さない。
- `elevation_m = 整数cm / 100`

### 4.4 ログ

- 1リクエストにつき1件。サーバーが生成した `request_id`、公開status、error_codeだけを出す。緯度経度・パス・クエリ・本文・データrootは出さない。標準ライブラリのアクセスログは無効にしている。

## 5. 上位契約への改訂提案（OWNER判断事項）

| ID | 内容 | 理由 |
|---|---|---|
| P1 | 公開実体をPNGではなく、検証済みの正規化JSON（`hererisk-elevation-cm-json-v0.1`）とする（標高API契約 §6.1） | APIでのPNG再復号をなくし、Validateに合格したバイト列をそのまま提供するため |
| P2 | `coverage.ref` の形式を `xyz:<z>/<x>/<y>`、`coverage.mode = xyz_tile` とする | §6.1でOWNER判断とされていたCoverage参照の形式 |
| P3 | `dataset.data_reference_date` は、確認済みの基準日がないためnullとする | 測量時期が未確認のため（推測しない） |
| P4 | パス不明に `not_found`（404）を追加する | 契約 §5 にパス不明のコードがない |
| P5 | 公開APIの設定ファイル `api/elevation/conf/api.json`（本文上限・評価タイムアウト）を追加する | 設定をコードに埋め込まないため |
| P6 | Registryの現行ポインタ方式（`current.json` の原子的な置換。上書きを許す唯一のファイル）を採用する | 原子的な切替と旧Registryの保持のため |
| P7 | Publish認可に公開条件（`license`、`attribution_url`）を必須とする | 出典・利用条件のない公開を防ぐため |

## 6. 実GSIの本番取得・公開に必要な承認事項（未承認）

1. 本番承認ストアの設計の承認（Phase 1-F で実装済み）と、承認記録の登録（[Runbook](../operations/elevation-production-runbook-v0.1.md)）
2. `gsi-dem10b-candidate` の有効化: `approval_ref`、対象タイル、鉛直基準の確認結果、出典文言、利用条件レビューの記入
3. 国土地理院コンテンツ利用規約に基づく、再配布・公開条件（license・attribution_url・出典表示）の確定
4. 取得規模・間隔・実行者・実行環境の承認
5. 鉛直基準・測量時期・2025年改定の反映状況の確認と、確認できない場合の採否
6. 改訂提案P1〜P7の採否
7. 公開API のデプロイ先、公開範囲、運用・監視の承認
