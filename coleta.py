"""Coleta de prints da câmera para treinar o modelo próprio de EPI.

Salva prints ORIGINAIS (sem caixas desenhadas) em <pasta>/AAAA-MM-DD/ — por padrão numa pasta
"Fotos treino EPI" na Área de Trabalho:
  - quando há alguém na imagem: no máximo 1 print a cada `intervalo_s` segundos (…_pessoa.jpg),
    e, se `recortar_pessoas`, também o recorte de cada pessoa em pessoas/ (para revisar rápido);
  - de vez em quando, um print SEM ninguém (…_vazia.jpg: ensina que latas/tonéis não são gente);
  - quando você aperta "Tirar print" na tela (…_manual.jpg), sem limite de intervalo.

As fotos mostram funcionários: não vão para o GitHub.
"""
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2

TIPOS_PESSOA = {"pessoa", "sem_capacete", "sem_colete"}
MARGEM_RECORTE = 0.15  # folga em volta da pessoa no recorte


def _nome_arquivo(texto):
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-") or "camera"


def area_de_trabalho():
    """Pasta real da Área de Trabalho (no Windows pode estar dentro do OneDrive)."""
    if os.name == "nt":
        import winreg
        try:
            chave = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as reg:
                return Path(os.path.expandvars(winreg.QueryValueEx(reg, "Desktop")[0]))
        except OSError:
            pass
    return Path.home() / "Desktop"


def resolver_pasta(texto):
    return Path(str(texto).replace("{AREA_DE_TRABALHO}", str(area_de_trabalho())))


def _gravar(arquivo, imagem, qualidade=95):
    ok, jpg = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if ok:
        arquivo.write_bytes(jpg.tobytes())  # write_bytes: cv2.imwrite falha em caminhos com acento
    return ok


class Coletor:
    def __init__(self, cfg, camera):
        cfg = cfg or {}
        self.ativa = bool(cfg.get("ativa", False))
        self.pasta = resolver_pasta(cfg.get("pasta", "{AREA_DE_TRABALHO}/Fotos treino EPI"))
        self.intervalo_s = float(cfg.get("intervalo_s", 10))
        self.vazia_a_cada_s = float(cfg.get("sem_pessoa_a_cada_s", 600))
        self.limite_dia = int(cfg.get("limite_por_dia", 500))
        self.recortar_pessoas = bool(cfg.get("recortar_pessoas", True))
        self.camera = _nome_arquivo(camera)
        self._ultima_com = self._ultima_sem = None
        self._dia, self.hoje = None, 0

    def _pasta_do_dia(self):
        dia = datetime.now().strftime("%Y-%m-%d")
        pasta = self.pasta / dia
        if dia != self._dia:  # virou o dia (ou primeira vez): recomeça a contagem
            self._dia = dia
            pasta.mkdir(parents=True, exist_ok=True)
            self.hoje = len(list(pasta.glob(f"{self.camera}_*.jpg")))
        return pasta

    def _salvar(self, quadro, deteccoes, tipo):
        pasta = self._pasta_do_dia()
        base = f"{self.camera}_{datetime.now().strftime('%H%M%S_%f')[:-3]}"
        arquivo = pasta / f"{base}_{tipo}.jpg"
        if not _gravar(arquivo, quadro):
            return None
        self.hoje += 1
        if self.recortar_pessoas:
            self._salvar_recortes(pasta, base, quadro, deteccoes)
        return arquivo

    def _salvar_recortes(self, pasta, base, quadro, deteccoes):
        h, w = quadro.shape[:2]
        pessoas = [d for d in deteccoes if d.tipo == "pessoa"]
        if not pessoas:
            return
        destino = pasta / "pessoas"
        destino.mkdir(exist_ok=True)
        for n, d in enumerate(pessoas, 1):
            x1, y1, x2, y2 = d.caixa
            mx, my = (x2 - x1) * MARGEM_RECORTE, (y2 - y1) * MARGEM_RECORTE
            x1, y1 = max(0, int(x1 - mx)), max(0, int(y1 - my))
            x2, y2 = min(w, int(x2 + mx)), min(h, int(y2 + my))
            if x2 - x1 >= 20 and y2 - y1 >= 20:
                _gravar(destino / f"{base}_pessoa{n}.jpg", quadro[y1:y2, x1:x2])

    def talvez_salvar(self, quadro, deteccoes, agora):
        """Chamado a cada análise. `agora` = relógio do monitor (segundos). Devolve o arquivo salvo ou None."""
        if not self.ativa or quadro is None:
            return None
        self._pasta_do_dia()
        if self.hoje >= self.limite_dia:
            return None
        com_pessoa = any(d.tipo in TIPOS_PESSOA for d in deteccoes)
        if com_pessoa:
            if self._ultima_com is not None and agora - self._ultima_com < self.intervalo_s:
                return None
            self._ultima_com = agora
        else:
            if self._ultima_sem is not None and agora - self._ultima_sem < self.vazia_a_cada_s:
                return None
            self._ultima_sem = agora
        return self._salvar(quadro, deteccoes, "pessoa" if com_pessoa else "vazia")

    def salvar_manual(self, quadro, deteccoes=()):
        """Botão "Tirar print" da tela: salva agora, mesmo com a coleta automática desligada."""
        if quadro is None:
            return None
        return self._salvar(quadro, list(deteccoes), "manual")
