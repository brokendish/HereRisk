# Phase 1-B.1 Normalize Core MVP 独立検証

- Task ID: `phase1b1-elevation-normalize-core-verification`
- 日付: 2026-10-17 / 実装: Claude / 独立検証: Codex
- 対象コミット: `9a7a8eee33c5e4f006eef51af49091f0429cc142`
- **判定: PASS WITH FINDINGS。fixture用1タイル変換コアは受入可能。次工程へ進行可能。**
- OWNERの最終受入・本番操作承認とは別。今回commit/pushなし。

## 1. 範囲と実測

開始時HEADは対象コミット、作業ツリーclean。親コミットとの差分6ファイルを確認し、[設計契約](../../docs/pipeline/elevation-normalize-validate-contract-v0.1.md)、[Claude自己レビュー](phase1b1-elevation-normalize-core-mvp.md)、[変換コア](../../src/hererisk/elevation/normalize/convert.py)、[既存変換テスト](../../tests/unit/test_normalize_convert.py)を照合した。対象差分と新規PNG依存の実行経路に限定し、共通保存層の再監査は行っていない。Git fetch・外部通信・依存インストールは実施していない。

環境: Python 3.14.3 / macOS、pypng 0.20220715.0、pytest 9.1.1、既存venv。

| 実行 | 実測結果 |
|---|---|
| 既存pytest全件（無変更） | **320 passed / 45.33秒**。既存Download等261件＋Normalize59件 |
| 独立追加試験 | **25件PASS**。固定画素の全配列照合10件、付随chunk異常6件、zlib/画素異常5件、展開爆弾2件、I/O禁止1件、入力サイズ境界/不変性1件 |
| LOW指摘の診断 | **1件で再現確認**。NoneのTypeError、NaNによるサイズ比較無効化。正常動作のPASSには含めない |
| 追加試験＋診断のpytest表示 | **26 passed / 0.93秒**。診断は問題の現状を期待した試験であり、指摘解消を意味しない |

追加コードはリポジトリ外の一時領域に置き、既存テストのエンコーダー・期待値生成関数を流用しなかった。両試験群にsocket/DNS拒否を設定。実GSIデータは取得していない。

## 2. コード監査・独立確認

| 項目 | 結果 |
|---|---|
| 数値と欠損 | 1234、0、−120、null、±8388607、−1、256cmを固定期待値で照合。0/負値を欠損へ変換しない |
| 配置 | 四隅、255/256、511/512の行境界を含む65536要素全体を比較。北西原点・row-major、出力キー/寸法/tile一致 |
| 復号 | 5種filter×非interlace/Adam7の10通りを独立生成。7byte分割と空IDATを含め同じ固定値へ復号。既存テストでPLTE/gAMA/tRNS非適用も確認 |
| 異常系 | 短い/過剰な展開結果、zlib終端切断、連結した第2ストリーム、不正filterをPNG_INVALIDで拒否。gAMA/tRNS/bKGD/sBIT/pHYsの不正長も想定外例外なし |
| 展開上限 | 32 MiB相当の圧縮入力39112 bytesを両方式で拒否。Readerを禁止してもPNG_INVALIDとなり、上限検査がpypngより先に働くことを確認 |
| メモリ観測 | 上記拒否経路のtracemalloc peakは非interlace316286 bytes、Adam7 316270 bytes。入力生成後から計測。プロセス全体RSS・全入力のメモリ上限保証ではない |
| 二段階復号 | 事前の厳密zlib検査後、同じ不変bytesをpypngへ渡す。pypng内部の無制限decompressは存在するが、前段で正確な総展開サイズを確認する構造。監査した付随chunk経路には追加の圧縮展開なし |
| 独立性 | 変換関数内にファイル保存・ネットワーク・後続実行なし。builtins.open禁止下でも変換成功。Downloadからは定数/コンテナ検査を利用し、取得処理を起動しない |
| 回帰 | 既存全件PASS。Download/共通基盤のコード差分なし。候補保存、Validate、証跡、Orchestrator接続は今回の実装対象外 |

不正なPNGを入力し、妥当な整数ポリシーを与えた試験範囲では、誤標高、欠損の誤変換、部分成功、未捕捉の復号例外、危険な展開受入を確認していない。全不正PNGへの網羅保証ではない。

## 3. Finding

**B1-F01 / LOW / 後続対応可・今回の受入は非阻害**

該当: [convert.py](../../src/hererisk/elevation/normalize/convert.py) 143–153行。`max_png_bytes` は型注釈のみで、実行時の型・正値検査がない。

再現: 正常な合成PNGと `{z:1,x:1,y:0}` に対し、`normalize_tile(..., max_png_bytes=None)` はTypeErrorを送出する。`max_png_bytes=float('nan')` は比較がfalseになり変換に成功する。後者は入力bytes上限の比較が機能しない意味で、IDAT展開量の固定上限まで解除するものではない。

今回の影響: このコアは公開APIではなく、呼出元から検証済みの `max_tile_bytes` 整数を受け取る設計。PNG自身から当該引数を変更する経路はない。現行fixtureの妥当なポリシー下で危険なPNG受入を示す問題ではないため、FAILの根拠にしない。

最小対応案: 正整数（bool除外）以外を既存INVALID_INPUT等の合意した分類で拒否する小検査、または信頼された管理入口で必ず検証する前提を明文化し接続テストで固定する。**Download/Orchestratorとの後段接続前**に責務を決める。新しい設定基盤やエラー体系は不要。コードは修正していない。

## 4. 結論・限界

CRITICAL/HIGHの新規指摘、fixture MVPの受入を阻害する実証問題はない。**Phase 1-B.1の変換コアを受入可能、後続の候補検査・取得証拠接続の工程へ進行可能**とする。B1-F01の引数前提を接続時に確認すること。

本検証はPNG→内部構造のコアに限る。候補のJSON保存、Validate、実データの鉛直基準・精度、Publish、全体性能・本番運用はNOT RUN。pypngの採用・版固定に関するOWNER判断は自己レビュー記載のまま維持し、依存全体の監査へ拡張していない。

公開変更は本レビューのみ。非公開詳細は指定のworkspace報告に記録。コード・既存テスト・設定・本番データ・Registryを変更していない。文書リンク、秘密情報、Git変更範囲、非公開報告のignoreを確認。
