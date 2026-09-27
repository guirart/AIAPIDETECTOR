"""Monitor de EPI - detecta pessoas sem capacete e/ou colete refletivo na câmera.

Uso:
    python monitor.py                         # usa o config.yaml
    python monitor.py --fonte videos/obra.mp4 # testa com um vídeo
    python monitor.py --fonte 0               # webcam
"""
import argparse
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml

from alertas import Alertas
from registro import NOMES_EPI, Registro
from regras import ControleTemporal, Deteccao, avaliar_quadro
from segredos import expandir, mascarar

# Câmeras IP (Tapo e outras): RTSP por TCP é bem mais estável que UDP em Wi-Fi
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

PASTA = Path(__file__).resolve().parent
VERDE, VERMELHO, AMARELO, BRANCO = (60, 180, 75), (40, 40, 230), (0, 200, 255), (255, 255, 255)
ROTULO = {"capacete": "SEM CAPACETE", "colete": "SEM COLETE"}


# ---------------------------------------------------------------- fonte de vídeo
class FonteAoVivo:
    """Webcam/RTSP: uma thread lê sem parar e guarda só o quadro mais recente (sem atraso acumulado)."""

    def __init__(self, fonte):
        self.fonte = fonte
        self._quadro, self._rodando = None, True
        self.ultimo_ok = 0.0  # instante (monotonic) do último quadro recebido
        self._cap = self._abrir()
        threading.Thread(target=self._ler, daemon=True).start()

    def _abrir(self):
        if isinstance(self.fonte, int) and os.name == "nt":
            return cv2.VideoCapture(self.fonte, cv2.CAP_DSHOW)
        return cv2.VideoCapture(self.fonte)

    def _ler(self):
        while self._rodando:
            ok, quadro = self._cap.read()
            if ok:
                self._quadro, self.ultimo_ok = quadro, time.monotonic()
            else:  # câmera caiu: tenta reconectar
                time.sleep(2)
                self._cap.release()
                self._cap = self._abrir()

    @property
    def online(self):
        return time.monotonic() - self.ultimo_ok < 5

    def ler(self):
        """Devolve o quadro mais recente (None enquanto a câmera não entregou nenhum)."""
        return self._quadro, time.monotonic()

    def fechar(self):
        self._rodando = False
        self._cap.release()


class FonteArquivo:
    """Vídeo gravado: lê quadro a quadro e usa o tempo do próprio vídeo nas regras."""

    online = True

    def __init__(self, caminho):
        self._cap = cv2.VideoCapture(caminho)
        if not self._cap.isOpened():
            sys.exit(f"Não consegui abrir o vídeo: {caminho}")

    def ler(self):
        ok, quadro = self._cap.read()
        return (quadro if ok else None), self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000

    def fechar(self):
        self._cap.release()


def abrir_fonte(fonte):
    if isinstance(fonte, int) or str(fonte).isdigit():
        return FonteAoVivo(int(fonte)), True
    if str(fonte).lower().startswith(("rtsp://", "http://", "https://")):
        return FonteAoVivo(str(fonte)), True
    if str(fonte).lower().startswith(("janela:", "tela")):  # tela do PC (ex.: celular espelhado)
        from captura_tela import FonteTela
        return FonteTela(str(fonte)), True
    return FonteArquivo(str(fonte)), False


# ---------------------------------------------------------------- detecção
def mapear_classes(nomes_modelo, config_classes):
    """id da classe do modelo -> tipo interno (pessoa, capacete, colete, sem_capacete, sem_colete)."""
    mapa = {}
    for tipo, aliases in config_classes.items():
        aliases = {a.lower() for a in aliases}
        for id_classe, nome in nomes_modelo.items():
            if nome.lower() in aliases:
                mapa[id_classe] = tipo
    return mapa


def detectar(modelo, quadro, mapa, cfg):
    resultado = modelo.track(quadro, persist=True, conf=cfg["confianca_minima"],
                             imgsz=cfg["tamanho_imagem"], tracker="bytetrack.yaml", verbose=False)[0]
    deteccoes = []
    b = resultado.boxes
    if b is None or len(b) == 0:
        return deteccoes
    ids = b.id.int().tolist() if b.id is not None else [None] * len(b)
    for caixa, cls, conf, tid in zip(b.xyxy.tolist(), b.cls.int().tolist(), b.conf.tolist(), ids):
        if cls in mapa:
            deteccoes.append(Deteccao(mapa[cls], tuple(caixa), conf, tid))
    return deteccoes


