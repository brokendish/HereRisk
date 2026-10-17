# Verification Summary

## Metadata

- Task ID: `phase1c1-elevation-point-lookup-core`
- Task: Phase 1-C.1 Elevation Point Lookup Core MVP（緯度・経度・zoom → XYZ画素 → 格納値の純粋関数）
- Implementer: Claude（実装・自己テスト）
- Reviewer: Claude（自己検証。Codex独立検証は今回実施しない指示）
- Target Commit: 未コミット。基準main `8be2ae6d6620bd04d2e98da7c8fe8de0ad8a3478`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS**（ChatGPTのGitHub差分レビュー待ち。この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| ファイル | 内容 |
|---|---|
| `src/hererisk/elevation/lookup/core.py`（新規、139行） | `PixelLocation`、`locate_pixel`、`lookup_elevation` |
| `tests/unit/test_elevation_lookup.py`（新規、326行、147件） | 単体テスト（独立した高精度参照実装を含む） |

既存コード・設定・保存層・認可・Orchestrator・Download・Normalize・Validateは変更していない。依存の追加なし（標準ライブラリのみ。定数は既存の `TILE_WIDTH`・`FORMAT`・`PIXELS` を再利用）。

## API仕様

```python
locate_pixel(latitude, longitude, zoom) -> PixelLocation   # z, tile_x, tile_y, pixel_x, pixel_y, index
lookup_elevation(candidate, location) -> int | None
```

### locate_pixel

標高API契約6.2の式による Web Mercator / XYZ タイル（N = 256×2^z）。

- 計算: `u = N(lon+180)/360`、`v = N(1 − asinh(tan φ)/π)/2`。`floor` で画素番号を求め、`tile = i // 256`、`pixel = i % 256`、`index = pixel_y·256 + pixel_x`。xは東向き、yは南向き、原点は北西。
- **定義域は半開区間**で、画素の半開区間（境界は東・南側の画素に属する）と揃えた。
  - 経度: `−180 ≤ lon < 180`
  - 緯度: `−LAT_MAX < lat ≤ LAT_MAX`（`LAT_MAX = degrees(atan(sinh(π))) ≈ 85.0511287798`）
  - zoom: 0〜30の整数
  - 経度180とちょうど−LAT_MAXは世界の東端・南端そのもので、どの画素にも属さないため拒否する。クランプ・ラップ・正規化（180→−180）はしない。
- **型・値の拒否**: 型がintまたはfloatと完全に一致するものだけを受け付ける（bool、str、Decimal、complex、None等は拒否）。NaN・±Infは拒否。zoomはint型のみ（14.0やTrueは拒否）。拒否時は既存の `PipelineError("INVALID_INPUT")`。
- **端での丸め補正**: 範囲内と判定済みの入力が、浮動小数点の丸めで外縁（u または v = N、あるいはわずかに負）に届いた場合だけ、最後の有効画素（または0）にする。真の値はその画素の区間内にあるため、範囲外入力のクランプではない。
- `PixelLocation` は生成時に整合性を検査する（整数型、範囲、index = pixel_y·256 + pixel_x）。

### lookup_elevation

- `values_cm[index]` を**そのまま**返す（整数cm、または欠損のNone）。0と負値は正常値として返す。補間・丸め・単位変換・欠損補完はしない。
- 必要最小限の境界検査だけを行う。全体の形式検査はValidate Coreの責務として、重複実装しない。
  - format が一致すること
  - tile の z・x・y がちょうどその3キーで、int型で、`PixelLocation` と一致すること
  - `values_cm` がlistで65536要素であること
  - 取り出した値がintまたはNoneであること
- 入力は変更しない。タイルが存在するかどうかの判定はしない（後続のデータアクセス層の責務）。

## Verification

| Check | Result |
|---|---|
| Lookup単体（147件） | PASS |
| 全pytest | **PASS: 633 passed**（既存486 + 新規147、約82秒） |
| 変異確認 | 10点すべて検出（floorをroundに、南端の受理、経度180の受理、x・yの丸め補正の削除、タイル照合、列優先での参照、型検査、index式、格納値の型検査）。作業中に古いバイトコードによる誤判定が起きたため、キャッシュを削除し `PYTHONDONTWRITEBYTECODE=1` で全件を再実行した |

