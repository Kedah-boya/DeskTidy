# -*- coding: utf-8 -*-
"""读取 Windows 快捷方式(.lnk)与网址文件(.url)指向的真实目标。

.lnk 通过 Shell 的 IShellLinkW COM 接口解析，等价于资源管理器里
"属性 -> 目标" 显示的内容。
"""
from __future__ import annotations

import configparser
import ctypes
from ctypes import POINTER, byref, c_void_p, c_int, c_ulong, c_wchar_p
from pathlib import Path

ole32 = ctypes.WinDLL("ole32")

CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
IID_IPersistFile = "{0000010B-0000-0000-C000-000000000046}"

CLSCTX_INPROC_SERVER = 0x1
STGM_READ = 0x0
COINIT_APARTMENTTHREADED = 0x2


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


ole32.CLSIDFromString.argtypes = [c_wchar_p, POINTER(GUID)]
ole32.CLSIDFromString.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [
    POINTER(GUID), c_void_p, ctypes.c_ulong, POINTER(GUID), POINTER(c_void_p)
]
ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoInitializeEx.argtypes = [c_void_p, ctypes.c_ulong]
ole32.CoInitializeEx.restype = ctypes.c_long


def _guid(text: str) -> GUID:
    g = GUID()
    if ole32.CLSIDFromString(text, byref(g)) != 0:
        raise OSError("无法解析 GUID: %s" % text)
    return g


def _method(ptr: c_void_p, index: int, restype, argtypes):
    """取出 COM 对象虚表第 index 个方法。"""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(vtable[index])


def _release(ptr: c_void_p) -> None:
    try:
        _method(ptr, 2, c_ulong, [])(ptr)
    except Exception:
        pass


def _co_init() -> None:
    # 已在 STA 线程中时返回 S_FALSE，忽略即可
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)


def resolve_lnk(path: Path) -> dict:
    """返回 {'target', 'args', 'workdir', 'icon'}；失败抛异常。"""
    _co_init()
    punk = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(_guid(CLSID_ShellLink)), None, CLSCTX_INPROC_SERVER,
        byref(_guid(IID_IShellLinkW)), byref(punk),
    )
    if hr != 0 or not punk:
        raise OSError("CoCreateInstance 失败 hr=0x%08X" % (hr & 0xFFFFFFFF))

    persist = c_void_p()
    try:
        query = _method(punk, 0, ctypes.c_long, [POINTER(GUID), POINTER(c_void_p)])
        if query(punk, byref(_guid(IID_IPersistFile)), byref(persist)) != 0 or not persist:
            raise OSError("获取 IPersistFile 失败")
        load = _method(persist, 5, ctypes.c_long, [c_wchar_p, c_ulong])
        if load(persist, str(path), STGM_READ) != 0:
            raise OSError("读取快捷方式失败")

        get_path = _method(punk, 3, ctypes.c_long,
                           [c_wchar_p, c_int, c_void_p, c_ulong])
        buf = ctypes.create_unicode_buffer(1024)
        get_path(punk, buf, 1024, None, 0)

        get_args = _method(punk, 10, ctypes.c_long, [c_wchar_p, c_int])
        abuf = ctypes.create_unicode_buffer(1024)
        get_args(punk, abuf, 1024)

        get_wd = _method(punk, 8, ctypes.c_long, [c_wchar_p, c_int])
        wbuf = ctypes.create_unicode_buffer(1024)
        get_wd(punk, wbuf, 1024)

        get_icon = _method(punk, 16, ctypes.c_long,
                           [c_wchar_p, c_int, POINTER(c_int)])
        ibuf = ctypes.create_unicode_buffer(1024)
        idx = c_int(0)
        get_icon(punk, ibuf, 1024, byref(idx))

        return {
            "target": buf.value,
            "args": abuf.value,
            "workdir": wbuf.value,
            "icon": ibuf.value,
        }
    finally:
        if persist:
            _release(persist)
        _release(punk)


def resolve_url(path: Path) -> str:
    """读取 .url 文件里的 URL 字段。"""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in raw.splitlines():
        line = line.strip()
        if line.lower().startswith("url="):
            return line[4:].strip()
    parser = configparser.ConfigParser()
    try:
        parser.read_string(raw)
        for section in parser.sections():
            if parser.has_option(section, "URL"):
                return parser.get(section, "URL")
    except Exception:
        pass
    return ""


def resolve(path: Path) -> dict:
    """统一入口：任何文件都返回目标信息（非快捷方式时 target 为自身）。"""
    suffix = path.suffix.lower()
    if suffix == ".lnk":
        try:
            info = resolve_lnk(path)
            info["kind"] = "快捷方式"
            return info
        except Exception as exc:  # 损坏或权限问题，降级处理
            return {"target": "", "args": "", "workdir": "",
                    "icon": "", "kind": "快捷方式", "error": str(exc)}
    if suffix == ".url":
        return {"target": resolve_url(path), "args": "", "workdir": "",
                "icon": "", "kind": "网址"}
    kind = "程序" if suffix in {".exe", ".bat", ".cmd", ".msi", ".ps1"} else ""
    return {"target": str(path), "args": "", "workdir": "", "icon": "", "kind": kind}
