# -*- coding: utf-8 -*-
"""PyInstaller 打包入口（也可直接 python DeskTidy/launcher.py 运行）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DeskTidy.__main__ import run_gui  # noqa: E402

if __name__ == "__main__":
    run_gui()
