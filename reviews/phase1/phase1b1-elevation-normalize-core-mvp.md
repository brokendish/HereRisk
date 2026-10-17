# Verification Summary

## Metadata

- Task ID: `phase1b1-elevation-normalize-core-mvp`
- Task: Phase 1-B.1 Normalize Core MVP（PNG 1枚 → 整数cm/null配列の純粋変換）
- Implementer: Claude（実装・単体テスト）
- Reviewer: Claude（自己検証。独立検証ではない）
- Target Commit: 未コミット。基準main `ed83638d4656e4815e1d5d6df51b8b4ee020718d`。作業開始時にfetchし、HEADとorigin/mainの一致と作業ツリーがcleanであることを確認した
- Status: **自己テストPASS・独立検証待ち**（この自己テストは最終受入ではない）
- OWNER Approval: 未承認（commit・push未実施）

## Changes

| 区分 | 内容 |
|---|---|
| 新規 | `src/hererisk/elevation/normalize/convert.py`（約170行）: `normalize_tile(png_bytes, tile, *, max_png_bytes)`、`rgb_to_cm`、`decode_rgb_rows` |
| 新規 | `tests/unit/test_normalize_convert.py`（59件）。試験専用のPNGエンコーダー（全5フィルター、Adam7、IDAT分割）を含み、デコーダーとは独立 |
| 依存 | `pyproject.toml` に `pypng==0.20220715.0` を追加 |
| 文書 | `docs/development/phase1a1-download-fixture-usage.md` の依存表に1行追加 |

変更していないもの: Download、Orchestrator、Configuration Manager、保存層、Acquisition Record、認可、CLI、設定、Source Definition。ファイル保存・Validate・Publish・Registry・通信は実装していない。

### 処理

1. **入力確認**: 入力は不変の `bytes` に限る（`bytearray`・`memoryview` 等はINVALID_INPUT）。タイルは呼出元が渡す `{z,x,y}` で、PNGからは取得しない。z/x/yは整数（bool不可）、0≤z≤30、0≤x,y<2^z。`max_png_bytes` を超える入力はSIZE_INVALID。
2. **コンテナ検査**: Downloadの `check_png` をそのまま再利用する（IHDR=256×256・8bit・RGB、CRC、chunk順序、PLTE規則、IEND、末尾の余剰）。
3. **展開検査**: IDATを連結し、上限付きで厳密に展開する。展開結果がIHDRから決まる正確なサイズ（非interlace 196,864 bytes、Adam7 197,088 bytes）と一致すること、zlibストリームが正しく終端し、後続データがないことを要求する。展開は上限+1 byteで打ち切るため、展開爆弾でメモリを消費しない。
4. **画素復号**: フィルター解除とAdam7の展開はpypngに任せる。得られた生の8bit RGBサンプルが256行×768 bytesであることを再確認する。
5. **符号化変換**: `q = 65536R + 256G + B` について、q<2^23はq（cm）、q=2^23はnull、q>2^23はq−2^24（cm）とする。北西原点・row-major（`index = y*256 + x`）。
6. **出力**: `{"format": "hererisk-elevation-cm-json-v0.1", "tile", "width": 256, "height": 256, "values_cm": [65536要素]}`。
7. **失敗時**: 復号失敗はすべてPNG_INVALIDとする。欠損（null）や0に置き換えず、部分的な出力も返さない。

### PNGライブラリの選定

採用はpypng 0.20220715.0（純Python、単一モジュール、依存なし。最終リリースは2022-07）。PillowはC拡張を含む大規模な依存になるため見送った。

| 確認項目 | 結果 |
|---|---|
| 8bit RGBの元サンプル | `Reader.read()` が生サンプルを返す（planes=3、bitdepth=8） |
| 色補正 | gAMA・PLTE・tRNSを適用しない（試験で確認） |
| Adam7 | 対応（試験で確認） |
| 展開サイズ上限 | **pypng単体では不十分**。上限がなく、過剰な展開データ（257行目）と、zlibストリーム後の余剰データを受け入れる。このため前段の厳密展開検査で補い、未対応部分を黙って通さないようにした |

## Verification

| Check | Result |
|---|---|
| Normalize単体（59件） | PASS |
| 全pytest | **PASS: 320 passed**（既存261 + 新規59） |
| 変異確認 | PASS: 8変異をすべて検出（厳密展開の削除、欠損→0、負値の折返しなし、境界±1、BGR順、行の反転、コンテナ検査の削除、復号失敗→欠損） |
| Download既存動作 | 不変（関連ファイルの変更なし。既存261件PASS） |
| 外部通信・I/O | なし。変換モジュールのimportを静的に検査し、I/O・保存層・Orchestratorへの依存がないことを確認 |

試験の内訳:

| 区分 | 内容 |
|---|---|
| 符号化 | 契約4.2の6例と、境界・桁位置の6例（1、−1、8388606、−2、256、65536）。いずれも固定値 |
| 混合タイル | 欠損数、0・負値を正常値として扱うこと |
| 画素順序 | 四隅（index 0、255、65280、65535）、行境界（255/256、511/512）、隣接画素 |
| 同値性 | Sub・Up・Average・Paeth・行ごとの混在、IDAT分割（1000・13 bytes）、Adam7（フィルター混在・分割を含む）、PLTE・gAMA・tRNS・tEXtの付加。いずれも同一の値になる |
| 寸法・形式の拒否 | 255幅、512高、16bit、RGBA、インデックス、グレー、巨大IHDR |
| 画像データ不正 | 255行・257行、1 byte不足・過剰、不正フィルター、空データ、Adam7のサイズ不一致 |
| zlib不正 | 末尾の余剰、ストリーム後のIDAT、切断、不正deflate、途中のbit破損 |
| 展開爆弾 | 64 MiB相当。展開量が196,865 bytes以下で停止することを計測 |
| その他 | コンテナ破損、サイズ上限、入力型、タイル不正10種、原本bytes不変、失敗時に部分出力しないこと |

## 未対応の入力形式（明示的に拒否）

- 256×256以外、8bit以外、RGB以外（RGBA・グレー・インデックス）。自動変換しない。
- IHDRのcompression/filterが0以外、interlaceが0・1以外。
- 展開サイズが正確に一致しないもの、zlibストリーム後のデータ。

PLTE・tRNS・gAMA等の付加chunkを持つRGB PNGは受け付けるが、画素値には適用しない（契約4.2どおり）。

## Findings

1. **依存の保守性**: pypngは2022年以降リリースがない。版を厳密に固定し、展開の上限と厳密さは自前の前段検査で担保する。将来の更新・置換は要判断。
2. **上限値の扱い**: `max_png_bytes` は呼出元が渡す（ポリシーの `max_tile_bytes` 相当）。変換モジュールにポリシー値を重複して埋め込まない。
3. **依存の向き**: 定数と `check_png` を `elevation.download` から参照する（同一API内の依存）。`download.download` のimportは定数のためで、Downloadの処理は呼ばない。
4. **候補形式の範囲**: 候補JSONの保存・直列化（compact、1 MiB上限）と、候補形式の検査（Validate側）は今回の範囲外。

## Limitations

- 計測したのはzlibの展開量の上限だけで、メモリ総量（pypngの内部バッファ）は計測していない。
- 実GSIのPNGでは未試験（取得禁止）。Downloadとの接続、証跡、Orchestratorへの組込みは後続作業。

## Conclusion

PNG 1枚から正しい整数cm/null配列が得られることを、デコーダーから独立した期待値で確認した（自己テスト320件PASS）。**最終受入ではない。**

OWNER確認事項:

1. pypngの採用と版固定
2. Findings 1〜4
