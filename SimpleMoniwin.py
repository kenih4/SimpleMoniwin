#!/usr/bin/env python3
"""signal_list の各信号について、指定時刻の値を MDAQ から取得して CSV に出力する。

    python daq_util.py                         # GUI
    python daq_util.py --cli 2026/10/05+0:00   # コマンドライン (GUI なし)

標準ライブラリのみで動作する (tkinter 使用)。
SIGNAME が xfel_ で始まる信号は SACLA 側、それ以外は SCSS 側のサーバに問い合わせる。
"""
from __future__ import annotations

import argparse
import csv
import json
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LIST = BASE_DIR / "sig" / "signal_list_util_LOW_forDEBUG.csv"
DEFAULT_OUTDIR = BASE_DIR / "output_util"
SETTINGS_PATH = BASE_DIR / "settings.json"

BASE_URL = {
    "SACLA": "http://srweb-dmz-03.spring8.or.jp/cgi-bin/MDAQ/mdaq_data.py",
    "SCSS": "http://xfweb-dmz-03.spring8.or.jp/cgi-bin/MDAQ/mdaq_data.py",
}
QUERY = ("sig_id={sid}&b={date}&period=60&bel=bl&format=text&_style0=line"
         "&sampling=-1&dt_fmt=0&gw=640&s=submit")
DATA_LINE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}")


# --- コア処理 (GUI 非依存) -------------------------------------------------

@dataclass
class Signal:
    unit: str
    name: str
    sid: str


@dataclass
class Result:
    signal: Signal
    value: str
    status: str  # OK / NO_DATA / HTTP_ERROR


def parse_date(text: str) -> datetime:
    """'2026/10/05+0:00' / '2026/10/05 00:00' / '2026-10-05 00:00' を datetime に。"""
    m = re.fullmatch(r"\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})[+\sT]+(\d{1,2}):(\d{2})\s*", text)
    if not m:
        raise ValueError(f"日時の形式が不正です: {text!r}  (例: 2026/10/05 00:00)")
    try:
        return datetime(*map(int, m.groups()))
    except ValueError as e:
        raise ValueError(f"日時が不正です: {text!r} ({e})") from None


def read_signal_list(path: Path) -> list[Signal]:
    signals: list[Signal] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = csv.reader(f)
        next(rows, None)  # header
        for row in rows:
            row = [c.strip() for c in row]
            if len(row) < 3 or not row[2].isdigit():
                if any(row):
                    print(f"skip: {row}")
                continue
            signals.append(Signal(row[0], row[1], row[2]))
    return signals


def parse_value(content: str) -> str | None:
    """データ行 '日時, <NONE>, 値, ...' のうち、最後の行の 3 列目を返す。"""
    value = None
    for line in content.splitlines():
        if not DATA_LINE.match(line):
            continue
        fields = line.split(",")
        if len(fields) >= 3:
            value = fields[2].strip()
    return value


