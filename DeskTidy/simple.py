# -*- coding: utf-8 -*-
"""简洁模式：浅色简约界面，一个大按钮完成「分类归档 + 图标排布」。"""
from __future__ import annotations

import csv
import json
import os
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import classifier, desktop_layout, organizer, scanner, taskbar

BG = "#f6f7f9"
CARD = "#ffffff"
INK = "#1b1f27"
MUTED = "#8a90a0"
ACCENT = "#2f6fed"
ACCENT_HOVER = "#2a62d4"
CHIP = "#eef1f6"
LINE = "#e6e9f0"
FONT = "Microsoft YaHei UI"

LAYOUT_OPTIONS = [("l", "倒L型"), ("top", "顶部横向"), ("left", "左侧竖向")]

REPORT_DIR = organizer.DATA_DIR / "reports"
SNAPSHOT_FILE = organizer.DATA_DIR / "layout_snapshot.json"
GUIDE_FLAG = organizer.DATA_DIR / "onboarded.flag"


class SimpleView(tk.Frame):
    def __init__(self, shell):
        super().__init__(shell, bg=BG)
        self.shell = shell
        self.rules = classifier.load_rules()
        self.items: list[scanner.DesktopItem] = []
        self.layout_key = "l"
        self.create_folders = True
        self.chips: dict[str, tk.Button] = {}

        try:
            ratio = float(self.winfo_toplevel().tk.call("tk", "scaling")) / (96.0 / 72.0)
        except Exception:
            ratio = 1.0
        self.scale = max(1.0, min(2.0, ratio))
        self.s = lambda value: int(round(value * self.scale))

        self.status = tk.StringVar(value="正在扫描桌面…")
        self.detail = tk.StringVar(value="")
        self.common_text = tk.StringVar(value="常用应用 ›")

        self._build()
        self.after(80, self.refresh)
        self.after(600, self._maybe_guide)

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=self.s(30), pady=self.s(22))

        top = tk.Frame(wrap, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="DeskTidy", bg=BG, fg=INK,
                 font=(FONT, 19, "bold")).pack(side="left")
        classic = tk.Button(top, text="经典界面", command=self.shell.show_classic,
                            bg=BG, fg=MUTED, activebackground=BG, activeforeground=INK,
                            relief="flat", bd=0, cursor="hand2", font=(FONT, 9))
        classic.pack(side="right", pady=self.s(4))

        tk.Label(wrap, text="一键归档，按类别排布桌面图标",
                 bg=BG, fg=MUTED, font=(FONT, 10)).pack(anchor="w", pady=(self.s(4), 0))

        card = tk.Frame(wrap, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", pady=(self.s(16), 0))

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=self.s(22), pady=self.s(20))

        tk.Label(inner, textvariable=self.status, bg=CARD, fg=INK,
                 font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(inner, textvariable=self.detail, bg=CARD, fg=MUTED,
                 font=(FONT, 9), justify="left", wraplength=self.s(420)
                 ).pack(anchor="w", pady=(self.s(5), self.s(14)))

        layout_row = tk.Frame(inner, bg=CARD)
        layout_row.pack(fill="x", pady=(0, self.s(14)))
        tk.Label(layout_row, text="图标排布", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(0, self.s(10)))
        for key, label in LAYOUT_OPTIONS:
            chip = tk.Button(layout_row, text=label, bd=0, relief="flat",
                             font=(FONT, 9), padx=self.s(10), pady=self.s(4),
                             cursor="hand2",
                             command=lambda k=key: self.choose_layout(k))
            chip.pack(side="left", padx=(0, self.s(6)))
            self.chips[key] = chip
        self._paint_chips()

        self.big = tk.Button(inner, text="一键整理", command=self.run_organize,
                             bg=ACCENT, fg="white", activebackground=ACCENT_HOVER,
                             activeforeground="white", relief="flat", bd=0,
                             cursor="hand2", font=(FONT, 18, "bold"), height=3)
        self.big.pack(fill="x")
        self.big.bind("<Enter>", lambda _e: self.big.configure(bg=ACCENT_HOVER))
        self.big.bind("<Leave>", lambda _e: self.big.configure(bg=ACCENT))

        opts = tk.Frame(inner, bg=CARD)
        opts.pack(fill="x", pady=(self.s(12), 0))
        self.folders_var = tk.BooleanVar(value=True)
        self.check = tk.Checkbutton(opts, text="创建分类文件夹", variable=self.folders_var,
                                    command=self.toggle_folders, bg=CARD, fg=INK,
                                    activebackground=CARD, selectcolor=CARD,
                                    font=(FONT, 9), bd=0, highlightthickness=0)
        self.check.pack(side="left")
        common = tk.Button(opts, textvariable=self.common_text, command=self.pick_common,
                           bg=CARD, fg=ACCENT, activebackground=CARD,
                           activeforeground=ACCENT_HOVER, relief="flat", bd=0,
                           cursor="hand2", font=(FONT, 9))
        common.pack(side="right")

        tk.Label(inner, text="微信、QQ、浏览器等常用应用会留在桌面，不放进文件夹。",
                 bg=CARD, fg=MUTED, font=(FONT, 9), justify="left",
                 wraplength=self.s(420)).pack(anchor="w", pady=(self.s(10), 0))

        tools = tk.Frame(wrap, bg=BG)
        tools.pack(fill="x", pady=(self.s(12), 0))
        ttk.Button(tools, text="任务栏透明", command=self.toggle_taskbar).pack(side="left")
        self.undo_btn = ttk.Button(tools, text="撤销上次整理", command=self.undo)
        self.undo_btn.pack(side="left", padx=(8, 0))
        self.undo_btn.state(["disabled"])
        self.restore_btn = ttk.Button(tools, text="恢复布局", command=self.restore_layout)
        self.restore_btn.pack(side="left", padx=(8, 0))
        self.restore_btn.state(["!disabled"] if SNAPSHOT_FILE.exists() else ["disabled"])

        tk.Label(wrap, text="倒L排列只调整图标位置、不移动文件；文件夹和系统图标不受影响。"
                            "若图标没有变化，请右键桌面 → 查看 → 取消「自动排列图标」。",
                 bg=BG, fg=MUTED, font=(FONT, 9), justify="left",
                 wraplength=self.s(450)).pack(anchor="w", pady=(self.s(12), 0))

    def _paint_chips(self) -> None:
        for key, chip in self.chips.items():
            active = key == self.layout_key
            chip.configure(bg=ACCENT if active else CHIP,
                           fg="white" if active else MUTED,
                           activebackground=ACCENT_HOVER if active else "#e2e7f0",
                           activeforeground="white" if active else INK)

    def choose_layout(self, key: str) -> None:
        self.layout_key = key
        self._paint_chips()

    def toggle_folders(self) -> None:
        self.create_folders = bool(self.folders_var.get())

    # ---------------- 扫描 ----------------
    def refresh(self, silent: bool = False) -> None:
        try:
            result = scanner.scan(rules=organizer.effective_rules(self.rules),
                                  overrides=organizer.load_overrides())
        except Exception as exc:
            self.status.set("扫描失败")
            self.detail.set(str(exc))
            return
        self.items = [item for item in result.items if not item.is_dir]
        common = sum(1 for item in self.items if item.category == "常用")
        self.common_text.set("常用应用 %d ›" % common)
        if not silent:
            self.status.set("桌面共 %d 项" % len(result.items))
            self.detail.set("%d 个常用应用保留在桌面 · %d 个文件待归档" %
                            (common, len(self.items) - common))
        self.undo_btn.state(["!disabled"] if organizer.last_journal() else ["disabled"])

    # ---------------- 一键整理 ----------------
    def run_organize(self) -> None:
        rules = organizer.effective_rules(self.rules)
        try:
            result = scanner.scan(rules=rules, overrides=organizer.load_overrides())
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc))
            return
        items = [item for item in result.items if not item.is_dir]
        if not items:
            messagebox.showinfo("没有可整理的项目", "桌面上没有扫描到可整理的文件或快捷方式。")
            return

        plan: list[organizer.Move] = []
        if self.create_folders:
            plan, _skipped = organizer.build_plan(items, rules)

        dry = False
        if plan:
            ok, dry = self._preview(plan, len(items))
            if not ok:
                return
        if dry:
            report = self._write_report(plan, None, 0, dry=True)
            self.status.set("演练完成（未改动任何文件）")
            self.detail.set("将归档 %d 个 · 将排列 %d 个%s" %
                            (len(plan), len(items),
                             " · 报告：%s" % report.name if report else ""))
            return

        self.big.configure(state="disabled", text="整理中…")
        self.update_idletasks()
        started = time.perf_counter()
        lines: list[str] = []
        try:
            applied = None
            if plan:
                applied = organizer.apply_plan(plan, conflict="rename", label="一键整理")
                lines.append("已归档 %d 个" % len(applied.moved))
                if applied.skipped or applied.errors:
                    lines.append("跳过 %d、失败 %d" %
                                 (len(applied.skipped), len(applied.errors)))
            else:
                lines.append("未建文件夹，仅排列" if not self.create_folders else "无需归档")

            result = scanner.scan(rules=rules, overrides=organizer.load_overrides())
            files = [item for item in result.items if not item.is_dir]
            self._save_snapshot()
            moved, notes = desktop_layout.arrange([item.name for item in files],
                                                  self.layout_key, ignore_unmatched=True)
            lines.append("已排列 %d 个（%s）" % (moved, dict(LAYOUT_OPTIONS)[self.layout_key]))
            lines.extend(notes)

            report = self._write_report(plan, applied, moved)
            lines.append("耗时 %.1fs" % (time.perf_counter() - started))
            self.refresh(silent=True)
            self.status.set("整理完成")
            self.detail.set(" · ".join(lines))
            if report and messagebox.askyesno(
                    "整理完成", "已归档 %d 个、排列 %d 个。\n\n报告已保存：\n%s\n\n是否打开报告？" %
                    (len(applied.moved) if applied else 0, moved, report)):
                os.startfile(str(report))
        except Exception as exc:
            messagebox.showerror("整理失败", str(exc))
            self.status.set("整理失败")
            self.detail.set(str(exc))
        finally:
            self.big.configure(state="normal", text="一键整理")

    # ---------------- 整理预览 ----------------
    def _preview(self, plan: list, total: int) -> tuple[bool, bool]:
        win = tk.Toplevel(self)
        win.title("整理预览")
        win.configure(bg=BG)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)

        tk.Label(win, text="将归档 %d 个文件到分类文件夹" % len(plan),
                 bg=BG, fg=INK, font=(FONT, 13, "bold")
                 ).pack(anchor="w", padx=self.s(20), pady=(self.s(18), self.s(4)))
        tk.Label(win, text="共 %d 个可整理项；常用应用、文件夹和系统图标保持原位。" % total,
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", padx=self.s(20))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=self.s(20), pady=(self.s(10), self.s(6)))
        canvas = tk.Canvas(body, bg=CARD, highlightbackground=LINE,
                           highlightthickness=1, width=self.s(360), height=self.s(220))
        scroll = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=CARD)
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=self.s(360))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for move in plan:
            row = tk.Frame(inner, bg=CARD)
            row.pack(fill="x", padx=self.s(10), pady=self.s(3))
            name = move.src.name
            if len(name) > 30:
                name = name[:28] + "…"
            tk.Label(row, text=name, bg=CARD, fg=INK, font=(FONT, 9),
                     anchor="w").pack(side="left")
            tk.Label(row, text="→ %s" % move.dst.parent.name, bg=CARD,
                     fg=ACCENT, font=(FONT, 9)).pack(side="right")

        dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="演练模式（只预览，不改动任何文件）",
                        variable=dry_var).pack(anchor="w", padx=self.s(20))

        answer = {"ok": False, "dry": False}

        def confirm() -> None:
            answer["ok"] = True
            answer["dry"] = bool(dry_var.get())
            win.destroy()

        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill="x", padx=self.s(20), pady=self.s(12))
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="开始整理", command=confirm
                   ).pack(side="right", padx=(0, self.s(8)))

        win.update_idletasks()
        parent = self.winfo_toplevel()
        win.geometry("+%d+%d" % (
            parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2,
            parent.winfo_rooty() + self.s(70)))
        self.wait_window(win)
        return answer["ok"], answer["dry"]

    # ---------------- 报告与快照 ----------------
    def _write_report(self, plan: list, applied, arranged: int, dry: bool = False):
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            path = REPORT_DIR / ("report_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"))
            status: dict[str, tuple[str, str]] = {}
            if applied:
                for src, dst in applied.moved:
                    status[str(src)] = ("已移动", str(dst))
                for src, why in applied.skipped:
                    status[str(src)] = ("跳过", why)
                for src, why in applied.errors:
                    status[str(src)] = ("失败", why)
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["DeskTidy 整理报告",
                                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                writer.writerow(["演练模式" if dry else "已执行",
                                 "归档 %d" % len(plan), "排列 %d" % arranged])
                writer.writerow([])
                writer.writerow(["文件名", "类别", "动作", "原路径", "新路径", "结果"])
                for move in plan:
                    state, extra = status.get(str(move.src), ("未执行", ""))
                    writer.writerow([move.src.name, move.category, "归档",
                                     str(move.src),
                                     extra if state == "已移动" else str(move.dst),
                                     state])
            return path
        except Exception:
            return None

    def _save_snapshot(self) -> None:
        try:
            positions = desktop_layout.read_positions()
            SNAPSHOT_FILE.write_text(
                json.dumps({str(key): list(value) for key, value in positions.items()}),
                encoding="utf-8")
            self.restore_btn.state(["!disabled"])
        except Exception:
            pass

    def restore_layout(self) -> None:
        if not SNAPSHOT_FILE.exists():
            messagebox.showinfo("没有快照", "还没有可恢复的布局记录。")
            return
        try:
            data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
            positions = {int(key): tuple(value) for key, value in data.items()}
            count = desktop_layout.apply_positions(positions)
        except Exception as exc:
            messagebox.showerror("恢复失败", str(exc))
            return
        messagebox.showinfo("已恢复", "已恢复 %d 个图标的原位置。" % count)

    # ---------------- 首次使用引导 ----------------
    def _maybe_guide(self) -> None:
        if GUIDE_FLAG.exists():
            return
        win = tk.Toplevel(self)
        win.title("欢迎使用 DeskTidy")
        win.configure(bg=BG)
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)

        tk.Label(win, text="DeskTidy 只做三件事", bg=BG, fg=INK,
                 font=(FONT, 13, "bold")).pack(anchor="w", padx=self.s(22),
                                               pady=(self.s(18), self.s(8)))
        for line in ("1. 扫描桌面，自动按类别分组；常用应用和文件夹不动",
                     "2. 点「一键整理」会先弹出预览，确认后才移动文件",
                     "3. 不满意可「撤销上次整理」，或用「恢复布局」还原图标位置"):
            tk.Label(win, text=line, bg=BG, fg=MUTED, font=(FONT, 9),
                     justify="left", wraplength=self.s(340)
                     ).pack(anchor="w", padx=self.s(22), pady=self.s(3))

        def close() -> None:
            try:
                GUIDE_FLAG.write_text("1", encoding="utf-8")
            except OSError:
                pass
            win.destroy()

        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill="x", padx=self.s(22), pady=self.s(16))
        ttk.Button(buttons, text="开始使用", command=close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close)

        win.update_idletasks()
        parent = self.winfo_toplevel()
        win.geometry("+%d+%d" % (
            parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2,
            parent.winfo_rooty() + self.s(90)))

    def undo(self) -> None:
        entry = organizer.last_journal()
        if not entry:
            messagebox.showinfo("无记录", "还没有可撤销的整理记录。")
            return
        if not messagebox.askyesno(
                "撤销确认", "将撤销 %s 的「%s」，共 %d 项移动。继续？" %
                (entry.get("time", ""), entry.get("label", "整理"),
                 len(entry.get("moves", [])))):
            return
        restored, errors = organizer.undo_last()
        self.refresh(silent=True)
        self.status.set("已撤销")
        self.detail.set("还原 %d 项，失败 %d 项" % (len(restored), len(errors)))

    # ---------------- 任务栏透明 ----------------
    def toggle_taskbar(self) -> None:
        try:
            active = taskbar.layered_active()
        except Exception:
            active = False
        hint = ("将关闭任务栏透明、恢复系统默认外观。继续？" if active
                else "将把任务栏设为半透明（背景和图标一起变透，立即生效、"
                     "无需重启，也不用安装任何软件）。继续？")
        if not messagebox.askyesno("任务栏透明", hint):
            return
        try:
            message = taskbar.set_transparency(not active)
        except Exception as exc:
            messagebox.showerror("设置失败", str(exc))
            return
        messagebox.showinfo("任务栏透明", message)

    # ---------------- 自选常用应用 ----------------
    def pick_common(self) -> None:
        apps = [item for item in self.items
                if item.path.suffix.lower() in {".lnk", ".url", ".exe"}]
        win = tk.Toplevel(self)
        win.title("选择常用应用")
        win.configure(bg=BG)
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)

        tk.Label(win, text="勾选的应用会留在桌面，整理时不放进分类文件夹。",
                 bg=BG, fg=MUTED, font=(FONT, 9)
                 ).pack(anchor="w", padx=self.s(18), pady=(self.s(16), self.s(8)))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=self.s(18))
        canvas = tk.Canvas(body, bg=BG, highlightthickness=0, width=self.s(300),
                           height=self.s(240))
        scroll = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=self.s(300))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        vars_: dict = {}
        if apps:
            for item in apps:
                var = tk.BooleanVar(value=item.category == "常用")
                vars_[item.path] = var
                tk.Checkbutton(inner, text=item.name, variable=var, bg=BG, fg=INK,
                               activebackground=BG, selectcolor=CARD, anchor="w",
                               font=(FONT, 9), bd=0, highlightthickness=0,
                               padx=self.s(2)).pack(fill="x", pady=self.s(2))
        else:
            tk.Label(inner, text="桌面上没有快捷方式或程序。", bg=BG, fg=MUTED,
                     font=(FONT, 9)).pack(anchor="w")

        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill="x", padx=self.s(18), pady=(self.s(10), self.s(14)))
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="保存",
                   command=lambda: self._save_common(win, vars_)
                   ).pack(side="right", padx=(0, self.s(8)))

        win.update_idletasks()
        parent = self.winfo_toplevel()
        win.geometry("+%d+%d" % (
            parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2,
            parent.winfo_rooty() + self.s(80)))

    def _save_common(self, win: tk.Toplevel, vars_: dict) -> None:
        selected = [str(path) for path, var in vars_.items() if var.get()]
        organizer.save_pinned(selected)
        win.destroy()
        self.refresh(silent=True)
        self.status.set("常用应用已更新")
        self.detail.set("已选 %d 个应用保留在桌面" % len(selected))
