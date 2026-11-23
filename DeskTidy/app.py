# -*- coding: utf-8 -*-
"""DeskTidy 主界面：扫描 → 分类预览 → 手动/一键整理 → 撤销。"""
from __future__ import annotations

import csv
import os
import subprocess
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import classifier, icons, organizer, scanner

APP_TITLE = "DeskTidy · Windows 桌面图标整理分类工具"

BG = "#f5f6f8"
CARD = "#ffffff"
INK = "#1f2430"
MUTED = "#7a8296"
LINE = "#e3e7ef"
ACCENT = "#3b6ff5"
ACCENT_HOVER = "#2f5fe0"

SCOPES = [("用户桌面", "user"), ("公共桌面", "public"), ("用户 + 公共桌面", "both")]


class App:
    def __init__(self, root: tk.Tk, parent: tk.Widget | None = None,
                 on_simple=None):
        self.root = root
        self.parent = parent or root
        self.on_simple = on_simple
        self.rules = classifier.load_rules()
        self.overrides = organizer.load_overrides()
        self.items: list[scanner.DesktopItem] = []
        self.row_items: dict[str, scanner.DesktopItem] = {}
        self.icon_cache: dict[str, tk.PhotoImage] = {}
        self.real_icons = 0
        self.fallback_icons = 0

        self.scope_text = tk.StringVar(value=SCOPES[-1][0])
        self.only_shortcuts = tk.BooleanVar(value=False)
        self.search = tk.StringVar()
        self.filter_cat = tk.StringVar(value="全部类别")
        self.cat_pick = tk.StringVar(value="")
        self.status = tk.StringVar(value="准备就绪，点击「重新扫描」开始")
        self.summary_text = tk.StringVar(value="")

        try:
            ratio = float(root.tk.call("tk", "scaling")) / (96.0 / 72.0)
        except Exception:
            ratio = 1.0
        self.scale = max(1.0, min(2.0, ratio))
        self.s = lambda value: int(round(value * self.scale))

        self._build_style()
        self._build_header()
        self._build_toolbar()
        self._build_body()
        self._build_footer()

        self.search.trace_add("write", lambda *_: self._populate())
        self.root.after(120, self.scan)

    # ---------------- 外观 ----------------
    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        font = ("Microsoft YaHei UI", 10)
        style.configure(".", font=font, background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=CARD, foreground=INK)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=CARD, foreground=INK,
                        font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Sub.TLabel", background=CARD, foreground=MUTED,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Section.TLabel", background=CARD, foreground=INK,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=INK, rowheight=self.s(40), borderwidth=0)
        style.configure("Treeview.Heading", background="#eef1f7", foreground=INK,
                        font=("Microsoft YaHei UI", 9, "bold"), relief="flat",
                        padding=(8, 6))
        style.map("Treeview", background=[("selected", "#dbe6ff")],
                  foreground=[("selected", INK)])
        style.map("Treeview.Heading", background=[("active", "#e2e7f1")])
        style.configure("TButton", padding=(10, 5), background="#eef1f7",
                        borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", "#e2e7f1")])
        style.configure("TCheckbutton", background=CARD)
        style.configure("TCombobox", padding=4)
        style.configure("TSeparator", background=LINE)

    def _accent(self, parent, text, command, width=None):
        btn = tk.Button(parent, text=text, command=command, bg=ACCENT, fg="white",
                        activebackground=ACCENT_HOVER, activeforeground="white",
                        relief="flat", bd=0, cursor="hand2",
                        font=("Microsoft YaHei UI", 10, "bold"),
                        padx=14, pady=6)
        if width:
            btn.configure(width=width)
        btn.bind("<Enter>", lambda _e: btn.configure(bg=ACCENT_HOVER))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=ACCENT))
        return btn

    # ---------------- 布局 ----------------
    def _build_header(self) -> None:
        self.header = tk.Frame(self.parent, bg=CARD)
        self.header.pack(fill="x")
        inner = tk.Frame(self.header, bg=CARD)
        inner.pack(fill="x", padx=18, pady=(12, 10))
        tk.Label(inner, text="DeskTidy", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        tk.Label(inner, text="Windows 桌面图标整理分类工具", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(10, 0), pady=(6, 0))
        tk.Label(inner, text="扫描 · 归类 · 一键整理", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="right", pady=(8, 0))

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.parent, bg=CARD)
        bar.pack(fill="x", padx=18, pady=(0, 10))

        tk.Label(bar, text="扫描范围", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        ttk.Combobox(bar, textvariable=self.scope_text, state="readonly", width=14,
                     values=[s[0] for s in SCOPES]).pack(side="left", padx=(4, 12))
        ttk.Checkbutton(bar, text="只看快捷方式/网址",
                        variable=self.only_shortcuts).pack(side="left")

        tk.Label(bar, text="搜索", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(14, 4))
        ttk.Entry(bar, textvariable=self.search, width=20).pack(side="left")

        tk.Label(bar, text="类别", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(12, 4))
        self.cat_filter = ttk.Combobox(
            bar, textvariable=self.filter_cat, state="readonly", width=12,
            values=["全部类别"] + classifier.category_names(self.rules))
        self.cat_filter.pack(side="left")
        self.cat_filter.bind("<<ComboboxSelected>>", lambda _e: self._populate())

        self._accent(bar, "重新扫描", self.scan).pack(side="left", padx=(16, 0))
        ttk.Button(bar, text="导出报告", command=self.export_csv).pack(side="left", padx=(8, 0))

    def _build_body(self) -> None:
        body = tk.Frame(self.parent, bg=BG)
        body.pack(fill="both", expand=True, padx=18)

        left = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)

        columns = ("kind", "category", "target", "size", "mtime")
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="名称")
        self.tree.heading("kind", text="类型")
        self.tree.heading("category", text="类别")
        self.tree.heading("target", text="目标 / 说明")
        self.tree.heading("size", text="大小")
        self.tree.heading("mtime", text="修改时间")
        self.tree.column("#0", width=self.s(220), minwidth=self.s(160))
        self.tree.column("kind", width=self.s(76), anchor="center", stretch=False)
        self.tree.column("category", width=self.s(94), anchor="center", stretch=False)
        self.tree.column("target", width=self.s(280))
        self.tree.column("size", width=self.s(74), anchor="e", stretch=False)
        self.tree.column("mtime", width=self.s(112), anchor="center", stretch=False)

        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self._build_menu()

        right = tk.Frame(body, bg=CARD, width=self.s(320),
                         highlightbackground=LINE, highlightthickness=1)
        right.pack(side="left", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        inner = tk.Frame(right, bg=CARD)
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        tk.Label(inner, text="分类统计", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.summary_label = tk.Label(inner, textvariable=self.summary_text, bg=CARD,
                                      fg=MUTED, font=("Microsoft YaHei UI", 9),
                                      wraplength=self.s(286), justify="left")
        self.summary_label.pack(anchor="w", pady=(2, 8))
        self.stats_canvas = tk.Canvas(inner, bg=CARD, highlightthickness=0,
                                      width=self.s(290), height=self.s(230))
        self.stats_canvas.pack(fill="x")

        ttk.Separator(inner).pack(fill="x", pady=12)

        tk.Label(inner, text="手动整理", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        tk.Label(inner, text="选中列表项后，可单独改类别或移动到任意文件夹。",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9),
                 wraplength=280, justify="left").pack(anchor="w", pady=(2, 8))

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(0, 6))
        self.cat_combo = ttk.Combobox(row, textvariable=self.cat_pick, state="readonly",
                                      width=13, values=classifier.category_names(self.rules))
        self.cat_combo.pack(side="left")
        ttk.Button(row, text="应用类别", command=self.assign_category).pack(side="left", padx=(6, 0))

        ttk.Button(inner, text="移动到指定文件夹…", command=self.move_selected).pack(fill="x", pady=2)
        ttk.Button(inner, text="在资源管理器中显示", command=self.reveal_selected).pack(fill="x", pady=2)
        ttk.Button(inner, text="打开选中项", command=self.open_selected).pack(fill="x", pady=2)

        tk.Label(inner, text="整理只移动桌面项本身，不改动文件内容；\n"
                             "每次移动都会记录，可在底部一键撤销。",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9),
                 justify="left").pack(anchor="w", pady=(10, 0))

    def _build_footer(self) -> None:
        foot = tk.Frame(self.parent, bg=BG)
        foot.pack(fill="x", padx=18, pady=(10, 12))

        self._accent(foot, "一键整理全部", self.organize_all).pack(side="left")
        ttk.Button(foot, text="撤销上次整理", command=self.undo_last).pack(side="left", padx=(8, 0))
        ttk.Button(foot, text="仅整理选中项", command=self.organize_selected).pack(side="left", padx=(8, 0))
        if self.on_simple:
            ttk.Button(foot, text="简洁模式", command=self.on_simple).pack(side="left", padx=(8, 0))

        tk.Label(foot, textvariable=self.status, bg=BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="right")

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="打开", command=self.open_selected)
        self.menu.add_command(label="在资源管理器中显示", command=self.reveal_selected)
        self.menu.add_separator()
        cat_menu = tk.Menu(self.menu, tearoff=0)
        for name in classifier.category_names(self.rules):
            cat_menu.add_command(label=name,
                                 command=lambda n=name: self.assign_category(n))
        self.menu.add_cascade(label="归类到", menu=cat_menu)
        self.menu.add_command(label="移动到指定文件夹…", command=self.move_selected)
        self.menu.add_separator()
        self.menu.add_command(label="重新扫描", command=self.scan)
        self.tree.bind("<Button-3>", self._popup)

    def _popup(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---------------- 扫描 ----------------
    def scan(self) -> None:
        scope = dict(SCOPES).get(self.scope_text.get(), "both")
        self.status.set("正在扫描桌面…")
        self.root.update_idletasks()
        try:
            result = scanner.scan(scope=scope,
                                  only_shortcuts=self.only_shortcuts.get(),
                                  rules=organizer.effective_rules(self.rules),
                                  overrides=organizer.load_overrides())
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc))
            self.status.set("扫描失败")
            return

        self.items = result.items
        self.overrides = organizer.load_overrides()
        self._populate()
        self._draw_stats()

        detail = "共 %d 项 · 用时 %.2fs" % (len(result.items), result.elapsed)
        if result.skipped:
            detail += " · 已过滤 %d 项" % result.skipped
        if result.errors:
            detail += " · %d 个异常" % len(result.errors)
        self.summary_text.set(detail)
        self.status.set("扫描完成：%d 项 · %.2fs · 来源 %d 处" %
                        (len(result.items), result.elapsed, len(result.roots)))

    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.row_items.clear()
        keyword = self.search.get().strip().lower()
        cat = self.filter_cat.get()

        for item in self.items:
            if cat and cat != "全部类别" and item.category != cat:
                continue
            if keyword:
                haystack = " ".join([item.name, item.entry, item.target,
                                     item.category, item.kind]).lower()
                if keyword not in haystack:
                    continue
            image = self._icon_for(item)
            target = item.target
            if item.args:
                target += " " + item.args
            if item.error:
                target = "解析失败：" + item.error
            iid = self.tree.insert("", "end", text="  " + item.name, image=image,
                                   values=(item.kind, item.category, target,
                                           item.size_text, item.mtime_text))
            self.row_items[iid] = item

    def _icon_for(self, item) -> tk.PhotoImage:
        key = str(item.path).lower()
        cached = self.icon_cache.get(key)
        if cached is not None:
            return cached
        color = classifier.category_color(self.rules, item.category)
        image = icons.get_icon(self.root, item.path, color, size=self.s(32))
        if image is None:
            image = icons.fallback_icon(self.root, color, size=self.s(32))
            self.fallback_icons += 1
        else:
            self.real_icons += 1
        self.icon_cache[key] = image
        return image

    def _draw_stats(self) -> None:
        canvas = self.stats_canvas
        canvas.delete("all")
        rows = scanner.summary(self.items, self.rules)
        if not rows:
            canvas.create_text(8, 12, anchor="nw", text="暂无扫描结果",
                               fill=MUTED, font=("Microsoft YaHei UI", 9))
            return
        max_count = max(count for _, count, _ in rows)
        y = self.s(4)
        for name, count, color in rows:
            canvas.create_text(self.s(6), y + self.s(9), anchor="w", text=name, fill=INK,
                               font=("Microsoft YaHei UI", 9))
            canvas.create_text(self.s(284), y + self.s(9), anchor="e", text=str(count),
                               fill=MUTED, font=("Microsoft YaHei UI", 9))
            width = int(self.s(150) * count / max_count)
            canvas.create_rectangle(self.s(96), y + self.s(3),
                                    self.s(96) + max(width, self.s(3)), y + self.s(15),
                                    fill=color, outline="")
            y += self.s(24)
        canvas.configure(height=y + self.s(6))

    # ---------------- 选择与手动操作 ----------------
    def selected_items(self) -> list[scanner.DesktopItem]:
        return [self.row_items[i] for i in self.tree.selection() if i in self.row_items]

    def _on_select(self, _event=None) -> None:
        items = self.selected_items()
        if items:
            self.cat_pick.set(items[0].category)
            self.status.set("已选中 %d 项" % len(items))

    def assign_category(self, name: str | None = None) -> None:
        target = name or self.cat_pick.get()
        items = self.selected_items()
        if not target:
            messagebox.showinfo("提示", "请先在右侧选择目标类别。")
            return
        if not items:
            messagebox.showinfo("提示", "请先在列表中选中要归类的项目。")
            return
        data = organizer.load_overrides()
        for item in items:
            data[str(item.path).lower()] = target
            item.category = target
            item.matched = "手动指定"
        organizer.save_overrides(data)
        self.overrides = data
        for iid, item in self.row_items.items():
            if item in items:
                values = list(self.tree.item(iid, "values"))
                values[1] = target
                self.tree.item(iid, values=values)
        self._draw_stats()
        self.status.set("已将 %d 项归类为「%s」" % (len(items), target))

    def move_selected(self) -> None:
        items = self.selected_items()
        if not items:
            messagebox.showinfo("提示", "请先在列表中选中要移动的项目。")
            return
        dest = filedialog.askdirectory(title="选择要移动到的文件夹",
                                       initialdir=str(items[0].path.parent))
        if not dest:
            return
        result = organizer.move_items([i.path for i in items], Path(dest))
        self.scan()
        messagebox.showinfo("移动完成",
                            "成功 %d 项，跳过 %d 项，失败 %d 项。" %
                            (len(result.moved), len(result.skipped), len(result.errors)))

    def open_selected(self) -> None:
        items = self.selected_items()
        if not items:
            return
        try:
            os.startfile(str(items[0].path))
        except OSError as exc:
            messagebox.showerror("无法打开", str(exc))

    def reveal_selected(self) -> None:
        items = self.selected_items()
        if not items:
            return
        try:
            subprocess.Popen(["explorer.exe", "/select,", str(items[0].path)])
        except OSError as exc:
            messagebox.showerror("无法打开资源管理器", str(exc))

    # ---------------- 一键整理 ----------------
    def organize_all(self) -> None:
        self._organize(self.items)

    def organize_selected(self) -> None:
        items = self.selected_items()
        if not items:
            messagebox.showinfo("提示", "请先选中要整理的项。")
            return
        self._organize(items)

    def _organize(self, items) -> None:
        if not items:
            messagebox.showinfo("提示", "列表为空，请先扫描桌面。")
            return
        plan, skipped = organizer.build_plan(items, self.rules)
        if not plan:
            messagebox.showinfo("无需整理", "当前项目都已归类到位。")
            return
        OrganizeDialog(self.root, plan, skipped, self._after_organize, self.scale)

    def _after_organize(self, result) -> None:
        self.scan()
        messagebox.showinfo(
            "整理完成",
            "已移动 %d 项，跳过 %d 项，失败 %d 项。" %
            (len(result.moved), len(result.skipped), len(result.errors)))

    def undo_last(self) -> None:
        entry = organizer.last_journal()
        if not entry:
            messagebox.showinfo("无记录", "还没有可撤销的整理记录。")
            return
        if not messagebox.askyesno(
                "撤销确认",
                "将撤销 %s 的「%s」，共 %d 项移动。继续？" %
                (entry.get("time", ""), entry.get("label", "整理"),
                 len(entry.get("moves", [])))):
            return
        restored, errors = organizer.undo_last()
        self.scan()
        messagebox.showinfo("撤销完成",
                            "已还原 %d 项，失败 %d 项。" % (len(restored), len(errors)))

    # ---------------- 导出 ----------------
    def export_csv(self) -> None:
        if not self.items:
            messagebox.showinfo("提示", "还没有扫描结果。")
            return
        default = time.strftime("desktop_scan_%Y%m%d_%H%M%S.csv")
        path = filedialog.asksaveasfilename(
            title="导出扫描报告", defaultextension=".csv", initialfile=default,
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["名称", "类型", "类别", "命中规则", "目标",
                                 "参数", "大小(字节)", "修改时间", "桌面", "完整路径"])
                for item in self.items:
                    writer.writerow([item.name, item.kind, item.category, item.matched,
                                     item.target, item.args, item.size,
                                     item.mtime_text, item.desktop, str(item.path)])
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self.status.set("报告已导出：" + path)


