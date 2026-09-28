"""Reconhece cada câmera pela IMAGEM dentro de uma grade (ex.: app Tapo em visualização múltipla).

A câmera é fixa: o cenário (paredes, pilhas, bebedouro, andaime) é a "impressão digital" dela. Guardamos
uma foto de referência de cada câmera em referencias/<nome>.jpg e, a cada poucos segundos, comparamos
cada quadrado da grade com as referências. Se o app reorganizar a grade, cada câmera é achada no novo
lugar; se uma câmera sumir da grade, ela fica "sem sinal" (nunca mostra a imagem de outra).

No config.yaml:
    grades:
      bluestacks:
        fonte: "janela:BlueStacks App Player"
        posicoes: [[e, t, d, b], ...]     # quadrados possíveis da grade (fração da janela)
    cameras:
      - nome: "ALMOXARIFADO"
        fonte: "grade:bluestacks"

Uso pela linha de comando:
    python identificar_cameras.py                         # mostra quem está em cada quadrado agora
    python identificar_cameras.py --referencia "NOME" 2   # salva a referência de NOME a partir do quadrado 2
"""
import argparse
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import cv2
import numpy as np

from captura_tela import fonte_compartilhada

PASTA = Path(__file__).resolve().parent
PASTA_REFERENCIAS = PASTA / "referencias"
TAM = (128, 72)            # tamanho da "impressão digital"
LIMIAR = 0.45              # semelhança mínima para aceitar que é aquela câmera
REF_RECENTE_ACIMA = 0.75   # semelhança para renovar a referência "recente" (luz muda ao longo do dia)
RENOVAR_A_CADA_S = 1800


def _nome_arquivo(texto):
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-") or "camera"


def recortar(imagem, posicao):
    h, w = imagem.shape[:2]
    e, t, d, b = posicao
    return imagem[int(t * h):int(b * h), int(e * w):int(d * w)]


def _mascara():
    m = np.ones((TAM[1], TAM[0]), np.float32)
    m[: int(TAM[1] * 0.12), :] = 0                           # data/hora da câmera (igual em todas)
    m[int(TAM[1] * 0.80):, : int(TAM[0] * 0.30)] = 0         # marca d'água "tapo" (igual em todas)
    return m


MASCARA = _mascara()


