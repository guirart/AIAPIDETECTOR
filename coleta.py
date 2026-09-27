"""Coleta automática de fotos da câmera para treinar o modelo próprio.

Salva a imagem ORIGINAL (sem caixas desenhadas) em dataset/fotos_novas/AAAA-MM-DD/:
  - quando há alguém na imagem, no máximo 1 foto a cada `intervalo_s` segundos;
  - de vez em quando, uma foto SEM ninguém (ensina o modelo que latas/tonéis não são gente).

As fotos mostram funcionários: a pasta dataset/ não vai para o GitHub (.gitignore).
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2

TIPOS_PESSOA = {"pessoa", "sem_capacete", "sem_colete"}


def _nome_arquivo(texto):
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-") or "camera"


class Coletor:
    def __init__(self, cfg, camera):
        cfg = cfg or {}
        self.ativa = bool(cfg.get("ativa", False))
        self.pasta = Path(cfg.get("pasta", "dataset/fotos_novas"))
        self.intervalo_s = float(cfg.get("intervalo_s", 10))
        self.vazia_a_cada_s = float(cfg.get("sem_pessoa_a_cada_s", 600))
        self.limite_dia = int(cfg.get("limite_por_dia", 500))
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

    def talvez_salvar(self, quadro, deteccoes, agora):
        """Chamado a cada análise. `agora` = relógio do monitor (segundos). Devolve o arquivo salvo ou None."""
        if not self.ativa or quadro is None:
            return None
        pasta = self._pasta_do_dia()
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

        agora_txt = datetime.now().strftime("%H%M%S_%f")[:-3]  # hora + milissegundos
        arquivo = pasta / f"{self.camera}_{agora_txt}_{'pessoa' if com_pessoa else 'vazia'}.jpg"
        ok, jpg = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            return None
        arquivo.write_bytes(jpg.tobytes())  # write_bytes: cv2.imwrite falha em caminhos com acento
        self.hoje += 1
        return arquivo
