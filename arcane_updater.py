#!/usr/bin/env python3
"""Windows desktop front end for the Arcane return report generator."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import BooleanVar, END, BOTH, LEFT, RIGHT, X, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import build_arcane_workbook
import warframe_arcane_prices as prices


APP_NAME = "Warframe 赋能收益表更新器"
PROGRESS_PATTERN = re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]")


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def local_data_directory() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "WarframeArcaneReturnCalculator"


def default_output_directory() -> Path:
    configured = os.environ.get("ARCANE_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return application_directory() / "outputs" / "daily_arcane_return"


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class QueueWriter:
    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        self.events = events
        self.pending = ""

    def write(self, text: str) -> int:
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.strip():
                self.events.put(("log", line))
        return len(text)

    def flush(self) -> None:
        if self.pending.strip():
            self.events.put(("log", self.pending))
        self.pending = ""


class ArcaneUpdaterApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.output_directory = default_output_directory()
        self.auto_open = BooleanVar(value=True)

        root.title(APP_NAME)
        root.geometry("820x600")
        root.minsize(720, 500)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        self._build_ui()
        root.after(100, self._process_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(outer, text=APP_NAME, font=("Microsoft YaHei UI", 21, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Warframe Market PC · Cross Play · 满级赋能近48小时成交量加权平均价",
            foreground="#486b74",
        ).pack(anchor="w", pady=(2, 16))

        destination = ttk.LabelFrame(outer, text="输出位置", padding=10)
        destination.pack(fill=X)
        self.output_label = ttk.Label(destination, text=str(self.output_directory))
        self.output_label.pack(side=LEFT, fill=X, expand=True)
        self.choose_button = ttk.Button(destination, text="更改…", command=self._choose_output)
        self.choose_button.pack(side=RIGHT, padx=(8, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill=X, pady=14)
        self.update_button = ttk.Button(actions, text="更新并生成表格", command=self._start_update)
        self.update_button.pack(side=LEFT)
        self.folder_button = ttk.Button(actions, text="打开输出文件夹", command=self._open_output_folder)
        self.folder_button.pack(side=LEFT, padx=(8, 0))
        ttk.Checkbutton(actions, text="完成后打开Excel", variable=self.auto_open).pack(side=RIGHT)

        self.status_label = ttk.Label(outer, text="准备就绪。点击按钮后才会开始联网更新。")
        self.status_label.pack(fill=X)
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.pack(fill=X, pady=(6, 14))

        log_frame = ttk.LabelFrame(outer, text="运行日志", padding=8)
        log_frame.pack(fill=BOTH, expand=True)
        self.log = ScrolledText(
            log_frame,
            height=18,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            background="#f7f9fa",
        )
        self.log.pack(fill=BOTH, expand=True)

        ttk.Label(
            outer,
            text="价格和成交量来自 Warframe Market；生成工作簿不要求安装 Microsoft Excel。",
            foreground="#64757b",
        ).pack(anchor="w", pady=(10, 0))

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.output_directory))
        if selected:
            self.output_directory = Path(selected)
            self.output_label.configure(text=str(self.output_directory))

    def _open_output_folder(self) -> None:
        try:
            self.output_directory.mkdir(parents=True, exist_ok=True)
            open_path(self.output_directory)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"无法打开输出目录：\n{exc}")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(END, line + "\n")
        self.log.see(END)
        self.log.configure(state="disabled")

        match = PROGRESS_PATTERN.search(line)
        if match:
            current, total = map(int, match.groups())
            self.progress.configure(value=100 * current / max(total, 1))
            self.status_label.configure(text=f"正在抓取赋能价格：{current}/{total}")

    def _start_update(self) -> None:
        if self.running:
            return
        self.running = True
        self.update_button.configure(state="disabled")
        self.choose_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.status_label.configure(text="正在准备数据更新…")
        self._append_log("=" * 66)
        self._append_log("开始更新。完整抓取通常需要数分钟，请不要关闭程序。")
        threading.Thread(target=self._run_update, daemon=True).start()

    def _run_update(self) -> None:
        writer = QueueWriter(self.events)
        previous_stdout, previous_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = writer
        try:
            data_dir = local_data_directory()
            cache_dir = data_dir / "cache"
            work_dir = data_dir / "work"
            cache_dir.mkdir(parents=True, exist_ok=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            self.output_directory.mkdir(parents=True, exist_ok=True)
            os.environ["ARCANE_CACHE_DIR"] = str(cache_dir)

            output_file = self.output_directory / "赋能收益表_最新.xlsx"
            if output_file.exists():
                try:
                    with output_file.open("ab"):
                        pass
                except PermissionError as exc:
                    raise PermissionError("输出表格正在被Excel占用，请关闭表格后重试。") from exc

            client = prices.WarframeMarketClient(platform="pc", crossplay=True, timeout=20.0)
            items = prices.load_items(client, refresh=False)
            arcanes = prices.find_arcanes(items)
            if not arcanes:
                raise prices.ApiError("物品清单中没有找到可升级赋能")

            print(f"共找到 {len(arcanes)} 种赋能，开始读取市场数据…", file=sys.stderr)
            dissolution_by_game_ref, dissolution_by_name = prices.load_dissolution_vosfor_values(client)
            rows = prices.fetch_prices(
                client,
                arcanes,
                prices.ITEM_LANGUAGE,
                dissolution_by_game_ref,
                dissolution_by_name,
            )
            item_results, summaries = prices.calculate_pack_returns(
                rows, prices.DEFAULT_MIN_DAILY_VOLUME
            )

            price_csv = work_dir / "arcane_prices.csv"
            summary_csv = work_dir / "pack_summary.csv"
            data_json = work_dir / "arcane_data.json"
            prices.write_csv(rows, item_results, summaries, price_csv)
            prices.write_pack_summary_csv(summaries, summary_csv)
            prices.write_json(rows, item_results, summaries, data_json)

            print("正在生成并检查Excel工作簿…", file=sys.stderr)
            data = json.loads(data_json.read_text(encoding="utf-8"))
            build_arcane_workbook.build_workbook(data, output_file)
            print(f"完成：{output_file}")
            writer.flush()
            self.events.put(("success", output_file))
        except Exception as exc:  # The GUI must report unexpected packaging/runtime errors.
            writer.flush()
            log_path = local_data_directory() / "last_error.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            details = traceback.format_exc()
            log_path.write_text(details, encoding="utf-8")
            self.events.put(("error", (str(exc), log_path)))
        finally:
            sys.stdout, sys.stderr = previous_stdout, previous_stderr

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "success":
                    self.running = False
                    self.update_button.configure(state="normal")
                    self.choose_button.configure(state="normal")
                    self.progress.configure(value=100)
                    self.status_label.configure(text="更新完成。")
                    output_file = Path(payload)
                    messagebox.showinfo(APP_NAME, f"最新表格已生成：\n{output_file}")
                    if self.auto_open.get():
                        try:
                            open_path(output_file)
                        except OSError as exc:
                            messagebox.showwarning(APP_NAME, f"表格已生成，但无法自动打开：\n{exc}")
                elif event == "error":
                    self.running = False
                    self.update_button.configure(state="normal")
                    self.choose_button.configure(state="normal")
                    self.status_label.configure(text="更新失败，请查看错误信息。")
                    error, log_path = payload  # type: ignore[misc]
                    self._append_log(f"错误：{error}")
                    self._append_log(f"详细日志：{log_path}")
                    messagebox.showerror(APP_NAME, f"更新失败：\n{error}\n\n详细日志：{log_path}")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_events)


def main() -> int:
    root = Tk()
    ArcaneUpdaterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
