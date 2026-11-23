# -*- coding: utf-8 -*-
"""桌面扫描内核。

对应软件扫描器的四步：
  1. 多来源枚举（用户桌面 + 公共桌面，等价于两个注册表分支）
  2. 逐项提取字段（名称 / 类型 / 快捷方式目标 / 大小 / 修改时间）
  3. 过滤系统项（desktop.ini、隐藏项、临时文件）
  4. 关键词规则归档（classifier），并统计耗时
"""
from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import classifier, shelllink

HIDDEN = 0x2
SYSTEM = 0x4

DOC_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf",
            ".txt", ".md", ".csv", ".one"}
MEDIA_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".mp3", ".flac",
              ".wav", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@dataclass
class DesktopItem:
    path: Path
    name: str
    entry: str
    kind: str
    target: str = ""
    args: str = ""
    size: int = 0
    mtime: float = 0.0
    desktop: str = ""
    is_dir: bool = False
    category: str = ""
    score: int = 0
    matched: str = ""
    error: str = ""

    @property
    def size_text(self) -> str:
        if self.is_dir:
            return "-"
        size = float(self.size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return ("%.0f %s" % (size, unit)) if unit == "B" else ("%.1f %s" % (size, unit))
            size /= 1024
        return "-"

    @property
    def mtime_text(self) -> str:
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.mtime))
        except (OSError, ValueError):
            return "-"


@dataclass
class ScanResult:
    items: list[DesktopItem] = field(default_factory=list)
    roots: list[tuple[str, Path]] = field(default_factory=list)
    elapsed: float = 0.0
    errors: list[str] = field(default_factory=list)
    skipped: int = 0


def desktop_dirs() -> list[tuple[str, Path]]:
    """用户桌面 + 公共桌面。"""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    candidates = [("用户桌面", home / "Desktop")]
    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(("公共桌面", Path(public) / "Desktop"))
    return [(label, path) for label, path in candidates if path.is_dir()]


def _hidden(path: Path) -> bool:
    try:
        attrs = path.stat().st_file_attributes  # Windows 专有
    except (OSError, AttributeError):
        return False
    return bool(attrs & HIDDEN) and not path.is_dir()


def _ignored(entry: str, rules: dict) -> bool:
    low = entry.lower()
    return any(fnmatch.fnmatch(low, p.lower()) for p in rules.get("ignore_patterns", []))


def _kind_of(path: Path, suffix: str) -> str:
    if path.is_dir():
        return "文件夹"
    if suffix in {".lnk", ".url"}:
        return "快捷方式" if suffix == ".lnk" else "网址"
    if suffix in {".exe", ".bat", ".cmd", ".msi", ".ps1"}:
        return "程序"
    if suffix in DOC_EXTS:
        return "文档"
    if suffix in MEDIA_EXTS:
        return "媒体"
    if suffix in {".zip", ".rar", ".7z"}:
        return "压缩包"
    return "文件"


def scan(scope: str = "both", only_shortcuts: bool = False,
         rules: dict | None = None, overrides: dict | None = None) -> ScanResult:
    rules = rules or classifier.load_rules()
    overrides = overrides or {}
    started = time.time()
    result = ScanResult()

    roots = desktop_dirs()
    if scope == "user":
        roots = roots[:1]
    elif scope == "public":
        roots = [r for r in roots if r[0] == "公共桌面"]
    result.roots = roots

    pinned_folder_names = {name for name in classifier.folder_map(rules).values() if name}
    common_paths = {str(p).lower() for p in (rules.get("common_paths") or [])}
    seen: set[str] = set()

    for label, root in roots:
        try:
            entries = list(root.iterdir())
        except OSError as exc:
            result.errors.append("%s 读取失败: %s" % (label, exc))
            continue

        for path in entries:
            entry = path.name
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)

            if _ignored(entry, rules):
                result.skipped += 1
                continue
            if rules.get("ignore_hidden", True) and _hidden(path):
                result.skipped += 1
                continue

            suffix = path.suffix.lower()
            if only_shortcuts and suffix not in {".lnk", ".url"}:
                continue

            try:
                stat = path.stat()
            except OSError as exc:
                result.errors.append("%s 无法访问: %s" % (entry, exc))
                continue

            is_dir = path.is_dir()
            kind = _kind_of(path, suffix)
            info = {"target": "", "args": "", "kind": kind}
            if suffix in {".lnk", ".url"}:
                info = shelllink.resolve(path)
                kind = info.get("kind", kind)

            item = DesktopItem(
                path=path,
                name=path.stem if suffix in {".lnk", ".url"} else entry,
                entry=entry,
                kind=kind,
                target=info.get("target", ""),
                args=info.get("args", ""),
                size=0 if is_dir else stat.st_size,
                mtime=stat.st_mtime,
                desktop=label,
                is_dir=is_dir,
                error=info.get("error", ""),
            )

            if is_dir and entry in pinned_folder_names:
                item.category = rules.get("pinned_category", "保持原位")
                item.matched = "已整理的分类文件夹"
            elif key in overrides:
                item.category = overrides[key]
                item.matched = "手动指定"
            else:
                item.category, item.score, item.matched = classifier.classify(
                    item.name, item.target, suffix, is_dir, rules)

            if key in common_paths:
                item.category = "常用"
                item.matched = "自选常用"

            result.items.append(item)

    result.elapsed = time.time() - started
    result.items.sort(key=lambda i: (
        [c["name"] for c in rules["categories"]].index(i.category)
        if i.category in [c["name"] for c in rules["categories"]] else 99,
        i.name.lower()))
    return result


def summary(items: list[DesktopItem], rules: dict) -> list[tuple[str, int, str]]:
    """按类别汇总：[(类别, 数量, 颜色)]"""
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    order = [c["name"] for c in rules["categories"]] + [rules.get("pinned_category", "保持原位")]
    rows = []
    for name in order:
        if counts.get(name):
            rows.append((name, counts[name], classifier.category_color(rules, name)))
    return rows
