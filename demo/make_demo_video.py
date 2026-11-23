# -*- coding: utf-8 -*-
"""自动录制 DeskTidy 演示视频（v2）。

驱动真实界面操作 + 逐帧抓屏 + 烧入字幕，最后用 ffmpeg 合成 MP4。

安全约束：
- 归档环节强制使用「演练模式」，不会移动任何用户文件
- 排布环节取消「创建分类文件夹」，只调整图标位置，结束前用「恢复布局」还原
- 录制期间最小化的窗口在结束后自动恢复
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import imageio_ffmpeg
from PIL import ImageDraw, ImageFont, ImageGrab

ROOT = Path(r"C:\Users\Administrator\Documents\Trae-CN\temp_20261122_02")
sys.path.insert(0, str(ROOT))

import tkinter as tk

import DeskTidy.simple as simple
from DeskTidy.__main__ import Shell

OUT_DIR = ROOT / "演示视频"
FRAME_DIR = Path(os.environ["TEMP"]) / "desktidy_frames"
OUT_FILE = OUT_DIR / "DeskTidy-演示视频.mp4"
CAPTION_FONT = r"C:\Windows\Fonts\msyh.ttc"

CAPTIONS = [
    (0.0, "桌面图标越堆越多，逐个归类只能靠手动拖拽"),
    (4.0, "DeskTidy · 免安装的 Windows 桌面整理工具"),
    (7.6, "一个主按钮：点一下，先给出整理预览"),
    (11.6, "预览列出每个文件将被放进哪个分类文件夹"),
    (15.2, "勾选「演练模式」：只预览，不改动任何文件"),
    (19.4, "确认后执行，并自动生成 CSV 整理报告"),
    (23.2, "演练结束：没有任何文件被移动"),
    (30.2, "演示排布：先取消「创建分类文件夹」"),
    (31.6, "排列方式一：顶部横向"),
    (35.8, "排列方式二：倒 L 型"),
    (40.0, "排列方式三：左侧竖向"),
    (42.8, "排布只调整图标位置，不移动任何文件"),
    (45.6, "排布前自动保存快照，可一键恢复原布局"),
    (49.6, "常用应用保留在桌面，也可以自己勾选"),
    (53.2, "纯本地运行 · 不联网 · 可预览 · 可撤销"),
    (56.6, "开源地址 github.com/Kedah-boya/DeskTidy"),
]
TOTAL = 60.0

state = {"cursor": (-100, -100), "t0": 0.0}
frames: list[Path] = []
stop_flag = threading.Event()
hidden: list[int] = []

user32 = ctypes.windll.user32


# ---------------- 窗口管理 ----------------
def minimize_others(keep_pid: int) -> None:
    """把与演示无关的可见顶层窗口最小化，结束后可恢复。"""
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == keep_pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if title in ("Program Manager", "任务栏", "Taskbar"):
            return True
        if user32.GetWindowLongW(hwnd, -16) & 0x00C00000:  # 有标题栏
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            hidden.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(callback), 0)


def restore_windows() -> None:
    for hwnd in hidden:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE


def move_cursor(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    state["cursor"] = (int(x), int(y))


def cursor_to(widget) -> None:
    widget.update_idletasks()
    move_cursor(widget.winfo_rootx() + widget.winfo_width() // 2,
                widget.winfo_rooty() + widget.winfo_height() // 2)


def walk(widget):
    yield widget
    try:
        children = widget.winfo_children()
    except tk.TclError:
        return
    for child in children:
        yield from walk(child)


def find(widget, text, prefix=False):
    for w in walk(widget):
        label = ""
        try:
            label = str(w.cget("text"))
        except Exception:
            pass
        if not label:
            try:
                var = str(w.cget("textvariable"))
                if var:
                    label = str(widget.getvar(var))
            except Exception:
                label = ""
        if (prefix and label.startswith(text)) or label == text:
            return w
    return None


def dialog(root):
    for w in walk(root):
        if isinstance(w, tk.Toplevel):
            try:
                if w.winfo_exists():
                    return w
            except tk.TclError:
                continue
    return None


# ---------------- 录制 ----------------
def caption_at(elapsed: float) -> str:
    text = ""
    for start, value in CAPTIONS:
        if elapsed >= start:
            text = value
    return text


def draw_overlay(img, elapsed: float):
    draw = ImageDraw.Draw(img, "RGBA")
    width, height = img.size

    cx, cy = state["cursor"]
    if cx > 0:
        sx, sy = cx * width / 1920, cy * height / 1080
        points = [(0, 0), (0, 17), (4, 13), (7, 19), (9, 18), (6, 12), (11, 12)]
        draw.polygon([(sx + x * 1.6, sy + y * 1.6) for x, y in points],
                     fill=(255, 255, 255, 250), outline=(25, 25, 25, 240))

    text = caption_at(elapsed)
    if not text:
        return img
    font = ImageFont.truetype(CAPTION_FONT, 30)
    tw = draw.textlength(text, font=font)
    box_w, box_h = tw + 64, 62
    x1 = (width - box_w) / 2
    y1 = height - box_h - 34
    draw.rounded_rectangle([x1, y1, x1 + box_w, y1 + box_h], radius=14,
                           fill=(15, 17, 24, 200))
    draw.text((x1 + 32, y1 + 12), text, font=font, fill=(255, 255, 255, 252))
    return img


def capture_loop(start: float) -> None:
    index = 0
    while not stop_flag.is_set():
        tick = time.perf_counter()
        try:
            img = ImageGrab.grab().resize((1280, 720), 1)
            img = draw_overlay(img, tick - start)
            path = FRAME_DIR / ("f%05d.jpg" % index)
            img.save(path, quality=88)
            frames.append(path)
            index += 1
        except Exception:
            pass
        wait = 1.0 / 15 - (time.perf_counter() - tick)
        if wait > 0:
            time.sleep(wait)


def main() -> None:
    if FRAME_DIR.exists():
        shutil.rmtree(FRAME_DIR)
    FRAME_DIR.mkdir(parents=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_FILE.exists():
        OUT_FILE.unlink()

    simple.messagebox.askyesno = lambda *a, **k: False
    simple.messagebox.showinfo = lambda *a, **k: None

    root = Shell()
    view = root.view
    root.withdraw()
    root.update()
    root.geometry("+1010+130")  # 放到右下方，让顶部一行与左侧一列的图标保持可见

    minimize_others(os.getpid())
    time.sleep(0.5)

    start = time.perf_counter()
    state["t0"] = start
    recorder = threading.Thread(target=capture_loop, args=(start,), daemon=True)
    recorder.start()

    def at(seconds: float, fn, tag: str = "") -> None:
        def run():
            try:
                fn()
            except Exception as exc:  # 记录失败，避免中断整段录制
                with (ROOT / "demo" / "record.log").open("a", encoding="utf-8") as fh:
                    fh.write("[%.1fs] %s -> %r\n" % (seconds, tag or fn, exc))
        root.after(int(seconds * 1000), run)

    main_btn = lambda: find(view, "一键整理")

    # 起点：桌面
    at(3.4, lambda: (root.deiconify(), root.lift(),
                     root.attributes("-topmost", True)))

    at(7.8, lambda: cursor_to(main_btn()))
    at(8.8, lambda: main_btn().invoke())

    # 预览弹窗：勾选演练模式
    done = {"dry": False, "start": False}

    def arm_dry(tries: int = 40) -> None:
        win = dialog(root)
        box = find(win, "演练模式", prefix=True) if win is not None else None
        if box is None:
            if tries > 0:
                root.after(120, lambda: arm_dry(tries - 1))
            return
        cursor_to(box)
        root.after(500, lambda: (not done["dry"]) and _toggle(box))

    def _toggle(box) -> None:
        try:
            box.invoke()
            done["dry"] = True
        except tk.TclError:
            pass

    at(15.2, arm_dry)

    def arm_confirm(tries: int = 40) -> None:
        win = dialog(root)
        btn = find(win, "开始整理") if win is not None else None
        if btn is None:
            if tries > 0:
                root.after(120, lambda: arm_confirm(tries - 1))
            return
        cursor_to(btn)
        root.after(600, lambda: (not done["start"]) and _confirm(btn))

    def _confirm(btn) -> None:
        try:
            btn.invoke()
            done["start"] = True
        except tk.TclError:
            pass

    at(18.6, arm_confirm)

    # 排布演示：取消建文件夹后依次切换
    at(26.6, lambda: cursor_to(find(view, "创建分类文件夹")))
    at(27.2, lambda: find(view, "创建分类文件夹").invoke())

    def layout(name: str, t: float) -> None:
        """点选排布方式并执行，执行后把窗口移出屏幕，让观众看清桌面变化。"""
        at(t - 0.8, lambda: cursor_to(find(view, name)))
        at(t - 0.2, lambda: find(view, name).invoke())
        at(t + 0.3, lambda: cursor_to(main_btn()))
        at(t + 0.8, lambda: main_btn().invoke())
        at(t + 1.1, lambda: root.geometry("+3000+130"))
        at(t + 3.2, lambda: (root.geometry("+1010+130"), root.lift(),
                             root.attributes("-topmost", True)))

    layout("顶部横向", 31.0)
    layout("倒L型", 35.2)
    layout("左侧竖向", 39.4)

    at(45.6, lambda: cursor_to(find(view, "恢复布局")))
    at(46.2, lambda: find(view, "恢复布局").invoke())

    at(49.4, lambda: cursor_to(find(view, "常用应用", prefix=True)))
    at(50.0, lambda: find(view, "常用应用", prefix=True).invoke())

    def arm_cancel(tries: int = 30) -> None:
        win = dialog(root)
        btn = find(win, "取消") if win is not None else None
        if btn is None:
            if tries > 0:
                root.after(120, lambda: arm_cancel(tries - 1))
            return
        cursor_to(btn)
        root.after(500, lambda: _cancel(btn))

    def _cancel(btn) -> None:
        try:
            btn.invoke()
        except tk.TclError:
            pass

    at(53.0, arm_cancel)

    def finish() -> None:
        stop_flag.set()
        time.sleep(0.3)
        root.destroy()

    at(TOTAL, finish)
    try:
        root.mainloop()
    finally:
        restore_windows()

    recorder.join(timeout=3)
    if not frames:
        raise SystemExit("没有抓到任何帧")

    elapsed = time.perf_counter() - start
    fps = max(6.0, min(20.0, len(frames) / max(elapsed, 1)))
    print("frames:", len(frames), "elapsed:", round(elapsed, 1), "fps:", round(fps, 2))

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([
        ffmpeg, "-y", "-framerate", "%.3f" % fps,
        "-i", str(FRAME_DIR / "f%05d.jpg"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(OUT_FILE),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.rmtree(FRAME_DIR, ignore_errors=True)
    print("video:", OUT_FILE, round(OUT_FILE.stat().st_size / 1024 / 1024, 2), "MB")


if __name__ == "__main__":
    main()
