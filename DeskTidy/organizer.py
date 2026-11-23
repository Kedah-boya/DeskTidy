# -*- coding: utf-8 -*-
"""整理器：生成移动计划、执行整理、记录日志并支持撤销。

所有写操作都先出计划、再执行；执行前会做冲突检测，
任何异常都只影响单个文件，不会中断整批。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import classifier


def _data_dir() -> Path:
    """源码运行时放在包内 data/；打包成 exe 后写到用户目录，避免临时解包目录丢失。"""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DeskTidy"
    else:
        base = Path(__file__).with_name("data")
    return base


DATA_DIR = _data_dir()
OVERRIDES_FILE = DATA_DIR / "overrides.json"
JOURNAL_FILE = DATA_DIR / "journal.json"


def _load(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ---------- 手动归类的记忆 ----------

def load_overrides() -> dict:
    return _load(OVERRIDES_FILE, {})


def save_overrides(data: dict) -> None:
    _save(OVERRIDES_FILE, data)


def set_override(path: Path, category: str) -> None:
    data = load_overrides()
    data[str(path).lower()] = category
    save_overrides(data)


# ---------- 自选常用应用 ----------

PINNED_FILE = DATA_DIR / "pinned.json"


def load_pinned() -> dict:
    data = _load(PINNED_FILE, {})
    return data if isinstance(data, dict) else {}


def save_pinned(paths: list[str]) -> None:
    _save(PINNED_FILE, {"custom": True,
                        "paths": [str(Path(p)).lower() for p in paths]})


def effective_rules(rules: dict) -> dict:
    """把「自选常用应用」合并进规则；用户没自选时沿用内置常用清单。"""
    pinned = load_pinned()
    merged = dict(rules)
    if pinned.get("custom"):
        merged["use_default_common"] = False
        merged["common_paths"] = pinned.get("paths", [])
    return merged


# ---------- 移动计划 ----------

@dataclass
class Move:
    src: Path
    dst: Path
    category: str
    conflict: bool = False


@dataclass
class ApplyResult:
    moved: list[tuple[Path, Path]]
    skipped: list[tuple[Path, str]]
    errors: list[tuple[Path, str]]

    @property
    def total(self) -> int:
        return len(self.moved) + len(self.skipped) + len(self.errors)


def build_plan(items, rules: dict) -> tuple[list[Move], list[tuple[Path, str]]]:
    """返回 (可执行移动列表, 被跳过的说明列表)。"""
    pinned = rules.get("pinned_category", "保持原位")
    plan: list[Move] = []
    skipped: list[tuple[Path, str]] = []

    for item in items:
        category = item.category or ""
        if category in ("", pinned):
            skipped.append((item.path, "标记为保持原位"))
            continue
        folder = classifier.category_folder(rules, category)
        if not folder:
            skipped.append((item.path, "常用应用保持原位"))
            continue
        dst_dir = item.path.parent / folder
        if item.path.parent.name == folder:
            skipped.append((item.path, "已在该分类文件夹内"))
            continue
        if item.is_dir and item.entry == folder:
            skipped.append((item.path, "分类文件夹本身"))
            continue
        dst = dst_dir / item.path.name
        if dst.exists() and dst.resolve() == item.path.resolve():
            skipped.append((item.path, "目标与源相同"))
            continue
        plan.append(Move(src=item.path, dst=dst, category=category,
                         conflict=dst.exists()))
    return plan, skipped


def _unique_target(dst: Path) -> Path:
    stem, suffix = dst.stem, dst.suffix
    index = 2
    while True:
        candidate = dst.with_name("%s (%d)%s" % (stem, index, suffix))
        if not candidate.exists():
            return candidate
        index += 1


def apply_plan(plan: list[Move], conflict: str = "rename",
               label: str = "一键整理") -> ApplyResult:
    """conflict: rename=自动改名, skip=跳过同名。"""
    result = ApplyResult(moved=[], skipped=[], errors=[])
    created: list[Path] = []
    for move in plan:
        src, dst = move.src, move.dst
        try:
            if not src.exists():
                result.skipped.append((src, "源文件已不存在"))
                continue
            if not dst.parent.is_dir():
                dst.parent.mkdir(parents=True, exist_ok=True)
                created.append(dst.parent)
            if dst.exists():
                if conflict == "skip":
                    result.skipped.append((src, "目标已存在"))
                    continue
                dst = _unique_target(dst)
            shutil.move(str(src), str(dst))
            result.moved.append((src, dst))
        except Exception as exc:
            result.errors.append((src, str(exc)))

    # 只清理本次新建、且最终没放进去任何文件的分类文件夹
    for directory in sorted(set(created), key=lambda p: len(str(p)), reverse=True):
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            pass

    if result.moved:
        _append_journal(label, [(str(s), str(d)) for s, d in result.moved])
    return result


def _append_journal(label: str, moves: list[tuple[str, str]]) -> None:
    journal = _load(JOURNAL_FILE, [])
    journal.append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "moves": [{"src": s, "dst": d} for s, d in moves],
    })
    _save(JOURNAL_FILE, journal[-50:])


def move_items(paths: list[Path], dest_dir: Path,
               label: str = "手动移动") -> ApplyResult:
    plan = [Move(src=p, dst=dest_dir / p.name, category=dest_dir.name,
                 conflict=(dest_dir / p.name).exists()) for p in paths]
    return apply_plan(plan, conflict="rename", label=label)


def last_journal() -> dict | None:
    journal = _load(JOURNAL_FILE, [])
    return journal[-1] if journal else None


def undo_last() -> tuple[list[tuple[Path, Path]], list[tuple[Path, str]]]:
    """撤销最近一次移动。返回 (已还原, 失败说明)。"""
    journal = _load(JOURNAL_FILE, [])
    if not journal:
        return [], []
    entry = journal.pop()
    restored, errors = [], []
    folders: list[Path] = []
    for record in reversed(entry.get("moves", [])):
        src, dst = Path(record["src"]), Path(record["dst"])
        folders.append(dst.parent)
        try:
            if not dst.exists():
                errors.append((dst, "目标已不存在，无法还原"))
                continue
            if src.exists():
                errors.append((src, "原位置已被占用"))
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            restored.append((dst, src))
        except Exception as exc:
            errors.append((dst, str(exc)))

    # 还原后把因此空出来的分类文件夹一并删掉
    for directory in sorted(set(folders), key=lambda p: len(str(p)), reverse=True):
        try:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            pass

    _save(JOURNAL_FILE, journal)
    return restored, errors
