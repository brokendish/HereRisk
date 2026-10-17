# Verification Summary

## Metadata

- Task ID: `phase1d2-gsi-poc-point-lookup`
- Task: Phase 1-D.2 実GSI PoCの地点標高読取（Phase 1-D.1で取得したPNGと証跡からの読取専用ルックアップ）
- Implementer: Claude（実装・テスト・commit・push）
- Reviewer: Claude（自己検証。Codexは使用しない指示）
- Target Commit: 本レビューと同じコミット（基準main `11318549ad07bc71874d3e0c9feda1669e82b641`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した）
- Status: **自己テストPASS**（通信なし。この自己テストは最終受入ではない）
- OWNER Approval: Git運用ルールに基づきcommit・push

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/gsi_poc/reader.py`（新規） | `read_poc_elevation`、`PocElevation`。ネットワークのコードをimportしない |
| `src/hererisk/elevation/gsi_poc/constants.py`（新規） | 取得側と読取側で共有する定数（ホスト、上限、マーカー、証跡スキーマ名、ファイル名・URLの規則）。ネットワークのコードを含まない |
| `src/hererisk/elevation/gsi_poc/http_fetch.py`、`poc.py` | 定数を `constants.py` から読むようにした（名前は従来どおり公開。挙動の変更なし） |
| `src/hererisk/cli.py` | `gsi-elevation-poc` サブコマンドを追加 |
| `tests/contract/test_gsi_poc_reader.py`（新規、39件） | Phase 1-D.1のコードで作ったPoC成果物を読む契約テスト（通信なし） |
| `docs/development/phase1a1-download-fixture-usage.md` | 第3.4節を追加 |

Lookup・Normalize・Validateのコア、保存層、Orchestrator、fixtureパイプライン、本番Source Definitionは変更していない。PoCのファイルは、fixtureパイプラインへコピー・登録・投入しない。

## 仕様

```bash
hererisk-pipeline gsi-elevation-poc --lat <lat> --lon <lon> --zoom <z> --poc-dir <GSI_POC_DIR>
```

1. `locate_pixel` でタイルと画素を求める。zoomは呼出側が指定する（取得していないzoomのタイルは「未取得」になる）。
2. **PoCディレクトリ**
   - 指定パスそのものがsymlinkでなく、実在するディレクトリであること。
   - `/` からsymlinkを辿らずに固定する。
   - マーカーが通常ファイルで、リンク数1、本人所有で、内容が完全に一致すること。
   - fixtureのデータrootのマーカーがあれば拒否する。
3. **証跡** `dem_png_<z>_<x>_<y>.json`
   - 通常ファイル・リンク数1・本人所有で、64 KiB以下であることを確かめてから読む（上限超過のファイルは読まない）。
   - 厳密なJSON解析（重複キー・NaNを拒否）と、読取用Schemaで検査する。必須の値は次のとおり。
     - `schema` が一致、`poc_only=true`
     - DEM10B・dem_png
     - HTTP 200・`image/png`
     - checksがすべてpassed
     - `source_ref=gsi-dem10b-candidate`
     - SHA-256・size・統計・出典・未確認事項がそろっていること
   - タイル・PNGのファイル名・URLが、求めたタイルの値と完全一致すること（パストラバーサルは不可）。
4. **PNG**: 証跡と同じファイル条件で、1 MiBを上限に読む。size・SHA-256が証跡と一致すること。
5. `normalize_tile`（コンテナ検査と厳密な復号）、`validate_candidate`（expected_tile付き）で検査する。統計（valid・nodata・min・max・warning）が証跡と一致すること。
6. `lookup_elevation` で値を取り出す。`elevation_m = elevation_cm / 100`。

### 出力（JSON1行、キーは固定）

`status`、`error_code`、`reason`、`message`、`tile`、`pixel`、`elevation_cm`、`elevation_m`、`nodata`、`poc_only`（常にtrue）、`source`（国土地理院・DEM10B・dem_png・出典・PNGのSHA-256・取得時刻・`approved_for_publication: false`・未確認事項）。

- 欠損画素は成功として、`elevation_cm` と `elevation_m` をnull、`nodata=true` で返す。0と負値は正常な値。
- 入力した緯度経度・内部パス・例外文は、stdoutにもログにも出さない。

| 状態 | reason | error_code（終了コード） |
|---|---|---|
| 座標の不正 | INVALID_COORDINATES | INVALID_INPUT（2） |
| PoCディレクトリでない（マーカーなし・不正、symlink、fixture root、存在しない） | NOT_POC_DIR | INVALID_INPUT（2） |
| そのタイルを取得していない | TILE_NOT_FETCHED | TARGET_UNCONFIGURED（3） |
| 証跡の破損・改ざん・別タイル・hardlink・上限超過 | EVIDENCE_INVALID | RECOVERY_REQUIRED（3） |
| PNGの欠落・size/SHA-256不一致・hardlink・symlink | PNG_MISMATCH | STORAGE_INTEGRITY_FAILED（12） |
| 復号・プロファイル検査の失敗 | PNG_UNDECODABLE | PNG_INVALID（11） |
| 統計が証跡と一致しない | STATISTICS_MISMATCH | RECOVERY_REQUIRED（3） |

## Verification

| Check | Result |
|---|---|
| PoC読取の契約テスト（39件、通信なし） | PASS |
| 全pytest | **PASS: 797 passed**（既存758 + 新規39、約116秒） |
| 変異確認 | 10点すべて検出（リンク数・所有者、マーカーの内容、fixture rootの拒否、SHA-256・size、統計、証跡のタイル、証跡のURL、サイズの事前検査、メートル換算）。サイズの事前検査は、最初は受信量の上限による拒否と結果が同じで検出できなかった。そこで「上限超過のファイルを読まない」ことを、実際に読んだバイト数で確かめる試験を追加した |

試験項目との対応:

| 内容 | 主なテスト |
|---|---|
| D.1の成果物から標高を取得 | `run_fetch_poc` で作った成果物を読む。期待値はfixture PNGの生成規則による。隣接する2枚目のタイルも読める |
| 正値・0・負値・NoData | 画素に置いた値で確認（メートル換算を含む） |
| 対象外のタイル | 取得していないタイル、取得していないzoom |
| 証跡なし・破損・改変 | 改変10種（poc_only、スキーマ、check、status、Content-Type、タイル、URL、パストラバーサル、source、sha欠落）、破損4種（不正JSON、重複キー、配列、NaN）、上限超過 |
| PNGのsize・SHA-256不一致 | 別のPNG、末尾の余剰 |
| PNGの復号エラー | hashを整合させた復号不能のPNG。統計の不一致も検出 |
| 不正な入力・マーカーなし・symlink | 座標4種、通常のディレクトリ、存在しない、ディレクトリ自体がsymlink、マーカーの内容違い・hardlink、fixture root。親ディレクトリ経由のsymlinkは、実体に解決したうえで許可する |
| ファイル更新なし | 読取の前後でファイルのhashが不変（別プロセスのCLI実行を含む） |
| 分離 | 読取モジュールを読み込んでも `http.client`・`socket`・`ssl`・`http_fetch` が読み込まれない |

## Findings

1. **値の位置づけ**: PoCの実GSIデータであり、公開承認されたデータではない。鉛直基準・測量時期・改定の反映状況は、証跡の記録どおり未確認として返す（推測しない）。
2. **信頼の起点**: 信頼の起点は証跡JSONで、これ自体は署名されていない。PoCディレクトリに書き込める主体は、整合する一式を偽造できる（既存の信頼境界と同じ）。
3. **定数の移動**: `http_fetch`・`poc` の公開名は維持した。

## 次工程への引渡し

- 本番の取得・承認・Source Definitionの確定と、Download → Normalize → Validate → Publish への正式な接続は、別の工程で行う。
- 公開API（Phase 1-E）は、このPoCの読取を根拠にしない。

## Conclusion

Phase 1-D.1のPoC成果物から、通信なし・読取専用で地点標高を取得できる。証跡・PNG・復号・統計のどれかに不整合があれば成功させない（自己テスト797件PASS）。**最終受入ではない。**
