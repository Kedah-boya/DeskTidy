# -*- coding: utf-8 -*-
"""用 Windows Shell 提取真实文件图标，转成 Tk 可用的 PhotoImage。

流程：SHGetFileInfoW 取 HICON -> DrawIconEx 画进 32 位 DIB
-> 转 PNG(base64) 交给 Tk。失败时退回按类别着色的方块图标。
"""
from __future__ import annotations

import base64
import ctypes
import struct
import zlib
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_USEFILEATTRIBUTES = 0x000000010
FILE_ATTRIBUTE_NORMAL = 0x80
DI_NORMAL = 0x0003
DIB_RGB_COLORS = 0
BI_RGB = 0


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT,
                              wintypes.HBRUSH, wintypes.UINT]
user32.DrawIconEx.restype = wintypes.BOOL
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO),
                                    wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                    wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH

shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.POINTER(SHFILEINFOW),
                                   wintypes.UINT, wintypes.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_void_p

BG = (245, 246, 248)


def _hicon_for(path: Path):
    info = SHFILEINFOW()
    flags = SHGFI_ICON | SHGFI_LARGEICON
    hresult = shell32.SHGetFileInfoW(str(path), FILE_ATTRIBUTE_NORMAL,
                                     ctypes.byref(info), ctypes.sizeof(info), flags)
    if not hresult or not info.hIcon:
        flags |= SHGFI_USEFILEATTRIBUTES
        hresult = shell32.SHGetFileInfoW(path.suffix or ".txt", FILE_ATTRIBUTE_NORMAL,
                                         ctypes.byref(info), ctypes.sizeof(info), flags)
    return info.hIcon if hresult else None


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _rgb_to_png(width: int, height: int, rgb: bytes) -> bytes:
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        raw += rgb[y * stride:(y + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" +
            _png_chunk(b"IHDR", header) +
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)) +
            _png_chunk(b"IEND", b""))


def _hicon_to_png(hicon, size: int = 32) -> bytes:
    screen = user32.GetDC(None)
    memdc = gdi32.CreateCompatibleDC(screen)
    bmi = BITMAPINFO()
    header = bmi.bmiHeader
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = size
    header.biHeight = -size
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(memdc, bitmap)
    try:
        brush = gdi32.CreateSolidBrush(0x00F8F6F5)
        rect = wintypes.RECT(0, 0, size, size)
        user32.FillRect(memdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)
        user32.DrawIconEx(memdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        raw = ctypes.string_at(bits, size * size * 4)
    finally:
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, screen)

    rgb = bytearray()
    for index in range(0, len(raw), 4):
        b, g, r, a = raw[index], raw[index + 1], raw[index + 2], raw[index + 3]
        if a >= 250:
            rgb += bytes((r, g, b))
        elif a == 0:
            rgb += bytes(BG)
        else:
            rgb += bytes((
                (r * a + BG[0] * (255 - a)) // 255,
                (g * a + BG[1] * (255 - a)) // 255,
                (b * a + BG[2] * (255 - a)) // 255,
            ))
    return _rgb_to_png(size, size, bytes(rgb))


def fallback_icon(master, color: str = "#7a7f8c", size: int = 32):
    import tkinter as tk
    img = tk.PhotoImage(master=master, width=size, height=size)
    img.put("#f5f6f8", to=(0, 0, size, size))
    edge = max(2, size // 6)
    img.put(color, to=(edge, edge, size - edge, size - edge))
    img.put("#ffffff", to=(size // 2 - edge // 2, size // 2 - edge // 2,
                           size // 2 + edge // 2, size // 2 + edge // 2))
    return img


def get_icon(master, path: Path, color: str = "#7a7f8c", size: int = 32):
    """取不到真实图标时返回 None，由调用方决定降级方案。"""
    hicon = None
    try:
        hicon = _hicon_for(Path(path))
        if not hicon:
            return None
        png = _hicon_to_png(hicon, size)
        data = base64.b64encode(png).decode("ascii")
        import tkinter as tk
        return tk.PhotoImage(master=master, data=data)
    except Exception:
        return None
    finally:
        if hicon:
            user32.DestroyIcon(hicon)
