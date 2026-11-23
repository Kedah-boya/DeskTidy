# -*- coding: utf-8 -*-
"""分类规则引擎：把扫描到的桌面项映射到类别。

规则沿用软件扫描器的思路：
  多条关键词（白名单） + 子串匹配 + 打分排序，命不中则走兜底类别。
名称命中权重最高，其次目标路径，最后是扩展名。
"""
from __future__ import annotations

import json
from pathlib import Path

RULES_PATH = Path(__file__).with_name("rules.json")


def load_rules(path: Path | None = None) -> dict:
    path = Path(path) if path else RULES_PATH
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def category_names(rules: dict) -> list[str]:
    return [c["name"] for c in rules["categories"]] + [rules.get("pinned_category", "保持原位")]


def folder_map(rules: dict) -> dict[str, str]:
    return {c["name"]: c["folder"] for c in rules["categories"]}


def category_folder(rules: dict, name: str) -> str:
    return folder_map(rules).get(name, name)


def category_color(rules: dict, name: str) -> str:
    for cat in rules["categories"]:
        if cat["name"] == name:
            return cat.get("color", "#7a7f8c")
    return "#9aa0ad"


def classify(name: str, target: str, suffix: str,
             is_dir: bool, rules: dict) -> tuple[str, int, str]:
    """返回 (类别, 得分, 命中的关键词)。"""
    name_l = name.lower()
    target_l = (target or "").lower()
    suffix_l = (suffix or "").lower()

    best_cat, best_score, best_kw = "", 0, ""
    use_default_common = rules.get("use_default_common", True)
    for cat in rules["categories"]:
        if cat["name"] == "常用" and not use_default_common:
            continue
        score, kw = 0, ""
        for word in cat.get("keywords", []):
            word_l = word.lower()
            if word_l and word_l in name_l:
                score = max(score, 3)
                kw = kw or word
            elif word_l and word_l in target_l:
                if score < 2:
                    score, kw = 2, word
        if suffix_l and suffix_l in [e.lower() for e in cat.get("extensions", [])]:
            if score < 1:
                score, kw = 1, suffix_l
        if score > best_score:
            best_cat, best_score, best_kw = cat["name"], score, kw

    if best_score:
        return best_cat, best_score, best_kw
    return (rules.get("fallback_folder", "资料文件夹") if is_dir
            else rules.get("fallback_other", "其他")), 0, ""
