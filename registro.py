"""Registro das infrações: banco SQLite + foto de evidência."""
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2

NOMES_EPI = {"capacete": "Capacete", "colete": "Colete refletivo"}


class Registro:
    def __init__(self, pasta, banco):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        Path(banco).parent.mkdir(parents=True, exist_ok=True)
        # criada na thread principal e usada pela thread de análise (uma de cada vez)
        # várias câmeras gravam no mesmo banco: timeout espera a vez em vez de dar "database is locked"
        self.conexao = sqlite3.connect(banco, check_same_thread=False, timeout=15)
        self.conexao.execute("""
            CREATE TABLE IF NOT EXISTS infracoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT NOT NULL,
                camera TEXT NOT NULL,
                pessoa_id INTEGER,
                epis_faltando TEXT NOT NULL,
                imagem TEXT NOT NULL
            )""")
        self.conexao.commit()

    def salvar(self, camera, situacao, quadro_anotado):
        agora = datetime.now()
        pasta_dia = self.pasta / agora.strftime("%Y-%m-%d")
        pasta_dia.mkdir(exist_ok=True)
        cam = re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFKD", camera).encode("ascii", "ignore").decode()).strip("-")
        imagem = pasta_dia / f"{agora:%H%M%S}_{cam or 'cam'}_{situacao.track_id or 0}.jpg"
        # imencode + write_bytes: cv2.imwrite falha em caminhos com acento no Windows
        ok, jpg = cv2.imencode(".jpg", quadro_anotado, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            imagem.write_bytes(jpg.tobytes())

        faltando = ", ".join(NOMES_EPI[e] for e in situacao.faltando)
        self.conexao.execute(
            "INSERT INTO infracoes (data_hora, camera, pessoa_id, epis_faltando, imagem) "
            "VALUES (?, ?, ?, ?, ?)",
            (agora.isoformat(timespec="seconds"), camera, situacao.track_id,
             faltando, str(imagem.resolve())))
        self.conexao.commit()
        return agora, faltando, imagem

    def fechar(self):
        self.conexao.close()
