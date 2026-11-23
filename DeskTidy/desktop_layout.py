# -*- coding: utf-8 -*-
"""直接排布桌面图标位置（不移动文件）。

通过 Shell 的桌面 SysListView32 读取每个图标的名称，再按类别顺序
把图标摆放到「倒 L 型 / 顶部横向 / 左侧竖向」的网格坐标上。

注意：需要关闭桌面的「自动排列图标」，否则系统会立刻重排。
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_size_t, c_ssize_t, c_uint, c_void_p, wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _ensure_dpi_aware() -> None:
    """保证网格计算与桌面窗口坐标使用同一套物理像素。"""
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.GetProcessDpiAwareness.argtypes = [c_void_p, POINTER(ctypes.c_int)]
        shcore.GetProcessDpiAwareness.restype = ctypes.c_long
        awareness = ctypes.c_int(0)
        if shcore.GetProcessDpiAwareness(None, byref(awareness)) == 0 and awareness.value == 0:
            user32.SetProcessDPIAware()
    except Exception:
        pass


_ensure_dpi_aware()

LVM_GETITEMCOUNT = 0x1004
LVM_GETITEMTEXTW = 0x1073
LVM_GETITEMPOSITION = 0x1010
LVM_SETITEMPOSITION = 0x100F
LVM_GETITEMSPACING = 0x1033
LVIF_TEXT = 0x0001

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

LAYOUTS = {
    "l": "倒L型",
    "top": "顶部横向",
    "left": "左侧竖向",
}


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", c_uint),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", c_uint),
        ("stateMask", c_uint),
        ("pszText", c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", c_ssize_t),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", c_uint),
        ("puColumns", c_void_p),
        ("piColFmt", c_void_p),
        ("iGroup", ctypes.c_int),
    ]


user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, c_size_t, c_ssize_t]
user32.SendMessageW.restype = c_ssize_t
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClientRect.argtypes = [wintypes.HWND, POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.InvalidateRect.argtypes = [wintypes.HWND, c_void_p, wintypes.BOOL]
user32.EnumWindows.argtypes = [c_void_p, wintypes.LPARAM]

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, c_void_p, c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = c_void_p
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, c_void_p, c_size_t, wintypes.DWORD]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, c_void_p, c_void_p, c_size_t,
                                        POINTER(c_size_t)]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, c_void_p, c_void_p, c_size_t,
                                       POINTER(c_size_t)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def find_desktop_listview() -> int | None:
    progman = user32.FindWindowW("Progman", None)
    if progman:
        view = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
        if view:
            listview = user32.FindWindowExW(view, None, "SysListView32", None)
            if listview:
                return listview

    found: list[int] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _param):
        view = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
        if view:
            listview = user32.FindWindowExW(view, None, "SysListView32", None)
            if listview:
                found.append(listview)
                return False
        return True

    user32.EnumWindows(proto(callback), 0)
    return found[0] if found else None


def _open_process(hwnd: int):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    handle = kernel32.OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE,
                                  False, pid.value)
    return handle, pid.value


def read_icons() -> list[tuple[int, str]]:
    """返回 [(列表索引, 图标显示名)]，只读，不改任何位置。"""
    hwnd = find_desktop_listview()
    if not hwnd:
        raise OSError("找不到桌面图标窗口，请确认资源管理器正在运行")
    count = int(user32.SendMessageW(hwnd, LVM_GETITEMCOUNT, 0, 0))
    if count <= 0:
        return []

    handle, _pid = _open_process(hwnd)
    if not handle:
        raise OSError("无法访问资源管理器进程（请以普通权限运行本工具）")

    size = ctypes.sizeof(LVITEMW)
    buffer_size = size + 640
    remote = kernel32.VirtualAllocEx(handle, None, buffer_size, MEM_COMMIT | MEM_RESERVE,
                                     PAGE_READWRITE)
    icons: list[tuple[int, str]] = []
    try:
        text_addr = ctypes.c_void_p(remote + size)
        written = c_size_t(0)
        for index in range(count):
            item = LVITEMW()
            item.mask = LVIF_TEXT
            item.iItem = index
            item.pszText = text_addr
            item.cchTextMax = 260
            kernel32.WriteProcessMemory(handle, ctypes.c_void_p(remote), byref(item), size,
                                        byref(written))
            length = int(user32.SendMessageW(hwnd, LVM_GETITEMTEXTW, index, remote))
            if length <= 0:
                icons.append((index, ""))
                continue
            buf = ctypes.create_unicode_buffer(260)
            read = c_size_t(0)
            kernel32.ReadProcessMemory(handle, text_addr, buf, 520, byref(read))
            icons.append((index, buf.value))
    finally:
        kernel32.VirtualFreeEx(handle, ctypes.c_void_p(remote), 0, MEM_RELEASE)
        kernel32.CloseHandle(handle)
    return icons


def read_positions() -> dict[int, tuple[int, int]]:
    """读取每个图标当前坐标（列表索引 -> (x, y)）。"""
    hwnd = find_desktop_listview()
    if not hwnd:
        raise OSError("找不到桌面图标窗口，请确认资源管理器正在运行")
    count = int(user32.SendMessageW(hwnd, LVM_GETITEMCOUNT, 0, 0))
    handle, _pid = _open_process(hwnd)
    if not handle:
        raise OSError("无法访问资源管理器进程（请以普通权限运行本工具）")
    remote = kernel32.VirtualAllocEx(handle, None, 4096, MEM_COMMIT | MEM_RESERVE,
                                     PAGE_READWRITE)
    positions: dict[int, tuple[int, int]] = {}
    written = c_size_t(0)
    read = c_size_t(0)
    try:
        for index in range(count):
            point = wintypes.POINT(0, 0)
            kernel32.WriteProcessMemory(handle, ctypes.c_void_p(remote), byref(point),
                                        ctypes.sizeof(point), byref(written))
            user32.SendMessageW(hwnd, LVM_GETITEMPOSITION, index, remote)
            result = wintypes.POINT()
            kernel32.ReadProcessMemory(handle, ctypes.c_void_p(remote), byref(result),
                                       ctypes.sizeof(result), byref(read))
            positions[index] = (result.x, result.y)
    finally:
        kernel32.VirtualFreeEx(handle, ctypes.c_void_p(remote), 0, MEM_RELEASE)
        kernel32.CloseHandle(handle)
    return positions


def apply_positions(positions: dict[int, tuple[int, int]]) -> int:
    """把指定坐标写回图标（用于还原原始布局）。"""
    hwnd = find_desktop_listview()
    if not hwnd:
        raise OSError("找不到桌面图标窗口，请确认资源管理器正在运行")
    for index, (x, y) in positions.items():
        user32.SendMessageW(hwnd, LVM_SETITEMPOSITION, index,
                            ((y & 0xFFFF) << 16) | (x & 0xFFFF))
    user32.InvalidateRect(hwnd, None, True)
    return len(positions)


def _grid(hwnd: int) -> tuple[int, int, int, int]:
    spacing = int(user32.SendMessageW(hwnd, LVM_GETITEMSPACING, 0, 0))
    step_x = spacing & 0xFFFF
    step_y = (spacing >> 16) & 0xFFFF
    if step_x < 40:
        step_x = 100
    if step_y < 40:
        step_y = 100

    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, byref(rect))
    columns = max(1, rect.right // step_x)
    rows = max(1, rect.bottom // step_y)
    return step_x, step_y, columns, rows


def _coordinates(layout: str, step_x: int, step_y: int,
                 columns: int, rows: int) -> list[tuple[int, int]]:
    if layout == "top":
        return [(c * step_x, r * step_y) for r in range(rows) for c in range(columns)]
    if layout == "left":
        return [(c * step_x, r * step_y) for c in range(columns) for r in range(rows)]

    coords = [(c * step_x, 0) for c in range(columns)]
    coords += [(0, r * step_y) for r in range(1, rows)]
    coords += [(c * step_x, r * step_y) for c in range(1, columns) for r in range(1, rows)]
    return coords


def arrange(ordered_names: list[str], layout: str = "l",
            ignore_unmatched: bool = False) -> tuple[int, list[str]]:
    """按 ordered_names 的顺序摆放图标。

    ignore_unmatched=True 时只移动名单里的图标，其他图标（文件夹、系统图标等）
    保持原位，且它们占用的格子会被跳过。

    返回 (已摆放到位的数量, 提示信息)。只改图标位置，不移动文件。
    """
    hwnd = find_desktop_listview()
    if not hwnd:
        raise OSError("找不到桌面图标窗口，请确认资源管理器正在运行")

    icons = read_icons()
    if not icons:
        return 0, ["桌面上没有图标"]

    by_name: dict[str, int] = {}
    for index, label in icons:
        if label:
            by_name.setdefault(label.casefold(), index)

    used: set[int] = set()
    sequence: list[int] = []
    missing: list[str] = []
    for name in ordered_names:
        key = (name or "").casefold()
        index = by_name.get(key)
        if index is None or index in used:
            missing.append(name)
            continue
        used.add(index)
        sequence.append(index)
    if not ignore_unmatched:
        for index, _label in icons:
            if index not in used:
                sequence.append(index)

    step_x, step_y, columns, rows = _grid(hwnd)
    coords = _coordinates(layout, step_x, step_y, columns, rows)
    if ignore_unmatched:
        occupied = set()
        for index, (x, y) in read_positions().items():
            if index not in used:
                occupied.add((int(round(x / step_x)), int(round(y / step_y))))
        coords = [(x, y) for x, y in coords
                  if (int(round(x / step_x)), int(round(y / step_y))) not in occupied]

    moved = 0
    for index, (x, y) in zip(sequence, coords):
        user32.SendMessageW(hwnd, LVM_SETITEMPOSITION, index, (y << 16) | (x & 0xFFFF))
        moved += 1
    user32.InvalidateRect(hwnd, None, True)

    notes: list[str] = []
    if missing:
        notes.append("%d 个名称未匹配到桌面图标" % len(missing))
    return moved, notes