def assinatura(imagem):
    """Cinza + bordas, normalizados: comparável mesmo com mudança de luz e com pessoas passando."""
    if imagem is None or imagem.size == 0:
        return None
    cinza = cv2.cvtColor(cv2.resize(imagem, TAM, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0).astype(np.float32)
    bordas = cv2.magnitude(cv2.Sobel(cinza, cv2.CV_32F, 1, 0), cv2.Sobel(cinza, cv2.CV_32F, 0, 1))
    partes = []
    for canal in (cinza, bordas):
        v = canal[MASCARA > 0]
        partes.append((v - v.mean()) / (v.std() + 1e-6))
    return partes


def semelhanca(a, b):
    """-1 a 1 (1 = mesma cena). Média da correlação do cinza e das bordas."""
    if a is None or b is None:
        return -1.0
    return float(np.mean([np.mean(x * y) for x, y in zip(a, b)]))


def caminho_referencia(nome, extra=None):
    """referencias/NOME.jpg (principal) ou referencias/NOME__<extra>.jpg (cenários extras)."""
    sufixo = f"__{extra}" if extra else ""
    return PASTA_REFERENCIAS / f"{_nome_arquivo(nome)}{sufixo}.jpg"


def salvar_referencia(nome, imagem, extra=None):
    PASTA_REFERENCIAS.mkdir(exist_ok=True)
    ok, jpg = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if ok:
        caminho_referencia(nome, extra).write_bytes(jpg.tobytes())


def carregar_referencia(nome):
    c = caminho_referencia(nome)
    return cv2.imdecode(np.fromfile(c, np.uint8), cv2.IMREAD_COLOR) if c.exists() else None


def carregar_referencias(nome):
    """Todas as referências da câmera: a principal + as extras (outras posições da câmera, outra luz)."""
    base = _nome_arquivo(nome)
    arquivos = [PASTA_REFERENCIAS / f"{base}.jpg"] + sorted(PASTA_REFERENCIAS.glob(f"{base}__*.jpg"))
    imgs = [cv2.imdecode(np.fromfile(a, np.uint8), cv2.IMREAD_COLOR) for a in arquivos if a.exists()]
    return [assinatura(i) for i in imgs if i is not None]


def tem_imagem(celula_img):
    """O quadrado mostra vídeo? (o quadrado vazio da grade, com o botão "+", é quase liso)."""
    if celula_img is None or celula_img.size == 0:
        return False
    cinza = cv2.cvtColor(cv2.resize(celula_img, TAM), cv2.COLOR_BGR2GRAY)
    return float(cinza.std()) > 25


def associar(celulas, refs, limiar=LIMIAR, com_imagem=None):
    """celulas: [assinatura por posição]; refs: {nome: [assinaturas]}.
    Devolve ({nome: posição}, {nome: nota}, por_eliminacao) - cada posição para no máximo uma câmera
    (maiores notas primeiro). Se sobrar exatamente 1 câmera sem lugar e exatamente 1 quadrado com imagem
    sem dono, ela é esse quadrado (ex.: a câmera foi girada e o cenário mudou) -> por_eliminacao = nome."""
    pares = []
    for nome, lista in refs.items():
        for i, cel in enumerate(celulas):
            if cel is not None and lista:
                pares.append((max(semelhanca(cel, r) for r in lista), nome, i))
    pares.sort(reverse=True)
    posicao, nota, usadas = {}, {}, set()
    for s, nome, i in pares:
        nota.setdefault(nome, s)
        if s >= limiar and nome not in posicao and i not in usadas:
            posicao[nome], nota[nome] = i, s
            usadas.add(i)

    por_eliminacao = None
    if com_imagem is not None:
        sem_lugar = [n for n, lista in refs.items() if lista and n not in posicao]
        livres = [i for i, tem in enumerate(com_imagem) if tem and i not in usadas]
        if len(sem_lugar) == 1 and len(livres) == 1 and len(posicao) >= 1:
            por_eliminacao = sem_lugar[0]
            posicao[por_eliminacao] = livres[0]
    return posicao, nota, por_eliminacao


class Grade:
    """Captura a janela da grade e mantém "qual câmera está em qual quadrado"."""

    def __init__(self, nome, alvo, posicoes, cameras, intervalo_s=5):
        self.nome, self.posicoes = nome, [tuple(p) for p in posicoes]
        self.fonte = fonte_compartilhada(alvo)
        self.intervalo_s = intervalo_s
        self.refs, self._renovada_em = {}, {}
        self._n_fixas = {}  # quantas referências vêm de arquivo (as demais são a "recente", em memória)
        for c in cameras:
            self.refs[c] = carregar_referencias(c)
            self._n_fixas[c] = len(self.refs[c])
        self.posicao_de, self.nota_de = {}, {}
        self._trava = threading.Lock()
        threading.Thread(target=self._laco, daemon=True).start()

    def _laco(self):
        while True:
            quadro, _ = self.fonte.ler()
            if quadro is not None:
                try:
                    self.identificar(quadro)
                except Exception as e:  # nunca derruba as câmeras por causa da identificação
                    print(f"[grade {self.nome}] erro ao identificar: {e}", flush=True)
            time.sleep(self.intervalo_s)

    def identificar(self, quadro):
        celulas_img = [recortar(quadro, p) for p in self.posicoes]
        celulas = [assinatura(c) for c in celulas_img]
        posicao, nota, eliminada = associar(celulas, self.refs, com_imagem=[tem_imagem(c) for c in celulas_img])
        agora = time.monotonic()
        if eliminada:  # câmera girada / cenário novo: aprende o cenário como referência extra (em arquivo)
            i = posicao[eliminada]
            salvar_referencia(eliminada, celulas_img[i], extra=time.strftime("%Y%m%d-%H%M%S"))
            self.refs[eliminada] = self.refs[eliminada][: self._n_fixas[eliminada]] + [celulas[i]]
            self._n_fixas[eliminada] += 1
            self.refs[eliminada] = self.refs[eliminada][: self._n_fixas[eliminada]]
            print(f"[grade {self.nome}] {eliminada}: cenário novo (câmera girada?) reconhecido por eliminação "
                  f"no quadrado {i + 1}; salvo como referência extra", flush=True)
        for nome, i in posicao.items():  # luz muda ao longo do dia: guarda uma referência recente (memória)
            if nota.get(nome, 0) >= REF_RECENTE_ACIMA and agora - self._renovada_em.get(nome, -1e9) > RENOVAR_A_CADA_S:
                self.refs[nome] = self.refs[nome][: self._n_fixas[nome]] + [celulas[i]]
                self._renovada_em[nome] = agora
        with self._trava:
            antes = dict(self.posicao_de)
            self.posicao_de, self.nota_de = posicao, nota
        if antes and antes != posicao:
            print(f"[grade {self.nome}] câmeras mudaram de lugar: {posicao}", flush=True)
        return posicao, nota

    def onde(self, camera):
        with self._trava:
            return self.posicao_de.get(camera)


class FonteDaGrade:
    """Uma câmera dentro da grade (mesma interface das outras fontes: ler, online, erro, fechar)."""

    def __init__(self, grade, camera):
        self.grade, self.camera = grade, camera
        self._chave = self._saida = None

    @property
    def online(self):
        return self.grade.fonte.online and self.grade.onde(self.camera) is not None

    @property
    def erro(self):
        if not self.grade.fonte.online:
            return self.grade.fonte.erro
        if not self.grade.refs.get(self.camera):
            return (f'Sem foto de referência desta câmera. Rode: python identificar_cameras.py '
                    f'--referencia "{self.camera}" <quadrado>')
        if self.grade.onde(self.camera) is None:
            return "Câmera não encontrada na grade do app (saiu da grade ou a imagem mudou muito)"
        return None

    def ler(self):
        quadro, agora = self.grade.fonte.ler()
        i = self.grade.onde(self.camera)
        if quadro is None or i is None:
            return None, agora
        if self._chave != (id(quadro), i):  # mesmo quadro e lugar -> mesmo objeto (a análise usa isso)
            self._chave = (id(quadro), i)
            self._saida = np.ascontiguousarray(recortar(quadro, self.grade.posicoes[i]))
        return self._saida, agora

    def fechar(self):
        pass  # a captura da janela é compartilhada com as outras câmeras da grade


_grades = {}
_trava_grades = threading.Lock()


def fonte_da_grade(cfg, fonte, camera):
    """fonte = "grade:<nome>" (seção grades do config)."""
    nome = fonte.partition(":")[2]
    g = (cfg.get("grades") or {}).get(nome)
    if not g:
        raise SystemExit(f'Grade "{nome}" não existe na seção grades: do config.yaml')
    with _trava_grades:
        if nome not in _grades:
            cameras = [c["nome"] for c in cfg["cameras"] if str(c["fonte"]) == fonte]
            _grades[nome] = Grade(nome, g["fonte"], g["posicoes"], cameras, g.get("intervalo_s", 5))
        return FonteDaGrade(_grades[nome], camera)


def main():
    import yaml
    os.chdir(PASTA)
    ap = argparse.ArgumentParser(description="Reconhecimento das câmeras na grade")
    ap.add_argument("--grade", default="bluestacks")
    ap.add_argument("--referencia", nargs=2, metavar=("NOME", "QUADRADO"),
                    help="salva a foto de referência da câmera NOME a partir do QUADRADO (1, 2, 3...)")
    args = ap.parse_args()
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    g = cfg["grades"][args.grade]
    fonte = fonte_compartilhada(g["fonte"])
    for _ in range(50):
        quadro, _ = fonte.ler()
        if quadro is not None:
            break
        time.sleep(0.1)
    else:
        raise SystemExit(fonte.erro or "Não consegui capturar a janela da grade.")

    if args.referencia:
        nome, n = args.referencia[0], int(args.referencia[1])
        salvar_referencia(nome, recortar(quadro, g["posicoes"][n - 1]))
        print(f'Referência de "{nome}" salva a partir do quadrado {n}: {caminho_referencia(nome)}')
        return

    cameras = [c["nome"] for c in cfg["cameras"] if str(c["fonte"]) == f"grade:{args.grade}"]
    refs = {c: carregar_referencias(c) for c in cameras}
    celulas_img = [recortar(quadro, p) for p in g["posicoes"]]
    celulas = [assinatura(c) for c in celulas_img]
    print("Semelhança (quadrado x câmera):")
    print(" " * 24 + "".join(f"  Q{i + 1:<5}" for i in range(len(celulas))))
    for c in cameras:
        linha = "".join(f"  {max((semelhanca(cel, r) for r in refs[c]), default=-1):5.2f} " for cel in celulas)
        print(f"{c[:22]:24s}{linha}   ({len(refs[c])} referência(s))")
    posicao, nota, eliminada = associar(celulas, refs, com_imagem=[tem_imagem(c) for c in celulas_img])
    print("\nIdentificação:")
    for c in cameras:
        if c == eliminada:
            print(f"  {c:24s} -> quadrado {posicao[c] + 1} (por eliminação: o cenário mudou)")
        elif c in posicao:
            print(f"  {c:24s} -> quadrado {posicao[c] + 1} (semelhança {nota[c]:.2f})")
        else:
            print(f"  {c:24s} -> NÃO ENCONTRADA (melhor {nota.get(c, -1):.2f})")


if __name__ == "__main__":
    main()