def fetch_value(sig: Signal, when: datetime, retry: int = 2, timeout: float = 30) -> Result:
    site = "SACLA" if sig.name.startswith("xfel_") else "SCSS"
    date = when.strftime("%Y/%m/%d+%H:%M")
    url = f"{BASE_URL[site]}?{QUERY.format(sid=sig.sid, date=date)}"
    for attempt in range(retry + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as res:
                content = res.read().decode("utf-8", errors="replace")
            value = parse_value(content)
            return Result(sig, value or "", "OK" if value is not None else "NO_DATA")
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < retry:
                time.sleep(1)
    return Result(sig, "", "HTTP_ERROR")


def save_csv(results: list[Result], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM 付き: Excel で文字化けしない
        w = csv.writer(f)
        w.writerow(["UNIT", "SIGNAME", "SID", "VALUE", "STATUS"])
        for r in results:
            w.writerow([r.signal.unit, r.signal.name, r.signal.sid, r.value, r.status])


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(list_path: str, outdir: str, wait: str) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps({"list": list_path, "outdir": outdir, "wait": wait},
                                            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"設定を保存できませんでした: {e}")


def default_csv_path(outdir: Path, when: datetime) -> Path:
    return outdir / f"util_{when:%Y%m%d%H%M}.csv"


def save_values_txt(results: list[Result], path: Path) -> None:
    """VALUE だけを 1 行 1 値で出力する (取得できなかった信号は空行)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("\r\n".join(r.value for r in results) + "\r\n")


def open_in_notepad(path: Path) -> None:
    try:
        subprocess.Popen(["notepad.exe", str(path)])
    except OSError as e:
        print(f"notepad を起動できませんでした: {e}")


# --- CLI ------------------------------------------------------------------

def run_cli(args: argparse.Namespace) -> int:
    when = parse_date(args.date)
    signals = read_signal_list(Path(args.list))
    out = default_csv_path(Path(args.outdir), when)
    results: list[Result] = []
    for i, sig in enumerate(signals, 1):
        if i > 1 and args.wait > 0:
            time.sleep(args.wait)
        r = fetch_value(sig, when, args.retry, args.timeout)
        results.append(r)
        flag = "" if r.status == "OK" else f"  [{r.status}]"
        print(f"{i:4d}/{len(signals)}  {sig.name:<60} {r.value}{flag}")
    save_csv(results, out)
    print(f"Saved: {out}")
    txt = out.with_suffix(".txt")
    save_values_txt(results, txt)
    print(f"Saved: {txt}")
    if not args.no_open:
        open_in_notepad(txt)
    return 1 if any(r.status == "HTTP_ERROR" for r in results) else 0


# --- GUI ------------------------------------------------------------------

def run_gui(args: argparse.Namespace) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(ttk.Frame):
        def __init__(self, master: tk.Tk, args: argparse.Namespace) -> None:
            super().__init__(master, padding=10)
            self.master = master
            self.q: queue.Queue = queue.Queue()
            self.stop_event = threading.Event()
            self.worker: threading.Thread | None = None
            self.results: list[Result] = []
            self.when: datetime | None = None

            self.v_date = tk.StringVar(value=args.date or datetime.now().strftime("%Y/%m/%d %H:%M"))
            self.v_list = tk.StringVar(value=args.list)
            self.v_out = tk.StringVar(value=args.outdir)
            self.v_wait = tk.StringVar(value=str(args.wait))
            self.v_filter = tk.StringVar()
            self.v_status = tk.StringVar(value="日時を入力して「取得」を押してください")

            self._build()
            self.pack(fill="both", expand=True)
            master.after(100, self._poll)

        def _build(self) -> None:
            self.columnconfigure(1, weight=1)
            ttk.Label(self, text="日時").grid(row=0, column=0, sticky="w")
            f = ttk.Frame(self)
            f.grid(row=0, column=1, columnspan=2, sticky="w", pady=2)
            ttk.Entry(f, textvariable=self.v_date, width=20).pack(side="left")
            ttk.Label(f, text="  例: 2026/10/05 00:00").pack(side="left")
            ttk.Button(f, text="現在時刻", command=self._set_now).pack(side="left", padx=8)

            ttk.Label(self, text="信号リスト").grid(row=1, column=0, sticky="w")
            ttk.Entry(self, textvariable=self.v_list).grid(row=1, column=1, sticky="ew", pady=2)
            ttk.Button(self, text="参照...", command=self._pick_list).grid(row=1, column=2, padx=4)

            ttk.Label(self, text="出力先").grid(row=2, column=0, sticky="w")
            ttk.Entry(self, textvariable=self.v_out).grid(row=2, column=1, sticky="ew", pady=2)
            ttk.Button(self, text="参照...", command=self._pick_out).grid(row=2, column=2, padx=4)

            ttk.Label(self, text="間隔(秒)").grid(row=3, column=0, sticky="w")
            ttk.Spinbox(self, from_=0, to=10, increment=0.1, textvariable=self.v_wait,
                        width=6).grid(row=3, column=1, sticky="w", pady=2)

            bar = ttk.Frame(self)
            bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
            self.btn_start = ttk.Button(bar, text="取得", command=self._start)
            self.btn_start.pack(side="left")
            self.btn_stop = ttk.Button(bar, text="中止", command=self._stop, state="disabled")
            self.btn_stop.pack(side="left", padx=4)
            self.btn_save = ttk.Button(bar, text="CSV保存...", command=self._save, state="disabled")
            self.btn_save.pack(side="left", padx=4)
            ttk.Label(bar, text="絞り込み").pack(side="left", padx=(20, 4))
            e = ttk.Entry(bar, textvariable=self.v_filter, width=24)
            e.pack(side="left")
            self.v_filter.trace_add("write", lambda *_: self._refresh_table())

            self.progress = ttk.Progressbar(self, mode="determinate")
            self.progress.grid(row=5, column=0, columnspan=3, sticky="ew")

            cols = ("unit", "name", "sid", "value", "status")
            self.tree = ttk.Treeview(self, columns=cols, show="headings", height=18)
            for c, t, w in (("unit", "UNIT", 60), ("name", "SIGNAME", 380), ("sid", "SID", 80),
                            ("value", "VALUE", 110), ("status", "STATUS", 100)):
                self.tree.heading(c, text=t)
                self.tree.column(c, width=w, anchor="e" if c == "value" else "w")
            self.tree.tag_configure("bad", foreground="#c0392b")
            sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
            sb.grid(row=6, column=2, sticky="ns", pady=(6, 0))
            self.rowconfigure(6, weight=1)

            ttk.Label(self, textvariable=self.v_status).grid(row=7, column=0, columnspan=3,
                                                             sticky="w", pady=(6, 0))

        # -- 入力補助
        def _set_now(self) -> None:
            self.v_date.set(datetime.now().strftime("%Y/%m/%d %H:%M"))

        def _pick_list(self) -> None:
            p = filedialog.askopenfilename(title="信号リスト", filetypes=[("CSV", "*.csv"), ("All", "*.*")],
                                           initialdir=str(Path(self.v_list.get()).parent))
            if p:
                self.v_list.set(p)

        def _pick_out(self) -> None:
            p = filedialog.askdirectory(title="出力先", initialdir=self.v_out.get())
            if p:
                self.v_out.set(p)

        # -- 実行制御
        def _start(self) -> None:
            try:
                when = parse_date(self.v_date.get())
                signals = read_signal_list(Path(self.v_list.get()))
                wait = max(0.0, float(self.v_wait.get()))
            except (ValueError, OSError) as e:
                messagebox.showerror("入力エラー", str(e))
                return
            if not signals:
                messagebox.showerror("入力エラー", "信号リストが空です")
                return

            save_settings(self.v_list.get(), self.v_out.get(), self.v_wait.get())
            self.when, self.results = when, []
            self.tree.delete(*self.tree.get_children())
            self.progress.configure(maximum=len(signals), value=0)
            self.stop_event.clear()
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_save.configure(state="disabled")
            self.v_status.set(f"取得中... 0/{len(signals)}")
            self.worker = threading.Thread(target=self._work, args=(signals, when, wait), daemon=True)
            self.worker.start()

        def _stop(self) -> None:
            self.stop_event.set()
            self.btn_stop.configure(state="disabled")

        def _work(self, signals: list[Signal], when: datetime, wait: float) -> None:
            for i, sig in enumerate(signals):
                if self.stop_event.is_set():
                    break
                if i and wait > 0 and self.stop_event.wait(wait):
                    break
                self.q.put(("result", fetch_value(sig, when), len(signals)))
            self.q.put(("done", None, len(signals)))

        def _poll(self) -> None:
            try:
                while True:
                    kind, r, total = self.q.get_nowait()
                    if kind == "result":
                        self.results.append(r)
                        self.progress.configure(value=len(self.results))
                        self.v_status.set(f"取得中... {len(self.results)}/{total}")
                        if self._match(r):
                            self._insert(r)
                    else:
                        self._finish(total)
            except queue.Empty:
                pass
            self.master.after(100, self._poll)

        def _finish(self, total: int) -> None:
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.btn_save.configure(state="normal" if self.results else "disabled")
            n_ok = sum(r.status == "OK" for r in self.results)
            n_nd = sum(r.status == "NO_DATA" for r in self.results)
            n_err = sum(r.status == "HTTP_ERROR" for r in self.results)
            head = "中止" if len(self.results) < total else "完了"
            self.v_status.set(f"{head}: {len(self.results)}/{total}  OK={n_ok}  NO_DATA={n_nd}  HTTP_ERROR={n_err}")
            if self.results and self.when and len(self.results) == total:
                path = default_csv_path(Path(self.v_out.get()), self.when)
                try:
                    save_csv(self.results, path)
                    txt = path.with_suffix(".txt")
                    save_values_txt(self.results, txt)
                    self.v_status.set(self.v_status.get() + f"  → {path}")
                    open_in_notepad(txt)
                except OSError as e:
                    messagebox.showerror("保存エラー", str(e))

        # -- 表示
        def _match(self, r: Result) -> bool:
            f = self.v_filter.get().strip().lower()
            return not f or f in r.signal.name.lower() or f in r.value.lower() or f in r.status.lower()

        def _insert(self, r: Result) -> None:
            s = r.signal
            self.tree.insert("", "end", values=(s.unit, s.name, s.sid, r.value, r.status),
                             tags=() if r.status == "OK" else ("bad",))

        def _refresh_table(self) -> None:
            self.tree.delete(*self.tree.get_children())
            for r in self.results:
                if self._match(r):
                    self._insert(r)

        def _save(self) -> None:
            if not self.results or not self.when:
                return
            default = default_csv_path(Path(self.v_out.get()), self.when)
            p = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default.name,
                                             initialdir=str(default.parent),
                                             filetypes=[("CSV", "*.csv")])
            if p:
                save_csv(self.results, Path(p))
                self.v_status.set(f"保存しました: {p}")

    root = tk.Tk()
    root.title("DAQ Util - 指定時刻の信号値取得")
    root.geometry("860x640")
    app = App(root, args)

    def on_close() -> None:
        save_settings(app.v_list.get(), app.v_out.get(), app.v_wait.get())
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", "--date", metavar="DATE",
                    help="取得する日時 (YYYY/M/D+H:M)。--cli なしなら GUI の初期値になる")
    ap.add_argument("--cli", nargs="?", const=True, default=None, metavar="DATE",
                    help="GUI を使わず実行 (DATE を付けると --date と同じ)")
    ap.add_argument("-l", "--list", help="信号リスト CSV (省略時は前回の設定)")
    ap.add_argument("-o", "--outdir", help="出力先ディレクトリ (省略時は前回の設定)")
    ap.add_argument("-w", "--wait", type=float, help="リクエスト間隔(秒) (省略時は前回の設定、なければ 1.0)")
    ap.add_argument("--retry", type=int, default=2, help="取得失敗時のリトライ回数")
    ap.add_argument("--timeout", type=float, default=30, help="HTTP タイムアウト(秒)")
    ap.add_argument("--no-open", action="store_true", help="CLI 実行後に notepad で開かない")
    args = ap.parse_args()
    saved = load_settings()
    args.list = args.list or saved.get("list") or str(DEFAULT_LIST)
    args.outdir = args.outdir or saved.get("outdir") or str(DEFAULT_OUTDIR)
    if args.wait is None:
        try:
            args.wait = float(saved.get("wait", 1.0))
        except (TypeError, ValueError):
            args.wait = 1.0
    if isinstance(args.cli, str):
        args.date = args.cli
    if args.cli:
        if not args.date:
            args.date = datetime.now().strftime("%Y/%m/%d %H:%M")
        raise SystemExit(run_cli(args))
    run_gui(args)


if __name__ == "__main__":
    main()