テスト項目との対応:

| # | 内容 | 主なテスト |
|---|---|---|
| 1 | 既知の地点が独立期待値と一致 | 固定値（z0の中心、z1の赤道・本初子午線、東京駅z14のタイル14552/6451）。国内外10地点×zoom 9段階（0〜30）を参照実装と照合 |
| 2 | 赤道・本初子午線、タイル・画素の境界 | 経度のタイル境界（z2の−90）と画素境界、赤道、z2のタイル行境界の前後5値 |
| 3 | 四隅・タイル内の四隅 | 世界の四隅（z0・1・14・29・30）、タイル内の4隅と中央付近の画素中心 |
| 4 | 境界で隣のタイル・画素へ切り替わる | `nextafter` による前後の値 |
| 5 | 不正な緯度・経度、NaN、Infinity、bool | 20種 |
| 6 | zoomの最小・最大・範囲外 | 0・30が有効、−1・31・100・True・14.0・"14"・Noneが拒否 |
| 7 | 一致する候補で正しい画素を参照 | 固定の候補値、Normalizeの実出力を使ったend-to-end（fixture PNGの生成規則による期待値、欠損画素を含む） |
| 8 | タイル不一致を拒否 | z・x・yの各不一致、float・キー欠落 |
| 9 | 正値・負値・0・nullをそのまま返す | 型まで確認（`type is int`、`is None`） |
| 10 | 行優先の位置を取り違えない | (3,10)と(10,3)に異なる値を置いて確認 |
| 11 | 入力を変更しない | 候補とlocationを変更しないこと |
| 12 | 既存pytestがすべてPASS | 633 passed |

## 高zoomでの浮動小数点境界（実測）

独立参照は、経度を有理数で厳密に、緯度を80桁のDecimal（sin・cosはTaylor級数、`Decimal.ln`）で計算した。乱数3,000点×5段階のzoomで実測した結果:

| zoom | 最大誤差 u（画素） | 最大誤差 v（画素） | floor不一致 |
|---|---|---|---|
| 14 | 2.3×10⁻¹⁰ | 1.1×10⁻⁹ | 0 / 3000 |
| 20 | 1.5×10⁻⁸ | 6.9×10⁻⁸ | 0 / 3000 |
| 24 | 2.3×10⁻⁷ | 1.2×10⁻⁶ | 0 / 3000 |
| 28 | 3.7×10⁻⁶ | 1.6×10⁻⁵ | 0 / 3000 |
| 30 | 1.5×10⁻⁵ | 5.5×10⁻⁵ | 0 / 3000 |

- **対応できる範囲**: 真の位置が画素境界から上表の誤差以上離れていれば、正しい画素になる。z14では約10⁻⁹画素（地上で概ね0.01mm未満）であり、運用上の入力精度より十分小さい。
- **限界**: 真の位置が境界から上記の誤差未満の場合は、隣の画素になり得る。例: 緯度5×10⁻³²⁴度（非正規化数、画素換算で約10⁻³²¹）は境界上に丸められ、南側の画素になる。それでも有効な画素番号であり、範囲外のindexや不正なタイル番号は生成しない（世界の四隅とz0〜30の端点で確認）。
- 高精度の数値ライブラリは導入していない。

## Findings

1. **測地系**: 入力の測地系（WGS84）と国土地理院タイル（JGD2011）の同一視は、標高API契約6.2の暫定近似のままで、このモジュールでは扱わない。
2. **値の意味**: 格納値の取り出しであり、その地点の標高精度や安全性を保証しない（モジュールの説明に明記）。
3. **タイルの有無**: 対象タイルが存在するかの判定、Coverage・公開済みかの判定は実装していない。

## 未実装（Phase 1-C.2以降）

- 保存済みの検証済み候補を、タイルIDで選択・読み込みするデータアクセス層
- Coverage・Registryとの連携
- Web API、CLIとの接続

## Conclusion

座標から画素への変換と格納値の参照を、標準ライブラリだけの純粋関数として実装した。独立参照と境界試験で、高zoomを含めて正しいことを確認した（自己テスト633件PASS）。**最終受入ではない。**