class OrganizeDialog(tk.Toplevel):
    """整理前的预览确认窗口。"""

    def __init__(self, master, plan, skipped, on_done, scale: float = 1.0):
        super().__init__(master)
        self.plan = plan
        self.skipped = skipped
        self.on_done = on_done
        self.conflict = tk.StringVar(value="rename")
        self.scale = scale
        self.s = lambda value: int(round(value * scale))

        self.title("一键整理 · 预览")
        self.configure(bg=CARD)
        self.geometry("%dx%d" % (self.s(820), self.s(540)))
        self.transient(master.winfo_toplevel())
        self.grab_set()

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x", padx=18, pady=(16, 6))
        tk.Label(head, text="整理计划", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        tk.Label(head, text="待移动 %d 项 · 保持原位 %d 项 · 按类别创建文件夹" %
                           (len(plan), len(skipped)),
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(2, 0))

        wrap = tk.Frame(self, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=18, pady=6)
        tree = ttk.Treeview(wrap, columns=("cat", "dest"), show="tree headings")
        tree.heading("#0", text="名称")
        tree.heading("cat", text="类别")
        tree.heading("dest", text="移动到")
        tree.column("#0", width=self.s(330))
        tree.column("cat", width=self.s(110), anchor="center")
        tree.column("dest", width=self.s(330))
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

        for move in plan:
            note = "（同名，将自动改名）" if move.conflict else ""
            tree.insert("", "end", text="  " + move.src.name,
                        values=(move.category, move.dst.parent.name + note))

        foot = tk.Frame(self, bg=CARD)
        foot.pack(fill="x", padx=18, pady=(6, 16))
        tk.Label(foot, text="同名冲突：", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Radiobutton(foot, text="自动改名", variable=self.conflict, value="rename",
                       bg=CARD, activebackground=CARD, font=("Microsoft YaHei UI", 9)
                       ).pack(side="left")
        tk.Radiobutton(foot, text="跳过", variable=self.conflict, value="skip",
                       bg=CARD, activebackground=CARD, font=("Microsoft YaHei UI", 9)
                       ).pack(side="left", padx=(8, 0))

        tk.Button(foot, text="取消", command=self.destroy, relief="flat", bd=0,
                  bg="#eef1f7", fg=INK, padx=16, pady=6, cursor="hand2"
                  ).pack(side="right")
        tk.Button(foot, text="执行整理", command=self._run, relief="flat", bd=0,
                  bg=ACCENT, fg="white", activebackground=ACCENT_HOVER,
                  activeforeground="white", padx=18, pady=6, cursor="hand2",
                  font=("Microsoft YaHei UI", 10, "bold")
                  ).pack(side="right", padx=(0, 8))

    def _run(self) -> None:
        result = organizer.apply_plan(self.plan, conflict=self.conflict.get(),
                                      label="一键整理")
        self.grab_release()
        self.destroy()
        self.on_done(result)
