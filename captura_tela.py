"""Fonte de vídeo a partir da TELA do PC (útil para testar com o celular espelhado).

No config.yaml, em "fonte":
    "janela:LonelyScreen"      -> captura a janela cujo título contém esse texto
    "tela"                     -> tela principal inteira
    "tela:100,80,1280,720"     -> região x,y,largura,altura da tela

A janela precisa estar VISÍVEL (não minimizada nem coberta por outra).
"""
import ctypes
import ctypes.wintypes
import threading
import time

import cv2
import numpy as np
from PIL import ImageGrab

QPS = 10  # quadros por segundo capturados


def _preparar_dpi():
    """Sem isso, em telas com zoom (125%, 150%) as coordenadas da janela saem erradas."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _configurar_gdi():
    """Tipos das funções do Windows: sem isso, os "handles" de 64 bits são truncados e a captura falha."""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    H = ctypes.c_void_p
    u.GetWindowDC.restype, u.GetWindowDC.argtypes = H, [H]
    u.ReleaseDC.argtypes = [H, H]
    u.PrintWindow.argtypes = [H, H, ctypes.c_uint]
    u.GetWindowRect.argtypes = [H, ctypes.POINTER(ctypes.wintypes.RECT)]
    g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = H, [H]
    g.CreateCompatibleBitmap.restype, g.CreateCompatibleBitmap.argtypes = H, [H, ctypes.c_int, ctypes.c_int]
    g.SelectObject.restype, g.SelectObject.argtypes = H, [H, H]
    g.DeleteObject.argtypes = [H]
    g.DeleteDC.argtypes = [H]
    g.GetDIBits.argtypes = [H, H, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def capturar_janela(hwnd):
    """Copia o conteúdo da janela mesmo que esteja ATRÁS de outras (PrintWindow). Devolve BGR ou None."""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    r = ctypes.wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    dc_janela = u.GetWindowDC(hwnd)
    dc_mem = g.CreateCompatibleDC(dc_janela)
    bmp = g.CreateCompatibleBitmap(dc_janela, w, h)
    antigo = g.SelectObject(dc_mem, bmp)
    try:
        if not u.PrintWindow(hwnd, dc_mem, 2):  # 2 = PW_RENDERFULLCONTENT (inclui vídeo/GPU)
            return None
        info = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = np.empty((h, w, 4), np.uint8)
        if not g.GetDIBits(dc_mem, bmp, 0, h, buf.ctypes.data, ctypes.byref(info), 0):
            return None
        return np.ascontiguousarray(buf[:, :, :3])
    finally:
        g.SelectObject(dc_mem, antigo)
        g.DeleteObject(bmp)
        g.DeleteDC(dc_mem)
        u.ReleaseDC(hwnd, dc_janela)


def achar_hwnd(texto):
    """(hwnd, título) da primeira janela visível (não minimizada) cujo título contém `texto`."""
    user32 = ctypes.windll.user32
    achadas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cada(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if texto.lower() in buf.value.lower():
                    achadas.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cada, 0)
    return achadas[0] if achadas else (None, None)


def achar_janela(texto):
    """Retorna (título, (x1, y1, x2, y2)) da primeira janela visível cujo título contém `texto`."""
    user32 = ctypes.windll.user32
    achadas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cada(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if texto.lower() in buf.value.lower():
                    achadas.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cada, 0)
    if not achadas:
        return None, None
    hwnd, titulo = achadas[0]
    ret = ctypes.wintypes.RECT()
    # borda real da janela (sem a sombra do Windows 10/11)
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(ret), ctypes.sizeof(ret)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(ret))
    return titulo, (ret.left, ret.top, ret.right, ret.bottom)


def aparar_bordas(img, limite=18):
    """Corta as faixas pretas em volta (celular espelhado em pé deixa barras dos lados)."""
    cinza = img.max(axis=2)
    linhas = np.where(cinza.max(axis=1) > limite)[0]
    colunas = np.where(cinza.max(axis=0) > limite)[0]
    if len(linhas) < 20 or len(colunas) < 20:
        return img
    return img[linhas[0]:linhas[-1] + 1, colunas[0]:colunas[-1] + 1]


class FonteTela:
    """Mesma interface da FonteAoVivo (ler, online, fechar)."""

    def __init__(self, alvo):
        _preparar_dpi()
        _configurar_gdi()
        self.alvo = alvo
        self.erro = None
        self._quadro, self._rodando, self.ultimo_ok = None, True, 0.0
        threading.Thread(target=self._capturar, daemon=True).start()

    def _regiao(self):
        tipo, _, resto = self.alvo.partition(":")
        if tipo == "janela":
            titulo, caixa = achar_janela(resto)
            if caixa is None:
                self.erro = f'Janela "{resto}" não encontrada (abra o espelhamento e deixe a janela visível)'
            return caixa
        if resto:  # tela:x,y,w,h
            x, y, w, h = (int(v) for v in resto.split(","))
            return (x, y, x + w, y + h)
        return None  # tela inteira

    def _capturar(self):
        while self._rodando:
            inicio = time.monotonic()
            try:
                quadro = None
                if self.alvo.startswith("janela:"):
                    # 1º: copia a janela direto (funciona mesmo atrás de outras janelas)
                    hwnd, _ = achar_hwnd(self.alvo.partition(":")[2])
                    if hwnd:
                        quadro = capturar_janela(hwnd)
                        if quadro is not None and quadro.max() < 10:  # app não suporta: veio tudo preto
                            quadro = None
                if quadro is None:
                    # 2º: fotografa a região da tela (a janela precisa estar visível)
                    caixa = self._regiao()
                    if self.alvo.startswith("janela:") and caixa is None:
                        time.sleep(1)
                        continue
                    img = ImageGrab.grab(bbox=caixa, all_screens=True)
                    quadro = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
                quadro = aparar_bordas(quadro)
                self._quadro, self.ultimo_ok, self.erro = quadro, time.monotonic(), None
            except Exception as e:  # tela bloqueada, janela fechando...
                self.erro = f"Falha ao capturar a tela: {e}"
                time.sleep(1)
            time.sleep(max(0.0, 1 / QPS - (time.monotonic() - inicio)))

    @property
    def online(self):
        return time.monotonic() - self.ultimo_ok < 5

    def ler(self):
        return self._quadro, time.monotonic()

    def fechar(self):
        self._rodando = False
