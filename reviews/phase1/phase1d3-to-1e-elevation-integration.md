# Verification Summary

## Metadata

- Task ID: `phase1d3-through-phase1e-elevation-production-api`
- Task: Phase 1-D.3 本番形式パイプライン、Phase 1-D.4 Data Publish・Dataset Registry、Phase 1-E 公開API `POST /api/v1/elevation`
- Implementer: Claude（実装・テスト・commit・push）
- Reviewer: Claude（自己検証。Codexの独立検証は今回実施しない指示）
- Target Commit: 本レビューと同じコミット（基準main `59b22519c77c6a20993764b93d5b039a573f5033`。commit前にfetchし、HEADとorigin/mainの一致を確認した）
- Status: **自己テストPASS**（実GSIへの通信なし。モックとテスト専用承認による検証のみ。この自己テストは最終受入ではない）
- OWNER Approval: Git運用ルールに基づきcommit・push。**実GSIの本番取得・実データPublish・一般公開・デプロイは実施していない。**

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/net/gsi_http.py`（`gsi_poc/http_fetch.py` から移動）、`net/gsi_limits.py`（新規） | 唯一の外部通信モジュールと、その定数。旧パスは再エクスポートのみ |
| `src/hererisk/elevation/download/gsi_transport.py`（新規） | 本番コンテキスト専用のGSI dem_png Transport（URLの厳密な照合） |
| `src/hererisk/elevation/publish/`（新規） | `registry.py`（Schema・ポインタ・実体の検証）、`stage.py`（PublishStage） |
| `src/hererisk/elevation/api/`（新規） | `handler.py`（入力検査・評価・7キー応答）、`published.py`（起動時検証済みスナップショット）、`server.py`（stdlib HTTPアダプタ） |
| `src/hererisk/elevation/tile_format.py`（新規） | タイル形式の定数。読取側（lookup・validate core・API）がDownloadの工程をimportしないように分離 |
| `src/hererisk/common/storage.py` | インスタンスごとの書込み・読取領域、`with_permissions`、`replace_pointer`（現行ポインタだけ置換可）、Publish用の領域。macOSの同時 `O_CREAT` によるENOENTに対するロック作成の再試行 |
| `src/hererisk/common/orchestrator.py`、`authorization.py` | `run_pipeline(context=…)`、全工程の事前認可（同一コンテキスト）、`publish` 操作と公開条件 |
| `src/hererisk/elevation/{download,normalize,validate}/` | 本番コンテキストのpipeline・profileの記録 |
| `src/hererisk/cli.py`、`pyproject.toml` | `pipeline --production / --allow-network / --publish`、`hererisk-elevation-api` |
| `api/elevation/conf/api.json`・`api.schema.json`（新規） | 公開APIの設定 |
| `tests/e2e_support.py`（新規）、`tests/contract/test_production_pipeline.py`・`test_publish_registry.py`・`test_elevation_api.py`（新規、計84件） | テスト専用の承認ダブル・偽GSI・E2E |
| `docs/pipeline/elevation-publish-api-v0.1.md`（新規）、使い方 第3.5〜3.7節、README | 仕様・改訂提案・起動手順 |

committedの `api/elevation/conf/sources.json` は変更していない（`gsi-dem10b-candidate` は `approval_ref=null` のまま）。

## Verification

| Check | Result |
|---|---|
| 全テスト | 881 passed（既存797 + 新規84） |
| 本番形式E2E（偽GSI・テスト専用承認） | 1・2タイルのDownload→Normalize→Validate→Publish→API。12.34 m・0 m・−1.2 m・欠損・範囲外・2.56 mを確認 |
| 本番のBLOCKED | 実 `ProductionAuthorizer`、未承認の実Source Definition、工程認可の欠如は、いずれも通信0回・書込み0件でBLOCKED。CLI `--production` はexit 3 |
| Publish | 不変実体のバイト同一コピー、原子的な切替、切替前の失敗（実体・改訂・ポインタ）で旧Registryを保持、切替後・記録前の中断からの完了、再実行で変化なし、再公開で旧改訂・旧実体を保持、同時Publishで更新喪失なし |
| 起動時検証 | ポインタ・改訂checksum・実体checksum（有効な候補のまま値だけ変えた場合を含む）・実体欠落・不明ディレクトリで起動拒否。fixtureデータrootの拒否 |
| API入力契約 | 重複キー（Unicodeエスケープを含む）、NaN・Infinity・1e309、bool・文字列・null、範囲外、BOM、余分なキー、クエリ、405（Allow）、415、413、404、検査順序 |
| API status | success・no_coverage・elevation_nodata・data_unavailable（I/O・タイムアウト）・published_data_missing・dataset_integrity_error・data_quality_error・ambiguous_dataset・internal_error（内部情報を出さない） |
| ログ | request_idあり。緯度経度・パス・データrootなし |
| HTTP | ループバックの実ソケットで、200・405・413・chunked/不正Content-Lengthの415・クエリ400 |
| APIプロセスの依存 | Download・Normalize/Validate/Publishの工程、PoC、通信モジュール、Orchestrator、認可を読み込まない（子プロセスで確認） |
| ミューテーション | 11の安全装置（公開ロック、Mercator範囲、厳密JSON、fixture拒否、Validate SUCCESS必須、ambiguous、リクエスト時のchecksum、bool拒否、実体checksum、公開条件、ログの座標）を1つずつ無効化し、すべてテストで検出した |
| 手動確認（Mac） | fixtureでPublishまで実行し、`--fixture-demo` でループバック起動。curlでsuccess・no_coverage・405・400を確認。fixtureでないモードではfixtureデータrootでexit 3 |

## Findings

1. **同時Publishでロックファイル作成が失敗する（修正済み）**: macOSでは、同じファイルへの同時 `open(O_CREAT)` が、ディレクトリが存在してもENOENTを返すことがあった。`exclusive_lock` を、ENOENTに限り有限回（5回）再試行するようにした。
2. **APIがDownloadの工程を間接importしていた（修正済み）**: lookup・validate coreがタイル定数を `download.download` から読んでいたため、APIプロセスにOrchestratorと認可が読み込まれていた。定数を `tile_format.py` に分離した。
3. **テストの抜け（追加済み）**: 実体checksumの検査は、破損データの検査が代わりに失敗させていたため、無効化しても検出されなかった。有効な候補のまま値を変えた実体のテストを追加した。公開条件の欠如のテストも追加した。

## Limitations

- 実GSIへの通信、本番承認、実データのPublish、一般公開、デプロイは行っていない。本番形式の成功系は、テスト専用の承認ダブル（`test-only-not-an-approval-*`）とSource Definitionのテスト専用コピーによるものであり、本番承認ではない。
- 本番承認ストアは未実装である（OWNER承認が必要な認可の変更）。
- 標高API契約との差分（JSON実体の公開、Coverage参照の形式、`data_reference_date` のnull、`not_found` など）は、[実装仕様](../../docs/pipeline/elevation-publish-api-v0.1.md) 第5章の改訂提案P1〜P7であり、未承認である。
- Generation・Restore・Rollback・管理UIは対象外である。単一ホストのflockを前提とする。
- Codexによる独立検証は未実施である。

## Conclusion

自己テストの範囲で、Phase 1-D.3〜1-Eの実装は契約テストを満たす。実GSIの本番取得・公開に進むには、[実装仕様](../../docs/pipeline/elevation-publish-api-v0.1.md) 第6章の承認事項（本番承認ストア、取得元の有効化、再配布条件、鉛直基準の確認、改訂提案の採否、デプロイ）をOWNERが判断する必要がある。
