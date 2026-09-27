"""Tela web do Monitor de EPI: vídeo ao vivo, status e infrações registradas.

Uso:
    python painel.py                  # abre http://localhost:8080 no navegador
    python painel.py --fonte video.mp4
"""
import argparse
import json
import mimetypes
import os
import sqlite3
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from monitor import PASTA, Monitor, carregar_config, criar_detector

ESTATICOS = PASTA / "painel"
LIMITE_LISTA = 200


class Painel(BaseHTTPRequestHandler):
    monitores: list = []
    banco: str = None

    def log_message(self, *args):  # sem log de cada requisição no console
        pass

    # ----- respostas
    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho, cache=True):
        if not caminho.is_file():
            return self._json({"erro": "não encontrado"}, 404)
        corpo = caminho.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(caminho.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-cache")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _consultar(self, sql, params=()):
        if not Path(self.banco).exists():
            return []
        con = sqlite3.connect(self.banco)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    # ----- rotas
    def do_GET(self):
        url = urlparse(self.path)
        rota = url.path
        try:
            if rota == "/api/status":
                return self._status()
            if rota == "/api/infracoes":
                return self._infracoes(parse_qs(url.query))
            if rota.startswith("/api/infracoes/") and rota.endswith("/foto"):
                return self._foto(rota.split("/")[3])
            if rota.startswith("/video/") and rota.endswith(".mjpg"):  # /video/0.mjpg, /video/1.mjpg...
                n = rota[len("/video/"):-len(".mjpg")]
                if n.isdigit() and int(n) < len(self.monitores):
                    return self._video(self.monitores[int(n)])
                return self._json({"erro": "câmera não encontrada"}, 404)
            nome = "index.html" if rota == "/" else rota.lstrip("/")
            alvo = (ESTATICOS / nome).resolve()
            if ESTATICOS.resolve() not in alvo.parents:  # impede sair da pasta painel/
                return self._json({"erro": "não encontrado"}, 404)
            return self._arquivo(alvo, cache=alvo.suffix == ".woff2")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # navegador fechou a conexão

    def _status(self):
        hoje = datetime.now().strftime("%Y-%m-%d")
        (total_hoje,), = self._consultar("SELECT COUNT(*) FROM infracoes WHERE data_hora >= ?", (hoje,)) or [(0,)]
        primeiro = self.monitores[0].estado
        self._json({"motor": primeiro["motor"], "epis": primeiro["epis"],
                    "tempo_minimo_s": primeiro["tempo_minimo_s"], "infracoes_hoje": total_hoje,
                    "hora": datetime.now().isoformat(timespec="seconds"),
                    "cameras": [m.estado for m in self.monitores]})

    def _infracoes(self, q):
        dias = int(q.get("dias", ["1"])[0])
        sql = "SELECT id, data_hora, camera, pessoa_id, epis_faltando FROM infracoes"
        params = []
        if dias > 0:
            inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dias - 1)
            sql += " WHERE data_hora >= ?"
            params.append(inicio.isoformat())
        total = self._consultar(sql.replace("id, data_hora, camera, pessoa_id, epis_faltando", "COUNT(*)"), params)
        linhas = self._consultar(sql + f" ORDER BY id DESC LIMIT {LIMITE_LISTA}", params)
        self._json({
            "total": total[0][0] if total else 0,
            "infracoes": [{"id": i, "data_hora": d, "camera": c, "pessoa_id": p,
                           "faltando": [f.strip() for f in faltando.split(",")]}
                          for i, d, c, p, faltando in linhas],
        })

    def _foto(self, id_texto):
        if not id_texto.isdigit():
            return self._json({"erro": "id inválido"}, 400)
        linha = self._consultar("SELECT imagem FROM infracoes WHERE id = ?", (int(id_texto),))
        if not linha:
            return self._json({"erro": "não encontrado"}, 404)
        self._arquivo(Path(linha[0][0]))

    def _video(self, monitor):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=quadro")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        jpeg = None
        while not monitor.parar.is_set():
            novo = monitor.aguardar_jpeg(jpeg)
            if novo is None or novo is jpeg:
                continue
            jpeg = novo
            self.wfile.write(b"--quadro\r\nContent-Type: image/jpeg\r\nContent-Length: "
                             + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")


def main():
    os.chdir(PASTA)
    ap = argparse.ArgumentParser(description="Tela web do Monitor de EPI")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--fonte", action="append",
                    help="sobrescreve a fonte das câmeras, na ordem (pode repetir: --fonte a.mp4 --fonte b.mp4)")
    ap.add_argument("--modelo", help="usa um modelo .pt local (ignora o motor do config)")
    ap.add_argument("--nao-abrir", action="store_true", help="não abre o navegador")
    args = ap.parse_args()

    cfg = carregar_config(args.config)
    painel_cfg = cfg.get("painel", {})
    host, porta = painel_cfg.get("host", "127.0.0.1"), painel_cfg.get("porta", 8080)
    cameras = cfg["cameras"]
    if args.fonte:  # teste com vídeos: --fonte define quantas câmeras e de onde vêm
        cameras = [{"id": i, "nome": cameras[i]["nome"] if i < len(cameras) else f"Câmera {i + 1}", "fonte": f}
                   for i, f in enumerate(args.fonte)]

    # um detector por câmera: cada uma tem o seu rastreamento (números #) independente
    monitores = []
    for cam in cameras:
        detectar_quadro, motor = criar_detector(cfg, args.modelo)
        monitores.append(Monitor(cfg, cam["fonte"], detectar_quadro, motor, cam["nome"], cam["id"],
                                 cam.get("recorte")))
    Painel.monitores = monitores
    Painel.banco = str(Path(cfg["registro"]["banco"]).resolve())
    servidor = ThreadingHTTPServer((host, porta), Painel)
    servidor.daemon_threads = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    endereco = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{porta}"
    print(f"Detecção: {motor} · {len(monitores)} câmera(s)")
    print(f"Tela aberta em {endereco}  (Ctrl+C para encerrar)")
    if not args.nao_abrir:
        webbrowser.open(endereco)
    threads = [threading.Thread(target=m.executar, kwargs={"publicar_jpeg": True}, daemon=True) for m in monitores]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
        print("Todas as câmeras encerraram. A tela continua aberta com o histórico (Ctrl+C para sair).")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for m in monitores:
            m.parar.set()
        servidor.shutdown()


if __name__ == "__main__":
    main()
