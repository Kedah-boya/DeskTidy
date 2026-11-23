# -*- coding: utf-8 -*-
"""程序入口：默认启动简洁模式，可随时切换到经典界面。

另有 --scan（命令行扫描报告）与 --selftest（界面冒烟测试）两个诊断入口。
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk


class Shell(tk.Tk):
    """主窗口：负责在「简洁模式」与「经典界面」之间切换。"""

    def __init__(self):
        super().__init__()
        from .app import APP_TITLE

        self.title(APP_TITLE)
        self.configure(bg="#f5f6f8")
        try:
            ratio = float(self.tk.call("tk", "scaling")) / (96.0 / 72.0)
        except Exception:
            ratio = 1.0
        self.scale = max(1.0, min(2.0, ratio))
        self.s = lambda value: int(round(value * self.scale))

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 10))

        self.view: tk.Widget | None = None
        self.app = None
        self.show_simple()

    def _clear(self) -> None:
        if self.view is not None:
            self.view.destroy()
            self.view = None
        self.app = None

    def _place(self, base_w: int, base_h: int, min_w: int, min_h: int) -> None:
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(self.s(base_w), screen_w - 40)
        height = min(self.s(base_h), screen_h - 80)
        left = max((screen_w - width) // 2, 0)
        top = max((screen_h - height) // 2 - 20, 0)
        self.geometry("%dx%d+%d+%d" % (width, height, left, top))
        self.minsize(self.s(min_w), self.s(min_h))

    def show_simple(self) -> None:
        from .simple import SimpleView

        self._clear()
        self.title("DeskTidy · 一键桌面整理")
        self._place(560, 570, 500, 540)
        self.resizable(False, False)
        self.view = SimpleView(self)
        self.view.pack(fill="both", expand=True)

    def show_classic(self) -> None:
        from .app import APP_TITLE, App

        self._clear()
        self.title(APP_TITLE)
        self._place(1220, 760, 860, 540)
        self.resizable(True, True)
        self.view = tk.Frame(self, bg="#f5f6f8")
        self.view.pack(fill="both", expand=True)
        self.app = App(self, parent=self.view, on_simple=self.show_simple)


def run_gui() -> None:
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    Shell().mainloop()


def cli_scan() -> None:
    from . import classifier, scanner

    rules = classifier.load_rules()
    result = scanner.scan(rules=rules)
    print("扫描来源：" + "、".join("%s(%s)" % (label, path) for label, path in result.roots))
    print("用时 %.2fs，共 %d 项，过滤 %d 项" % (result.elapsed, len(result.items), result.skipped))
    print("-" * 78)
    for item in result.items:
        print("%-8s %-10s %-30s %s" % (item.category, item.kind, item.name[:30],
                                       item.target[:40]))
    print("-" * 78)
    for name, count, _color in scanner.summary(result.items, rules):
        print("%-10s %d" % (name, count))
    if result.errors:
        print("异常：")
        for error in result.errors:
            print("  " + error)


def selftest() -> None:
    from .app import App
    from . import organizer

    root = tk.Tk()
    root.withdraw()
    app = App(root)
    app.scan()
    root.update()

    plan, skipped = organizer.build_plan(app.items, app.rules)
    print("selftest: items=%d rows=%d real_icons=%d fallback_icons=%d plan=%d skipped=%d" %
          (len(app.items), len(app.row_items), app.real_icons,
           app.fallback_icons, len(plan), len(skipped)))
    for item in app.items[:5]:
        print("  %-10s %-8s %s -> %s" % (item.category, item.kind, item.name,
                                         item.target[:60]))
    root.destroy()


if __name__ == "__main__":
    if "--scan" in sys.argv:
        cli_scan()
    elif "--selftest" in sys.argv:
        selftest()
    else:
        run_gui()