# ---------------------------------------------------------------- desenho
def desenhar(quadro, deteccoes, situacoes, camera, total_infracoes, alerta_ativo, cabecalho=True):
    img = quadro.copy()
    for d in deteccoes:
        if d.tipo in ("capacete", "colete"):
            x1, y1, x2, y2 = map(int, d.caixa)
            cv2.rectangle(img, (x1, y1), (x2, y2), AMARELO, 1)

    for s in situacoes:
        x1, y1, x2, y2 = map(int, s.caixa)
        cor = VERMELHO if s.faltando else VERDE
        texto = " / ".join(ROTULO[e] for e in s.faltando) if s.faltando else "OK"
        if s.track_id is not None:
            texto = f"#{s.track_id} {texto}"
        cv2.rectangle(img, (x1, y1), (x2, y2), cor, 2)
        (lt, at), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        xt = max(0, min(x1, img.shape[1] - lt - 8))  # não deixa o rótulo sair da imagem
        cv2.rectangle(img, (xt, max(0, y1 - at - 10)), (xt + lt + 8, y1), cor, -1)
        cv2.putText(img, texto, (xt + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, BRANCO, 2)

    h, w = img.shape[:2]
    if cabecalho:  # a tela web mostra essas informações fora do vídeo
        cv2.rectangle(img, (0, 0), (w, 34), (30, 30, 30), -1)
        irregulares = sum(1 for s in situacoes if s.faltando)
        info = (f"{camera} | {datetime.now():%d/%m/%Y %H:%M:%S} | Pessoas: {len(situacoes)} "
                f"| Irregulares: {irregulares} | Infracoes registradas: {total_infracoes}")
        cv2.putText(img, info, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, BRANCO, 1)

    if alerta_ativo:
        cv2.rectangle(img, (0, h - 50), (w, h), VERMELHO, -1)
        cv2.putText(img, f"ALERTA: {alerta_ativo}", (12, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, BRANCO, 2)
    return img


# ---------------------------------------------------------------- principal
def carregar_config(caminho):
    """Lê o config e normaliza as câmeras para cfg["cameras"] = [{id, nome, fonte}, ...]."""
    with open(caminho, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cameras = cfg.get("cameras") or [cfg["camera"]]  # aceita o formato antigo (uma câmera)
    cfg["cameras"] = [{"id": i, "nome": c.get("nome") or f"Câmera {i + 1}", "fonte": c["fonte"]}
                      for i, c in enumerate(cameras) if c.get("ativa", True)]
    if not cfg["cameras"]:
        sys.exit("Nenhuma câmera ativa no config.yaml.")
    return cfg


def fonte_real(fonte):
    """Troca ${VARIAVEL} pelo valor guardado no Windows (usuário/senha da câmera)."""
    return expandir(fonte) if isinstance(fonte, str) else fonte


def criar_detector(cfg, modelo_forcado=None):
    """Devolve (função detectar(quadro) -> [Deteccao], descrição do motor)."""
    motor = "local" if modelo_forcado else cfg["modelo"].get("motor", "local")
    if motor == "roboflow":
        from detector_roboflow import DetectorRoboflow
        rf = DetectorRoboflow(cfg["modelo"]["roboflow"], cfg["modelo"]["classes"],
                              cfg["modelo"]["confianca_minima"])
        return rf.detectar, f"Roboflow · {rf.especificacao['steps'][0]['model_id']}"

    caminho = modelo_forcado or cfg["modelo"]["caminho"]
    if not Path(caminho).exists() and not caminho.startswith("yolo"):
        sys.exit(f"Modelo não encontrado: {caminho}\nVeja o README, seção 'Modelo'.")
    from ultralytics import YOLO  # import aqui: é lento e só precisa depois das validações
    print(f"Carregando modelo {caminho}...")
    modelo = YOLO(caminho)
    mapa = mapear_classes(modelo.names, cfg["modelo"]["classes"])
    print(f"Classes usadas: { {modelo.names[i]: t for i, t in mapa.items()} }")
    if not set(mapa.values()) & {"capacete", "colete", "sem_capacete", "sem_colete"}:
        print("AVISO: o modelo não tem classes de EPI - todas as pessoas aparecerão como irregulares.")
    return (lambda q: detectar(modelo, q, mapa, cfg["modelo"])), f"Local · {Path(caminho).name}"


class Monitor:
    """Loop de vídeo + detecção + regras + registro. Usado pela janela (monitor.py) e pela tela web (painel.py)."""

    DURACAO_ALERTA_S = 8
    HISTORICO = 35  # quantas análises recentes a tela mostra na barrinha da câmera

    def __init__(self, cfg, fonte, detectar_quadro, descricao_motor, nome="Câmera 1", id_camera=0):
        self.cfg, self.fonte = cfg, fonte
        self.detectar_quadro = detectar_quadro
        self.camera, self.id_camera = nome, id_camera
        self.regras = cfg["regras"]
        self.parar = threading.Event()
        self._trava = threading.Lock()
        self._novo_jpeg = threading.Condition()
        self.jpeg = None  # último quadro anotado, para a tela web
        self._deteccoes, self._situacoes = [], []
        self._alerta_texto, self._alerta_ate = None, 0.0
        self.estado = {
            "id": id_camera, "camera": self.camera, "motor": descricao_motor, "epis": self.regras["epis_obrigatorios"],
            "tempo_minimo_s": self.regras["tempo_minimo_s"],
            "online": False, "pessoas": 0, "irregulares": 0, "infracoes_sessao": 0,
            "alerta": None, "ultima_analise_s": None, "erro": None, "historico": [],
        }

    # ----- análise (detecção + regras + registro)
    def _analisar(self, quadro, agora, controle, registro, alertas):
        inicio = time.monotonic()
        erro = None
        try:
            deteccoes = self.detectar_quadro(quadro)
        except Exception as e:  # rede instável, limite da API...: segue com o último resultado
            erro, deteccoes = str(e), self._deteccoes
            print(f"[ERRO na detecção] {e}", flush=True)
        situacoes = avaliar_quadro(deteccoes, self.regras["epis_obrigatorios"],
                                   self.regras["altura_minima_pessoa_px"])
        with self._trava:
            self._deteccoes, self._situacoes = deteccoes, situacoes
        for s in controle.atualizar(situacoes, agora):
            self.estado["infracoes_sessao"] += 1
            anotado = desenhar(quadro, deteccoes, situacoes, self.camera, self.estado["infracoes_sessao"], None)
            quando, faltando, _ = registro.salvar(self.camera, s, anotado)
            alertas.disparar(self.camera, quando, faltando)
            self._alerta_texto = f"Pessoa #{s.track_id} sem " + " e ".join(
                NOMES_EPI[e].lower() for e in s.faltando)
            self._alerta_ate = time.monotonic() + self.DURACAO_ALERTA_S

        irregulares = sum(1 for s in situacoes if s.faltando)
        hist = self.estado["historico"] + ["irregular" if irregulares else ("ok" if situacoes else "vazio")]
        self.estado.update(pessoas=len(situacoes), irregulares=irregulares, erro=erro,
                           ultima_analise_s=round(time.monotonic() - inicio, 2),
                           historico=hist[-self.HISTORICO:])

    def _trabalhador(self, fonte_video, controle, registro, alertas):
        """Câmera ao vivo: analisa sempre o quadro mais recente, sem travar o vídeo."""
        ultimo = None
        intervalo = self.cfg["desempenho"].get("intervalo_minimo_analise_s", 0)
        while not self.parar.is_set():
            quadro, agora = fonte_video.ler()
            if quadro is None or quadro is ultimo:
                time.sleep(0.02)
                continue
            ultimo = quadro
            inicio = time.monotonic()
            self._analisar(quadro, agora, controle, registro, alertas)
            self.parar.wait(max(0.0, intervalo - (time.monotonic() - inicio)))

    # ----- loop principal
    def executar(self, mostrar_janela=False, publicar_jpeg=False):
        try:
            fonte = fonte_real(self.fonte)
        except SystemExit as e:  # falta usuário/senha desta câmera: avisa na tela, as outras seguem
            self.estado["erro"] = str(e).splitlines()[0]
            print(f"[{self.camera}] {self.estado['erro']}", flush=True)
            return
        self.estado["erro"] = "Conectando à câmera…"
        fonte_video, ao_vivo = abrir_fonte(fonte)
        registro = Registro(self.cfg["registro"]["pasta"], self.cfg["registro"]["banco"])
        alertas = Alertas(som=self.cfg["alertas"]["som"])
        controle = ControleTemporal(self.regras["tempo_minimo_s"], self.regras["intervalo_repeticao_s"])
        pular = max(1, self.cfg["desempenho"]["processar_a_cada_n_quadros"])
        if ao_vivo:
            threading.Thread(target=self._trabalhador, args=(fonte_video, controle, registro, alertas),
                             daemon=True).start()

        print(f"Monitorando '{self.camera}' (fonte: {mascarar(self.fonte)}).")
        n_quadro, ultimo_publicado = 0, 0.0
        # vídeo gravado exibido na tela: toca na velocidade real (sem tela, processa o mais rápido possível)
        ritmo = not ao_vivo and (mostrar_janela or publicar_jpeg)
        relogio_inicio = time.monotonic()
        try:
            while not self.parar.is_set():
                quadro, agora = fonte_video.ler()
                self.estado["online"] = fonte_video.online
                if quadro is None:
                    if not ao_vivo:
                        print("Fim do vídeo.")
                        break
                    self.estado["erro"] = getattr(fonte_video, "erro", None) or (
                        "Sem conexão com a câmera: confira se o PC está na mesma rede, "
                        "o IP e o usuário/senha da câmera")
                    time.sleep(0.05)  # câmera ainda não entregou imagem
                    continue
                n_quadro += 1
                if ritmo:
                    atraso = agora - (time.monotonic() - relogio_inicio)
                    if atraso > 0:
                        time.sleep(atraso)
                if not ao_vivo and (n_quadro % pular == 0 or n_quadro == 1):
                    self._analisar(quadro, agora, controle, registro, alertas)

                alerta = self._alerta_texto if time.monotonic() < self._alerta_ate else None
                self.estado["alerta"] = alerta
                with self._trava:
                    deteccoes, situacoes = self._deteccoes, self._situacoes

                if publicar_jpeg and time.monotonic() - ultimo_publicado >= 1 / 15:
                    img = desenhar(quadro, deteccoes, situacoes, self.camera, 0, None, cabecalho=False)
                    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        with self._novo_jpeg:
                            self.jpeg = jpg.tobytes()
                            self._novo_jpeg.notify_all()
                    ultimo_publicado = time.monotonic()

                if mostrar_janela:
                    img = desenhar(quadro, deteccoes, situacoes, self.camera,
                                   self.estado["infracoes_sessao"], alerta)
                    cv2.imshow("Monitor de EPI", img)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                        break
                elif ao_vivo:
                    time.sleep(1 / 30)
        finally:
            self.parar.set()
            self.estado["online"] = False
            fonte_video.fechar()
            time.sleep(0.1)
            registro.fechar()
            if mostrar_janela:
                cv2.destroyAllWindows()
            print(f"Encerrado. Infrações registradas nesta sessão: {self.estado['infracoes_sessao']}")

    def aguardar_jpeg(self, anterior, timeout=2.0):
        """Espera um quadro diferente de `anterior` (usado pelo stream MJPEG)."""
        with self._novo_jpeg:
            self._novo_jpeg.wait_for(lambda: self.jpeg is not anterior or self.parar.is_set(), timeout)
            return self.jpeg


def main():
    os.chdir(PASTA)  # caminhos relativos do config valem a partir da pasta do projeto
    ap = argparse.ArgumentParser(description="Monitor de EPI (janela). Para a tela web use painel.py")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--camera", type=int, default=1, help="qual câmera da lista do config (1, 2, ...)")
    ap.add_argument("--fonte", help="sobrescreve a fonte da câmera escolhida")
    ap.add_argument("--modelo", help="usa um modelo .pt local (ignora o motor do config)")
    ap.add_argument("--sem-janela", action="store_true", help="roda sem abrir janela de vídeo")
    args = ap.parse_args()

    cfg = carregar_config(args.config)
    cam = cfg["cameras"][max(0, min(args.camera, len(cfg["cameras"])) - 1)]
    fonte = args.fonte if args.fonte is not None else cam["fonte"]
    detectar_quadro, motor = criar_detector(cfg, args.modelo)
    print(f"Detecção: {motor}. Pressione Q na janela para sair.")
    monitor = Monitor(cfg, fonte, detectar_quadro, motor, cam["nome"], cam["id"])
    try:
        monitor.executar(mostrar_janela=cfg["alertas"]["mostrar_janela"] and not args.sem_janela)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
