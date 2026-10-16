# HereRisk MVP 0 標高API詳細契約案 v0.1

- Task ID: `mvp0-elevation-api-contract-v0.1`
- 作成・公式資料確認日: 2026-10-16（日本時間）
- Status: Draft / OWNER承認待ち
- 対象: 設計・公開情報調査・文書化のみ。実装・API実測・データ取得検証は行っていない。

## 1. 適用範囲と確定度

| 区分 | 意味 |
|---|---|
| FIXED | 既存要件・今回の指示を継承する制約。標高0・負値は正常、欠損を0にしない、不明を安全にしない、公開資格を迂回しない、位置・秘密をログに残さない |
| PROVISIONAL | 本書で具体化した実装用の提案。HTTP、型、エラーコード、取得方式、設定値、テスト期待値はすべてOWNER未承認 |
| UNDECIDED | 採否・詳細が未決定。第12節の判断後に実装へ進む |

第3～10節は、特記した継承要件を除き、一体としてレビューするPROVISIONALな「ローカル公開データ方式」の契約案である。暫定であることは実装者が任意に値や意味を変更してよいことを意味しない。OWNER承認後は承認した組合せを実装・契約テストの基準にする。

今回設計する実装対象は標高APIのみ。住所、他4ハザード、Hazard Shape View、世代管理画面、管理画面の全機能は含めない。FrontendのGPS取得・標高表示は後続のClaude工程とし、CharterのMVP 0全体の範囲を縮小・拡大しない。

参照: [Charter](../project-charter.md)、[基本アーキテクチャ](../architecture/basic-architecture-v0.1.md)、[共通API](common-contract-v0.1.md)、[Registry](../architecture/dataset-registry-v0.1.md)、[Publish](../architecture/data-publish-v0.1.md)、[AI作業規約](../development/ai-development-policy.md)。

## 2. 公式資料調査と方式比較

### 2.1 確認した根拠

すべて2026-10-16確認。URLは公式資料へのリンク。資料の記載と本書の設計提案を区別する。APIを実際に呼んだ結果や、ダウンロード済みデータの検証結果ではない。

