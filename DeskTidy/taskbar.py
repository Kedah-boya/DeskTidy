# -*- coding: utf-8 -*-
"""任务栏透明一键开关（纯系统接口，不依赖第三方软件）。

做法：给 Shell_TrayWnd / Shell_SecondaryTrayWnd 加 WS_EX_LAYERED 并设置
整体透明度。任务栏背景与图标会一起变成半透明，效果立即生效、无需重启。
资源管理器重启后需要重新点一次。
"""
from __future__ import annotations

import ctypes
from ctypes import c_int, c_ssize_t, c_ubyte, wintypes

import winreg

ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002
DEFAULT_ALPHA = 170  # 0 全透明 / 255 不透明

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, c_int]
user32.GetWindowLongPtrW.restype = c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, c_int, c_ssize_t]
user32.SetWindowLongPtrW.restype = c_ssize_t
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, c_ubyte,
                                              wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL


def _tray_windows() -> list[int]:
    handles: list[int] = []
    main = user32.FindWindowW("Shell_TrayWnd", None)
    if main:
        handles.append(main)
    secondary = user32.FindWindowExW(None, None, "Shell_SecondaryTrayWnd", None)
    while secondary:
        handles.append(secondary)
        secondary = user32.FindWindowExW(None, secondary, "Shell_SecondaryTrayWnd", None)
    return handles


def _write_dword(path: str, name: str, value: int) -> None:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
    except OSError:
        pass


def layered_active() -> bool:
    for handle in _tray_windows():
        style = user32.GetWindowLongPtrW(handle, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            return True
    return False


def apply_transparency(alpha: int = DEFAULT_ALPHA) -> int:
    """把任务栏设成半透明，返回生效的任务栏数量。"""
    alpha = max(0, min(255, int(alpha)))
    count = 0
    for handle in _tray_windows():
        style = user32.GetWindowLongPtrW(handle, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(handle, GWL_EXSTYLE, style | WS_EX_LAYERED)
        if user32.SetLayeredWindowAttributes(handle, 0, alpha, LWA_ALPHA):
            count += 1
    # 同步打开系统「透明效果」，避免任务栏底色变实心
    _write_dword(PERSONALIZE, "EnableTransparency", 1)
    return count


def clear_transparency() -> int:
    count = 0
    for handle in _tray_windows():
        style = user32.GetWindowLongPtrW(handle, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            user32.SetWindowLongPtrW(handle, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            count += 1
    return count


def set_transparency(enabled: bool, alpha: int = DEFAULT_ALPHA) -> str:
    if enabled:
        count = apply_transparency(alpha)
        if not count:
            raise OSError("没有找到任务栏窗口，请确认资源管理器正在运行")
        return "已开启任务栏透明（背景与图标半透明，立即生效）"
    clear_transparency()
    return "已关闭任务栏透明，恢复系统默认外观"
