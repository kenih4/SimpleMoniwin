# SimpleMoniwin

信号リスト（CSV）に記載された各信号について、**指定した日時の値**を MDAQ（`mdaq_data.py`）から取得し、CSV に出力するツールです。
GUI（tkinter）とコマンドライン（CLI）の両方で使えます。

## 特長

- Python 標準ライブラリのみで動作（追加インストール不要）
- GUI：日時入力、進捗表示、結果の絞り込み、中止、CSV 保存
- CLI：GUI なしでバッチ実行可能
- 信号名が `xfel_` で始まるものは **SACLA** 側、それ以外は **SCSS** 側のサーバへ自動で振り分け
- 取得失敗時の自動リトライ、リクエスト間隔の調整に対応
- 出力 CSV は BOM 付き UTF-8（Excel でそのまま開いても文字化けしません）

## 動作環境

- Python 3.9 以上（tkinter 同梱のもの）
- MDAQ サーバへネットワーク接続できること

## 使い方

### GUI

```bash
python SimpleMoniwin.py
```

1. 「日時」を入力（例: `2026/10/05 00:00`。「現在時刻」ボタンも利用可）
2. 必要に応じて信号リスト・出力先・リクエスト間隔を変更
3. 「取得」を押す
4. 全件取得が完了すると、出力先に自動で CSV が保存されます。「CSV保存...」で別の場所へ保存することも可能です。「中止」で途中停止できます（中止時は自動保存されません）。

### CLI

```bash
python SimpleMoniwin.py --cli -d 2026/10/05+0:00 -l sig/signal_list_util_forPerl.csv -o output_util -w 0.5
python SimpleMoniwin.py --cli 2026/10/05+0:00      # 日時だけ指定する短縮形
```

`--cli` を付けずに引数だけ指定すると、GUI の初期値として反映されます（ショートカットに引数を足す使い方向け）。

| オプション | 既定値 | 説明 |
| --- | --- | --- |
| `--cli [DATE]` | – | GUI を使わず実行。DATE を付けると `--date` と同じ |
| `-d`, `--date DATE` | 現在時刻 | 取得する日時（`YYYY/M/D+H:M`） |
| `-l`, `--list PATH` | 前回の設定（なければ既定の信号リスト） | 信号リスト CSV |
| `-o`, `--outdir DIR` | 前回の設定（なければ `output_util/`） | 出力先ディレクトリ |
| `-w`, `--wait SEC` | 前回の設定（なければ `1.0`） | リクエスト間隔（秒） |
| `--retry N` | `2` | 取得失敗時のリトライ回数 |
| `--timeout SEC` | `30` | HTTP タイムアウト（秒） |
| `--no-open` | – | 実行後に notepad で値のテキストを開かない |

日時は `2026/10/05+0:00` / `2026/10/05 00:00` / `2026-10-05 00:00` の形式で指定できます。
HTTP エラーが 1 件でもあった場合、終了コードは `1` になります。

### ショートカット

プロジェクト直下の `SimpleMoniwin.lnk` をダブルクリックすると GUI が起動します（コンソールなし）。デスクトップ等へコピーして使えます。引数を固定したい場合は、ショートカットのプロパティの「リンク先」末尾に `-l ... -o ...` などを追記してください。
`.lnk` は絶対パスを含むため Git 管理外です。

### 設定の保存

GUI で変更した信号リスト・出力先・リクエスト間隔は、「取得」を押したときとウィンドウを閉じたときに `settings.json` へ保存され、次回起動時に読み込まれます。コマンドライン引数で指定した値は設定より優先されます（引数指定だけでは保存されません）。`settings.json` は Git 管理外です。

## 入出力ファイル

### 信号リスト（入力）

ヘッダ行付きの CSV で、列は `UNIT,SIGNAME,SID` です。`SID` が数字でない行はスキップされます。

```csv
UNIT,SIGNAME,SID
UNIT,xfel_util_tcs_238_cav_flowmeter/flow,530423
```

### 出力

`<出力先>/util_YYYYMMDDHHMM.csv` として保存されます。

```csv
UNIT,SIGNAME,SID,VALUE,STATUS
UNIT,xfel_util_tcs_238_cav_flowmeter/flow,530423,28.10000,OK
```

全件の取得が終わると、同じ場所に `util_YYYYMMDDHHMM.txt`（VALUE のみ・1 行 1 値・信号リストと同じ順序、取得できなかった信号は空行）も保存し、notepad で自動的に開きます。

`STATUS` の意味：

| STATUS | 内容 |
| --- | --- |
| `OK` | 値を取得できた |
| `NO_DATA` | サーバから応答はあったが、該当時刻のデータがなかった |
| `HTTP_ERROR` | 通信エラー（リトライ後も失敗） |

## ディレクトリ構成

```
SimpleMoniwin/
├── SimpleMoniwin.py   # 本体
├── SimpleMoniwin.lnk  # GUI 起動ショートカット（Git 管理外）
├── sig/               # 信号リスト CSV（Git 管理外）
└── output_util/       # 出力 CSV（Git 管理外）
```

## 仕組み

各信号につき、時刻 `b` を指定した MDAQ のテキスト出力（`format=text`）を取得し、データ行（`日時, <NONE>, 値, ...`）の最終行の 3 列目を値として採用します。