| ID | 公式資料 | 確認した内容・限界 |
|---|---|---|
| S01 | [国土地理院・サーバサイド標高取得](https://maps.gsi.go.jp/development/elevation_s.html) | 試験公開。lat/lonとouttype=JSON、応答elevation/hsrc、エラー文字列「-----」。予告なし変更・停止・過大アクセス遮断あり。数値のSLA、許容QPS、応答中の不変版・測量日・鉛直基準の識別は確認できない |
| S02 | [標高タイル詳細仕様](https://maps.gsi.go.jp/development/demtile.html) | 256×256、RGBから標高を復号。0.01m符号化単位、無効画素(128,0,0)。符号化単位は測量精度ではない |
| S03 | [標高タイル作成方法](https://maps.gsi.go.jp/development/hyokochi.html) | 地表の推定値で建物・橋の高さではない。元DEMを平滑化したタイル値は元データと一致しないことがある。DEM10Bは約10m格子・最大Z14、元データの標高精度は5m以内の標準偏差として掲載 |
| S04 | [基盤地図情報FAQ](https://www.gsi.go.jp/kiban/faq.html) | DEM10Bは日本全域整備。1m/5mは地域別。DEM1A/5Aの高さ精度はRMS 0.3m以内（計測点なし2m）、5Bは0.7m、5Cは1.4m、10Bは5m。原則T.P.だが離島例外あり。作成日と測量時期は別 |
| S05 | [地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html) | dem_png等の配信URL、データ区分と利用条件。対象レイヤーの範囲・条件を確認して取得する必要がある |
| S06 | [国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html) | 原則PDL1.0。出典、加工時の表示、第三者権利・個別法令の確認が必要 |
| S07 | [公共データ利用規約1.0](https://www.digital.go.jp/resources/open_data/public_data_license_v1.0) / [測量成果利用手続](https://www.gsi.go.jp/LAW/2930-index.html) | 複製・加工・再配布等の一般利用条件と測量成果の別途手続を確認する入口。HereRiskの具体的なローカル配布形態への申請要否は未確定 |
| S08 | [全国の標高成果改定](https://www.gsi.go.jp/sokuchikijun/hyoko2024rev.html) | 2025年の改定関連資料。取得日だけから個別タイルの改定反映済み・測地成果2024と断定しない |
| S09 | [地理院タイル仕様](https://maps.gsi.go.jp/development/siyou.html) | XYZ、メルカトル投影、北西原点、東X・南Y。国内タイルの水平系をJGD2011と説明。ブラウザ座標との同一性を無条件保証する資料ではない |
| S10 | [W3C Geolocation](https://www.w3.org/TR/geolocation/) | ブラウザ緯度・経度はWGS84。標高API入力系の提案根拠。端末のaltitudeは本APIのDEM標高として流用しない |
| S11 | [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html) | HTTPメソッド・応答コードの意味の根拠。業務statusとの対応はHereRisk側の設計提案 |

精度の数値は各資料の定義に従う集団的な品質指標であり、要求地点の誤差上限を保証しない。全国対応可能とは全座標に有効標高がある意味ではなく、水部・欠損・未整備を区別する。実際の東京検証範囲、島嶼、採用版の鉛直基準、許容誤差は未確認／OWNER判断対象。

### 2.2 候補比較（評価・推奨は設計上の判断）

| 方式 | 全国／東京検証 | 精度・根拠 | 障害・欠損 | Registry整合と運用負荷 |
|---|---|---|---|---|
| A. 国土地理院標高APIを毎要求で直接利用 | 共通の座標入力で東京から試しやすい。全国の各地点の応答保証は未確認 | S01のhsrcで元データ種別を得られるが、固定版・基準日が応答契約にない | 外部通信停止がそのまま影響。「-----」だけでは欠損と障害の原因を確定できない | 最小の接続コードで済むが、現行の検証済み公開実体契約に不適合。外部送信・負荷制御・監視が必要 |
| B. 標高PNGタイルを限定範囲で事前取得・公開（推奨） | DEM10Bを共通方式で段階拡張。東京の少数タイルから開始可能 | 同一レイヤー・Z・取得物を固定できる。元DEMより平滑化される。高精度DEMとの自動混在はしない | 実行時は外部通信不要。既知NoDataと破損を分離。更新は再取得・検証・Publish | ローカルの不変実体をRegistryへ登録できる。開発・本番に同じ版を配置し、容量・更新・バックアップ管理が必要 |
| C. 基盤地図情報DEM XML/GMLを取得・正規化・公開 | 日本全域のDEM10Bと高解像度地域別データを扱える。東京の選定・変換作業が必要 | 元データのメタデータ・測量方法を追跡しやすい。セル並び・欠損・水平／鉛直系を解釈する必要 | 実行時はローカルI/O。変換誤り、水域の特殊値等を検証する必要 | 公開契約に適合可能。取得・正規化・GIS処理の負担がBより大きい。将来の正式管理候補 |

AもBもCも出典・利用条件確認は必要。S06/S07の一般許諾だけで、対象成果のローカル保管・加工・原データ再配布について一律「申請不要」としない。BはS05の標高タイルの個別区分を確認し、API値返却とアーカイブ再配布を分けて判断する。出典表示案は「国土地理院の標高タイルをもとにHereRiskが抽出」とし、タイル一覧・利用条件へリンクする。正式文言と再配布の可否は公開資格審査で承認する。

推奨はBのDEM10B PNG・Z14を東京の限定範囲に公開する最小案。最高精度を目指す選択ではなく、単一の復号方式と固定根拠でAPI契約を実証でき、既存公開境界を守れるためである。元DEMの約10m格子とタイルの画素間隔を同一視しない。Cや高解像度タイルへの更新は別データ版・検証工程として追加できる。

Aは最小コード量の比較案であり、一般公開APIへの採用推奨ではない。URL・サービス名をRegistryに登録しただけでは、未検証の変動応答を公開済み実体にできない。`acquisition.method=api`は取得手段の候補であり、都度取得応答に公開資格を与える例外ではない。Aを選ぶなら、外部根拠の版・検証・公開資格・障害分類を定義する契約変更とOWNER承認が先に必要。本書はその例外を承認しない。事前取得結果を固定しValidate→Publishする場合はAの直接利用とは別方式になる。

## 3. リクエスト案

`POST /api/v1/elevation`、HTTPS、`Content-Type: application/json`（UTF-8、charset=utf-8も受理）。API major版v1は文書版v0.1・公開データ版と別。座標をURLへ含めないためPOST本文を提案するが、本文ログを無効化しなければプライバシーは保護されない。読み取り処理であり、データの更新はしない。

```json
{"lat":35.68,"lon":139.76}
```

| 入力 | 型・規則案 | 違反時 |
|---|---|---|
| 本文 | JSON object、lat/lonの2キーのみ、各1回、最大1024 bytes | 400（超過は413） |
| lat | JSON number、有限、-90以上90以下、WGS84十進度 | 400 invalid_request |
| lon | JSON number、有限、-180以上180以下、WGS84十進度 | 400 invalid_request |
| 数値文字列・boolean・配列・object | 数値へ変換しない。`"35.68"`、true等を拒否 | 400 |
| 欠落・null・空本文 | lat/lon両方を必須とする | 400 |
| NaN / Infinity / -Infinity、1e309等 | 非JSONトークン・変換後非有限値を拒否 | 400 |
| 重複JSONキー | 値が同じでも拒否。通常パーサーで上書きする前に検出 | 400 |
| URLクエリ | 全て禁止。lat/lonの重複・本文との併用も拒否 | 400 |
| 未知キー | dataset、provider、url、crs、timeout等も拒否 | 400 |
| 別メソッド | GET等は405、Allow: POST | 405 |
| 非JSON Content-Type・非対応Content-Encoding | 圧縮本文を含め非対応 | 415 |

指数表記の有限JSON数値は受理。パース後binary64相当で扱い、地理計算前に小数桁の丸め・clamp・経度のwrap・lat/lon交換をしない。表現上の末尾ゼロ・指数表記・負のゼロの保持は要求しない。両値が範囲内の誤順は検出できると保証しない。

地球上の妥当な座標は入力として受理する。日本国外・東京検証範囲外を緯度経度エラーにせず、正常に公開Coverageを調べて対象がなければ200/no_data。極域や±180度でも勝手に投影可能範囲へ補正しない。公開Coverage外と確認して終了し、投影式に渡さない。Registry障害を国外扱い・候補なしとして隠さない。

## 4. 応答スキーマ案

アプリが本エンドポイントの応答を生成できる場合、下記トップレベル7キーを必須とし、省略しない。Content-Typeはapplication/json、Cache-Controlはno-storeとする。プロキシ切断等でJSONが届かない場合もクライアントは通信失敗として扱う。

| フィールド | 型 | 必須・null・条件 |
|---|---|---|
| hazard | string | 常に `elevation` |
| location | object または null | 入力検証が完全に成功した場合のみobject。それ以前の拒否はnull、部分座標を返さない |
| location.lat / lon | number | object時は両方必須。受理した数値を返し、サンプル画素の中心座標へ置き換えない |
| status | string | success / no_data / retrieval_failed / indeterminate / invalid_requestのいずれか。最後は本書の追加提案 |
| result | object または null | success時のみobject、その他null |
| result.elevation_m | number | result時必須、有限、単位m。0・負値を許可、null・文字列不可 |
| dataset | object または null | success時必須object。失敗時は後述の信頼条件を満たす場合のみobject |
| error | object または null | success時null、それ以外は必須object |
| error.code / message | string | error時両方必須。第5節の固定公開文言。例外・入力値を補間しない |
| evaluated_at | string または null | 入力受理後の処理結果確定時刻をUTC `YYYY-MM-DDTHH:mm:ss.SSSZ`で返す。入力拒否時null。測量日・公開日ではない |

MVP 0のresultはelevation_mだけとする。小数点以下2桁以内の復号値を数値で返し、追加の地理補間をしない。表記上の桁数は精度保証を意味しない。クライアントは未知のstatusを正常へ変換しない。現行サーバーは定義外キーを出力しない案、将来の追加応答キーはクライアントで無視可能とする案を提案する。列挙追加・意味変更は互換性レビューが必要。

### 4.1 datasetの公開形式

| フィールド | 型・必須性 | Registryとの対応 |
|---|---|---|
| id | 非空string、必須 | datasets[].id。MVP公開集合内の重複を検証で拒否 |
| publication_version | 非空string、必須 | 実際に読んだpublication.version |
| source | object、必須 | 公開用要約だけ |
| source.provider | 非空string、必須 | source.provider |
| source.page_url | stringまたはnull、必須キー | 公開案内URL。未記録ならnull。取得URLは転写しない |
| published_at | string、必須 | publication.published_atをUTC上記形式へ表記統一。時点不明を捏造しない |
| data_reference_date | null、必須キー | MVP 0では常にnull。正式なRegistry対応先・測量時期の意味が未決定なため、取得日・作成日で代替しない |
| attribution | object、必須 | 推奨GSI方式では公開資格として必要 |
| attribution.text / license | 非空string、必須 | 検証済みattributionから許可した文言のみ抽出 |
| attribution.url | stringまたはnull、必須キー | 公開利用条件・出典URL。未記録ならnull |

dataset objectは上記をすべて信頼して構成できる場合のみ返す。I/O失敗や既知NoDataで選択済みRegistryメタデータが健全なら返せる。Registry破損・公開実体欠落・実体との版不一致・checksum不一致では根拠の結合を信頼できないためnull。失敗時に部分的なdataset objectは作らない。`source`の全文、内部ファイル名・パス、pipeline定義、認証情報、内部run_idは露出させない。

## 5. HTTP・業務状態・エラーの対応案

HTTPもstatus列挙もPROVISIONAL。200は照会処理が成立した意味であり、必ず標高が得られた意味ではない。HTTP 4xx/5xxでもJSONの業務状態とerrorを読む。HTTP自体の未到達はJSON業務状態に捏造しない。

| 状況 | HTTP | status | error.code | 公開message |
|---|---|---|---|---|
| 有効標高を取得 | 200 | success | error=null | — |
| 正常に公開集合を照会し候補なし・Coverage外 | 200 | no_data | no_coverage | この地点を評価できる公開データがありません。 |
| 選択済み健全データの既知NoData画素 | 200 | no_data | elevation_nodata | この地点の標高データはありません。 |
| Registry・実体の読み取りI/O失敗、処理期限超過 | 503 | retrieval_failed | data_unavailable | 標高データを取得できませんでした。 |
| 公開先にあるはずの実体が存在しない | 500 | indeterminate | published_data_missing | 公開データの整合性を確認できません。 |
| Registry形式・参照・版・checksum不一致 | 500 | indeterminate | dataset_integrity_error | 公開データの整合性を確認できません。 |
| PNG破損・寸法違い・非有限結果等の品質異常 | 500 | indeterminate | data_quality_error | 標高データの品質を確認できません。 |
| 複数候補の選択が未解決 | 500 | indeterminate | ambiguous_dataset | 標高データを一意に選択できません。 |
| 入力値・JSON・重複・クエリ不正 | 400 | invalid_request | invalid_input | 緯度・経度を含むリクエストが不正です。 |
| 本文サイズ超過 | 413 | invalid_request | request_too_large | リクエストが大きすぎます。 |
| メソッド不正 | 405 | invalid_request | method_not_allowed | このメソッドは利用できません。 |
| メディア型・符号化非対応 | 415 | invalid_request | unsupported_media_type | この形式のリクエストは利用できません。 |
| 未分類の内部例外 | 500 | retrieval_failed | internal_error | 標高取得処理に失敗しました。 |

根拠: S11の400は入力不正、405/413/415は該当する要求制約、503は取得基盤が利用できない状況、500はサーバー側の品質・整合性・予期しない失敗とする提案。no_dataはAPI経路やリソースの不存在ではないため404にしない。復旧時刻を知らない場合Retry-Afterを捏造せず、MVP 0では自動再試行しない。恒久的I/O権限不備もdata_unavailableになり得るため、503を「再試行で必ず復旧」と説明しない。

判定順序は、メソッド→Content-Type/Encoding→本文サイズ→クエリ・JSON構文/重複→キー/型/値→設定・Registry検証→候補選択→実体参照整合→読み取り・品質→NoDataまたは値。最初に検出した失敗で終了し、まだ確認していない後段の異常を推測しない。権限エラーとファイル不存在は区別する。入力受理前の拒否ではlocation/dataset/evaluated_atはnull。入力受理後ならlocationとevaluated_atを返す。

外部API直接利用は本表の実装範囲外。将来採用する場合、ネットワーク失敗はretrieval_failed、正常HTTPでも壊れた本文はindeterminate候補。「-----」はS01だけでは欠損の証明にならず、no_dataへ変換しない案とする。502/504の採用を含む外部アダプター専用契約は別途承認する。

## 6. 推奨ローカル方式のデータ契約と計算案

### 6.1 公開準備と実行境界

`取得 → 正規化 → Validate → Data Publish → 公開Registry → Selector → 標高読取`。公開前の成功条件・処理順は既存Publish契約を継承する。APIプロセスは作業領域や復元候補を読まず、実行時の外部取得・オンデマンド公開・自動フォールバックを行わない。

最小の公開単位候補は「1件のDEM10B/Z14 PNGタイルを1データセット」とする。source.filenameとpublication.filenameの複数ファイル問題を避け、既存Registry必須項目を満たしやすくするための限定案。全国運用の最終単位ではない。東京の限定タイル集合・有効画素をCoverageとして検証し、日本全域整備済みという表示をしない。

公開データ準備はAPIの前提作業であり、API実装者が仮Registryや未検証PNGを一般APIの実データとして配置して代替しない。管理画面全体の実装は不要だが、最低限のValidate・Publish経路と公開成果物は別途用意・承認が必要。まだ用意できない段階のモックは契約テスト専用と明記する。

`coverage.ref`はタイル範囲とNoDataを区別できる検証済み参照を持つ案。PNGの取得元、レイヤーID、Z/X/Y、取得時点、水平系、鉛直基準の確認状況、復号profileを公開準備の証跡に対応付ける。Registryへ新規必須キーを独断追加しない。既存acquisition.parameters・validation.profileでの表現、Coverage参照の形式はOWNER判断対象。

### 6.2 数値取得の具体案

DEM10B PNG（配信識別子dem_png）のZ14を使用。入力はWGS84であり、S09は国内タイルをJGD2011と説明している。MVP 0の東京検証に限り、水平数値を同じ経緯度として投影する近似を候補とするが、同一測地系であるとの主張ではない。許容水平誤差と境界試験を承認できなければ、変換方式を定義してから実装する。島嶼・全国へ無検証で適用しない。

承認したCoverage内でのみ、φ=lat×π/180、N=256×2^14とし、画素位置を次の案で得る（S09のXYZ仕様に基づく設計式）。

```text
u = N * (lon + 180) / 360
v = N * (1 - ln(tan(phi) + 1/cos(phi)) / pi) / 2
ix = floor(u); iy = floor(v)
tile_x = floor(ix / 256); tile_y = floor(iy / 256)
pixel_x = ix mod 256; pixel_y = iy mod 256
```

画素は投影座標で左・上を含み右・下を含まない半開区間。境界は東側／南側画素へ属する。座標を事前に丸めず、隣接画素から追加補間しない。投影限界・範囲外で配列参照やwrapをしない。Coverage参照も同じ境界規則で検証する。

復号はS02に従い、整数q=65536R+256G+Bとする。q<8388608ならq/100 m、q=8388608ならNoData、q>8388608なら(q−16777216)/100 m。RGBを色補正・リサイズ・補間しない。正常な0や負値を欠損扱いしない。地理院タイルの既知NoDataだけをno_dataとし、読み取れないPNGや未知の形式はindeterminate。

最小検証profile案は、256×256・24bit RGB PNG、レイヤー/Z/X/YとCoverageの一致、正常復号、NoData識別、出典・利用条件、公開メタデータ必須性、SHA-256一致。checksum必須化と方式は本API用profileの提案であり、Registry全体の契約を変更した扱いにしない。

標高は採用データの地表標高。端末の楕円体高と混同せず、未確認の鉛直変換はしない。採用タイルの鉛直基準と2025改定の反映状況は公開前に確認し、確認できない場合の採否をOWNERが決める。今回、測量日・特定の標高値・精度を実測確認したとは扱わない。

## 7. Registry接続と依存・設定

公開IDとpublication.versionの組が根拠の識別単位。データ切り替え中も一要求が読むRegistryとPNGを同じ公開世代に固定する。MVP 0は起動時に公開Registryを検証して不変の参照集合を持ち、更新は承認済み再起動で切り替える案とする。旧プロセス終了まで旧実体を保護する。これはオンライン更新・複数Registry原子性の一般方式を確定するものではない。

起動時の検証失敗はサービス利用可能としない。稼働後に読み取り失敗・破損が発生した場合のHTTPは第5節に従う。API用に任意の外部URLや内部ファイルパスをリクエストから受け取らない。元データの版不明を公開版で偽装しない。HereRisk公開版は取得物の固定版でありGSI側の測量時期ではない。

| 責務 | MVP 0の依存・最小構成案 |
|---|---|
| Backend | 入力検証、有効設定の固定、呼び出し、公開項目だけのJSON構築 |
| Location Resolver | 地域識別の契約境界を維持。少数の公開集合を直接Coverage照合する案では行政区域エンジンを先行実装しない。共通APIのResolver経由記述との差異は第11節 |
| Dataset Selector | 公開集合とCoverage・対象機能で選ぶ。都道府県一致だけで成功にしない。複数候補はambiguous_dataset |
| 標高Module | 選択済み不変実体から復号。住所や他ハザードに依存しない |
| Configuration Manager | 共通入口で設定検証・有効値解決。要求開始時の値を処理中固定 |
| Publish・管理 | APIから呼ばない。データ準備の別経路、認証・認可された操作に限定 |

設定の階層はconfの定義・デフォルト、Data Managerの永続運用値、許可済みリクエスト値。MVP 0のリクエスト上書き許可項目は空集合という案にする。管理画面・運用値の保存基盤は先行実装せず、MVP 0はconf値のみを共通入口で解決する案。運用値を追加する場合も既存の型・範囲・権限検証、履歴、デフォルト復帰要件を満たす。

| 最小設定候補 | 値・型の提案 | 管理・API変更 |
|---|---|---|
| request_body_max_bytes | integer、1024、許容256～4096 | conf定義。MVP 0で管理/API上書きなし |
| evaluation_timeout_ms | integer、3000、許容100～10000 | conf定義。要求開始時固定。期限超過は503。値の妥当性は後続負荷試験 |
| 公開Registry参照先・公開データroot | 環境ごとの検証済み内部参照 | env管理、一般API・管理画面から変更不可 |
| ログ収集先等 | 環境依存 | env管理。秘密情報をconf・Registryへ埋め込まない |

APIパス、型、status、復号方式、NoData値は契約・処理profileであり運用設定で自由に変える項目ではない。外部API URL・再試行・優先ソース等の未使用設定を先行追加しない。

## 8. JSON例（全8ケース、架空・PROVISIONAL）

座標、値、出典名、ID、版、時刻、利用条件は説明専用の架空値で、実際の地点の標高・データ公開資格を示さない。example.invalidへアクセスする必要はない。dataset objectの有無は第4節の信頼条件に従う。

### 8.1 正常・正値

HTTP 200。選択根拠の公開メタデータは健全なためobjectを返す。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "success",
  "result": {
    "elevation_m": 12.34
  },
  "dataset": {
    "id": "example-elevation-tile",
    "publication_version": "example-v1",
    "source": {
      "provider": "架空の標高提供主体",
      "page_url": "https://example.invalid/source"
    },
    "published_at": "2026-10-01T00:00:00.000Z",
    "data_reference_date": null,
    "attribution": {
      "text": "架空の出典表記",
      "license": "架空の利用条件",
      "url": "https://example.invalid/terms"
    }
  },
  "error": null,
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

### 8.2 正常・0m

HTTP 200。選択根拠の公開メタデータは健全なためobjectを返す。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "success",
  "result": {
    "elevation_m": 0
  },
  "dataset": {
    "id": "example-elevation-tile",
    "publication_version": "example-v1",
    "source": {
      "provider": "架空の標高提供主体",
      "page_url": "https://example.invalid/source"
    },
    "published_at": "2026-10-01T00:00:00.000Z",
    "data_reference_date": null,
    "attribution": {
      "text": "架空の出典表記",
      "license": "架空の利用条件",
      "url": "https://example.invalid/terms"
    }
  },
  "error": null,
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

### 8.3 正常・負値

HTTP 200。選択根拠の公開メタデータは健全なためobjectを返す。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "success",
  "result": {
    "elevation_m": -1.2
  },
  "dataset": {
    "id": "example-elevation-tile",
    "publication_version": "example-v1",
    "source": {
      "provider": "架空の標高提供主体",
      "page_url": "https://example.invalid/source"
    },
    "published_at": "2026-10-01T00:00:00.000Z",
    "data_reference_date": null,
    "attribution": {
      "text": "架空の出典表記",
      "license": "架空の利用条件",
      "url": "https://example.invalid/terms"
    }
  },
  "error": null,
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

### 8.4 データ未整備

HTTP 200。根拠未選択または結合を信頼できないためdataset=null。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "no_data",
  "result": null,
  "dataset": null,
  "error": {
    "code": "no_coverage",
    "message": "この地点を評価できる公開データがありません。"
  },
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

### 8.5 公開実体のI/O失敗

HTTP 503。選択根拠の公開メタデータは健全なためobjectを返す。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "retrieval_failed",
  "result": null,
  "dataset": {
    "id": "example-elevation-tile",
    "publication_version": "example-v1",
    "source": {
      "provider": "架空の標高提供主体",
      "page_url": "https://example.invalid/source"
    },
    "published_at": "2026-10-01T00:00:00.000Z",
    "data_reference_date": null,
    "attribution": {
      "text": "架空の出典表記",
      "license": "架空の利用条件",
      "url": "https://example.invalid/terms"
    }
  },
  "error": {
    "code": "data_unavailable",
    "message": "標高データを取得できませんでした。"
  },
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

### 8.6 PNG品質異常

HTTP 500。選択根拠の公開メタデータは健全なためobjectを返す。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "indeterminate",
  "result": null,
  "dataset": {
    "id": "example-elevation-tile",
    "publication_version": "example-v1",
    "source": {
      "provider": "架空の標高提供主体",
      "page_url": "https://example.invalid/source"
    },
    "published_at": "2026-10-01T00:00:00.000Z",
    "data_reference_date": null,
    "attribution": {
      "text": "架空の出典表記",
      "license": "架空の利用条件",
      "url": "https://example.invalid/terms"
    }
  },
  "error": {
    "code": "data_quality_error",
    "message": "標高データの品質を確認できません。"
  },
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

### 8.7 入力不正（lat=91）

HTTP 400。根拠未選択または結合を信頼できないためdataset=null。

```json
{
  "hazard": "elevation",
  "location": null,
  "status": "invalid_request",
  "result": null,
  "dataset": null,
  "error": {
    "code": "invalid_input",
    "message": "緯度・経度を含むリクエストが不正です。"
  },
  "evaluated_at": null
}
```

### 8.8 Registryと実体の版不一致

HTTP 500。根拠未選択または結合を信頼できないためdataset=null。

```json
{
  "hazard": "elevation",
  "location": {
    "lat": 35.68,
    "lon": 139.76
  },
  "status": "indeterminate",
  "result": null,
  "dataset": null,
  "error": {
    "code": "dataset_integrity_error",
    "message": "公開データの整合性を確認できません。"
  },
  "evaluated_at": "2026-10-16T00:00:00.000Z"
}
```

## 9. 契約テスト仕様案

以下は実装時に実施する期待値であり、今回実行したテストではない。第12節の承認後に採用する。実データ依存を避けたfixtureで単体・契約テストを行い、東京の実データ比較は別の統合検証とする。

共通fixture案: `D1`は8.1のdataset公開情報に一致する健全な公開版。座標35.68/139.76に対応する画素をケースごとに差し替える。Registry・時計・読取器は注入可能とし、時計は2026-10-16T00:00:00.000Zに固定。位置解決、候補選択、読取器の呼び出し回数を観測する。JSON比較はキー順・数値の末尾ゼロに依存させない。

| ID | 入力・fixture | HTTP / status / code と具体的な期待値 |
|---|---|---|
| T01 | 正常要求、RGB=(0,4,210)、D1 | 200/success、elevation_m=12.34、dataset=D1、error=null、7キー必須、時刻は固定時計 |
| T02 | RGB=(0,0,0) | 200/success、elevation_m=0、resultもdatasetもnullでない |
| T03 | RGB=(255,255,136) | 200/success、elevation_m=-1.2。負値を欠損にしない |
| T04 | 健全Registryで候補0件 | 200/no_data/no_coverage、result/dataset=null、実体読取0回 |
| T05 | 外国座標lat=0,lon=0、または日本内で公開範囲外 | T04と同じ。入力不正ではなくlocationを返す |
| T06 | RGB=(128,0,0)、D1 | 200/no_data/elevation_nodata、result=null、dataset=D1。0へ変換しない |
| T07 | D1読取がPermissionError相当 | 503/retrieval_failed/data_unavailable、dataset=D1。空データ扱いなし |
| T08 | Registry読取I/O失敗 | 503/retrieval_failed/data_unavailable、dataset=null、実体読取0回 |
| T09 | RegistryのJSON破損・必須項目欠落・公開validationがpassed以外 | 500/indeterminate/dataset_integrity_error、dataset=null、実体評価0回。起動時ならサービスを利用可能にしない |
| T10 | 公開パスに存在するはずのPNGが欠落 | 500/indeterminate/published_data_missing、dataset=null。no_dataにしない |
| T11 | Registry版と読取実体版が不一致、またはchecksum不一致 | 500/indeterminate/dataset_integrity_error、result/dataset=null |
| T12 | 破損PNG・256×256以外・非対応色形式・復号で非有限値 | 500/indeterminate/data_quality_error、健全メタデータD1ならdataset=D1 |
| T13 | `{}`、片方のみ、null、空本文、配列本文 | 400/invalid_request/invalid_input、location/result/dataset/evaluated_at=null、Resolver/Selector/読取0回 |
| T14 | latまたはlonが文字列・boolean・配列・object | T13と同じ。数値文字列を自動変換しない |
| T15 | NaN、Infinity、-Infinity、1e309 | T13と同じ。構文違反または非有限値として拒否 |
| T16 | lat=±90.000001、lon=±180.000001 | T13と同じ。clampしない |
| T17 | lat=±90、lon=±180（組合せ4件）、公開範囲なし | 200/no_data/no_coverage。範囲内として受理し、投影やwrapを行わない |
| T18 | JSONキーlat/lonの重複（同値・異値・Unicodeエスケープで同じキーも） | 400/invalid_request/invalid_input。最後の値で上書きしない |
| T19 | クエリlat/lon・重複クエリ・未知クエリ、本文は正常 | T13と同じ。URLをログ保存しない |
| T20 | 正常本文にdataset/url/timeout等を追加 | T13と同じ。任意参照先を開かない |
| T21 | lat=139.76,lon=35.68 | 400。自動交換しない。lat=35,lon=40なら有効入力のまま評価し誤順検出を保証しない |
| T22 | lat=3.568e1,lon=1.3976e2、正常画素 | T01と同じ数値。元の数値文字列表現保持は不要 |
| T23 | GET、非JSON型、圧縮本文、1025byte本文 | 順に405/method_not_allowed、415/unsupported_media_type、415/unsupported_media_type、413/request_too_large。status=invalid_request、評価関連はnull。405はAllow: POST |
| T24 | 重複公開ID・同一点の複数候補 | 重複IDはRegistry不整合、正常な複数候補は500/indeterminate/ambiguous_dataset。dataset=null。先着選択なし |
| T25 | Validate済み未公開候補・復元候補だけ存在 | 公開集合が正常に空ならT04。候補ファイル読取0回 |
| T26 | 処理中に公開版がD1→D2 | 完了応答の値とdatasetはともにD1。旧実体保護不能なら正常結果を返さない。再起動後の要求はD2で一致 |
| T27 | 処理中にtimeout設定変更 | その要求は開始時値3000msを使用。モック時間で期限未満は継続、3000ms以上で未完了なら503/data_unavailable |
| T28 | 画素・タイル境界とその両側 | 第6節のfloor・半開規則で東／南側を選択。隣接値混合なし。元座標を応答で保持 |
| T29 | 正常・全異常応答 | トップ7キーと各必須キー、null規則、第5節コード・messageを照合。パス、例外、run_id、秘密情報なし。no-storeあり |
| T30 | 正常・不正・例外時のログ／プロキシ／トレース | 座標、座標を含むURL/本文、応答本文、認証情報なし。request_idで追跡可能 |
| T31 | 固定評価時計・元データ日不明 | evaluated_atは要求処理確定時刻。data_reference_dateはnull。published_atから推定しない |
| T32 | 未分類例外 | 500/retrieval_failed/internal_error、公開固定文言。異常詳細の転写なし |
| T33 | 起動時の無効設定・非公開参照 | 利用可能にならず、外部APIや既定の架空標高へフォールバックしない |

T09/T10/T11の根拠の結合を信頼できない状態とT12の品質異常を混同しない。PNG破損とchecksum不一致が同時に判明する場合は第5節の順序に従いT11が先となる。T12は参照・checksumが一致しているがprofile違反を検出するfixtureとする。

東京の実データ統合検証（NOT RUN）では、公開対象の選定、同一PNGの独立復号との一致、Coverage境界・水域・負値の扱い、出典表示、水平系近似の影響、起動時検証、旧参照保護、journaldでの障害追跡を確認する。GSI標高APIとの一致はソース・解像度・平滑化・版が異なり得るため無条件の合否基準にしない。実データで0m・負値地点を確保できなくても、架空fixtureの成功を実地点の成功と報告しない。

## 10. セキュリティ・運用

FIXED: 不要な詳細位置・秘密・認証情報をログへ残さない。一般APIと管理APIを分離し、一般APIにRegistry変更権限を与えない。構造化ログをLinux syslog / journaldで解析可能とし、INFO / WARNING / ERRORを基本とする。本文POSTだけで保護完了とはしない。

PROVISIONAL: API側はサーバー生成のランダムなrequest_idを内部ログに用い、クライアント指定IDをそのまま信用しない。MVP 0の公開本文・ヘッダーへ追跡IDは追加しない。request_idは要求内のResolver・Selector・読取ログで共通にする。Data Pipelineのrun_idは取得・公開処理用であり、request_idへ転用・同一視しない。APIではrun_idを生成して架空のパイプライン実行を装わない。

ログ候補はtimestamp、level、module、request_id、status、公開用error_code、所要時間。正常・no_dataはINFO、入力拒否はWARNING、I/O・品質・内部障害はERROR。内部原因は許可した分類で記録し、例外全文、要求・応答全文、タイルパス・画素番号など詳細位置を再構成できる情報を出力しない。共通Loggingを使い、APIログ用の必須フィールドとpipeline用run_idの違いを詳細ログスキーマで調整する。

ローカル参照は許可したroot内の公開不変実体に限定する。public向けURLと内部参照を分離する。読み取り権限、ファイルの置換防止、期限、サイズ制限、秘密を含まない固定エラーを確認する。journald収集方式・保存期間・負荷制限・CORSの本番設定は運用レビュー対象。後続Frontendは同一originを基本候補とし、無制限CORSを暗黙追加しない。

## 11. 既存契約との照合・差異

| 文書 | 維持する内容 | 具体化・差異と扱い |
|---|---|---|
| Charter | 全国設計／東京検証、標高MVP、0・負値・不明の扱い、不要機能を実装しない | MVP全体のFrontend・単体/契約テスト完了条件は後続工程に維持 |
| 基本アーキテクチャ | 責務分離、設定3階層、conf/env、公開・世代・復元の分離 | MVPは運用設定UIなし・API上書きなしの具体案。全機能の前倒しではない |
| 共通API | status/resultの分離、根拠情報制限、公開済みデータ限定 | POST、v1、必須/null、invalid_request、HTTP、時刻を具体提案。既存暫定列挙を確定扱いしない |
| 共通APIのResolver経由記述 | 地域識別とデータ選択の責務を分離 | Coverage直接照合で地域エンジンを省略するMVP案は、C01のResolver経由という記述との調整事項。Charterの不要実装を強制しない方針との整合をOWNERが確認する |
| Registry | 公開資格、由来、validation=passed、必須publication、履歴非格納 | 単一PNG公開単位・checksum必須profile・Coverage形式は追加提案。元データ日対応は未決定なのでnull |
| Publish | 唯一の公開確定担当、参照整合、原子的切り替え、旧データ保護 | 最小公開準備も省略不可。APIの起動時固定案はPublish方式の確定ではない |
| AI作業規約 | 指定文書のみ、自己確認と独立検証を区別、workspace非公開 | commit・push未実施。実装・実行テスト成功を宣言しない |

外部API直接利用Aは、現行の「公開済みRegistryと検証済み実体のみ参照」にそのまま適合しないという設計差異を発見した。採用する場合はOWNER判断と既存契約の変更工程が必要であり、本書ではBを推奨して公開資格を維持する。上表以外に継承要件を上書きする変更は意図していない。参照元6文書は修正していない。

## 12. 実装前のOWNER判断事項

| ID | 判断対象 | 推奨・必要な合意 | 未承認時の扱い |
|---|---|---|---|
| O01 | データ取得方式 | B: DEM10B PNG/Z14の限定公開。Aの直接利用は契約改定を要する比較案 | 一般APIの実データ取得を実装しない |
| O02 | API wire契約 | POST /api/v1/elevation、厳密JSON number、7キー、null、invalid_request追加、第5節HTTP | Claude実装・契約テストの基準を確定しない |
| O03 | データ準備 | 東京の対象タイル、ID、Coverage・境界、1PNG単位、checksum/profile、Validate・Publishの最小経路 | 未公開fixtureを本番根拠にしない |
| O04 | 精度と基準 | WGS84入力とJGD2011タイルの近似許容、鉛直基準・2025改定、地点誤差・水部の利用可否 | 同じ測地系・一定精度・更新済みと断言しない |
| O05 | 利用条件 | 採用成果の保管・加工・値提供・再配布と申請要否、出典文言 | 利用条件未確認のままPublishしない |
| O06 | 共通処理の最小構成 | 行政区域Resolver実装を省きCoverage照合する案と共通C01の調整 | 既存文書を勝手に読み替えない |
| O07 | 参照・更新 | 起動時固定、再起動切替、旧実体保護、同時公開との接続 | 更新途中の実体を読まない |
| O08 | 設定・運用 | 1024byte/3000ms、運用値UIなし、API上書きなし、起動時検証、ログ・CORS・負荷制限 | 秘密・環境参照の任意変更不可を維持 |
| O09 | 根拠応答 | datasetの必須情報、元データ日null、失敗時の信頼条件 | 不明な情報を捏造しない |

O01～O09はUNDECIDED（提案の採否待ち）。採用案の承認とデータ準備を終えれば、第3～10節を実装・テストに使える。全国拡張時の複数ソース優先順位、正式な公開単位、元データ日、外部APIアダプター、無停止更新等は後続判断とし、MVP 0で先行実装しない。
