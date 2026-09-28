"""Separa os prints repetidos da pasta de fotos de treino (não apaga nada).

A câmera é fixa: o fundo é sempre igual e o que muda são as pessoas. Um print é "repetido" quando
quase nada mudou em relação aos últimos prints mantidos da mesma câmera (ex.: pessoa parada no
bebedouro gera 30 prints iguais). Os repetidos vão para <dia>/repetidas/ (com os recortes das pessoas).

Uso:
    python limpar_repetidas.py              # separa os repetidos e mostra o resumo
    python limpar_repetidas.py --simular    # só mostra o que faria, sem mover nada
    python limpar_repetidas.py --limiar 1   # mais rigoroso: exige mais diferença para manter
"""
import argparse
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import yaml

from coleta import resolver_pasta

PASTA = Path(__file__).resolve().parent
TAM_MINIATURA = (160, 90)
LIMIAR_PIXEL = 22        # diferença de brilho (0-255) para contar um pixel como "mudou"
COMPARAR_COM = 20        # compara com os últimos N prints mantidos da mesma câmera
IGNORAR = {"repetidas", "pessoas"}  # subpastas que não são prints de entrada


def miniatura(arquivo):
    im = cv2.imdecode(np.fromfile(arquivo, np.uint8), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    im = cv2.resize(im, TAM_MINIATURA, interpolation=cv2.INTER_AREA)
    im = cv2.GaussianBlur(im, (5, 5), 0)  # tira ruído de compressão do vídeo
    im[: int(TAM_MINIATURA[1] * 0.09), :] = 0  # faixa da data/hora da câmera (muda todo segundo)
    return im


def mudou(a, b):
    """% da imagem que mudou entre duas miniaturas."""
    if a.shape != b.shape:  # recorte diferente = cena diferente
        return 100.0
    return float((cv2.absdiff(a, b) > LIMIAR_PIXEL).mean() * 100)


def partes(arquivo):
    """ALMOXARIFADO_081856_714_manual.jpg -> ("ALMOXARIFADO", "manual", "ALMOXARIFADO_081856_714")"""
    base, tipo = arquivo.stem.rsplit("_", 1)
    camera = base.rsplit("_", 2)[0]
    return camera, tipo, base


def processar_dia(pasta_dia, limiar, simular):
    fotos = sorted(f for f in pasta_dia.glob("*.jpg"))
    mantidas, repetidas = [], []
    ultimas = defaultdict(list)  # câmera -> miniaturas dos últimos prints mantidos
    for f in fotos:
        m = miniatura(f)
        if m is None:
            continue
        camera, _, _ = partes(f)
        menor = min((mudou(m, u) for u in ultimas[camera]), default=100.0)
        if menor < limiar:
            repetidas.append(f)
        else:
            mantidas.append(f)
            ultimas[camera] = (ultimas[camera] + [m])[-COMPARAR_COM:]

    if not simular and repetidas:
        destino = pasta_dia / "repetidas"
        (destino / "pessoas").mkdir(parents=True, exist_ok=True)
        for f in repetidas:
            shutil.move(str(f), destino / f.name)
            for r in (pasta_dia / "pessoas").glob(f"{partes(f)[2]}_pessoa*.jpg"):
                shutil.move(str(r), destino / "pessoas" / r.name)
    return mantidas, repetidas


def contar_pessoas(pasta_dia, mantidas):
    bases = {partes(f)[2] for f in mantidas}
    return sum(1 for r in (pasta_dia / "pessoas").glob("*.jpg") if r.stem.rsplit("_", 1)[0] in bases)


def main():
    os.chdir(PASTA)
    ap = argparse.ArgumentParser(description="Separa prints repetidos das fotos de treino")
    ap.add_argument("--pasta", help="pasta das fotos (padrão: coleta.pasta do config.yaml)")
    ap.add_argument("--limiar", type=float, default=0.5,
                    help="%% mínima da imagem que precisa mudar para o print ser mantido (padrão 0.5)")
    ap.add_argument("--simular", action="store_true", help="não move nada, só mostra o resultado")
    args = ap.parse_args()

    if args.pasta:
        raiz = Path(args.pasta)
    else:
        with open("config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        raiz = resolver_pasta(cfg.get("coleta", {}).get("pasta", "{AREA_DE_TRABALHO}/Fotos treino EPI"))
    if not raiz.exists():
        raise SystemExit(f"Pasta não encontrada: {raiz}")

    print(f"Pasta: {raiz}{'   (SIMULAÇÃO - nada será movido)' if args.simular else ''}\n")
    total_tipos, total_rep, total_pessoas = Counter(), 0, 0
    for pasta_dia in sorted(p for p in raiz.iterdir() if p.is_dir()):
        mantidas, repetidas = processar_dia(pasta_dia, args.limiar, args.simular)
        if not mantidas and not repetidas:
            continue
        tipos = Counter(partes(f)[1] for f in mantidas)
        pessoas = contar_pessoas(pasta_dia, mantidas)
        total_tipos.update(tipos)
        total_rep += len(repetidas)
        total_pessoas += pessoas
        print(f"{pasta_dia.name}: {len(mantidas) + len(repetidas)} prints -> "
              f"{len(mantidas)} únicos, {len(repetidas)} repetidos"
              f"{'' if args.simular else ' (movidos para repetidas/)'}")

    unicos = sum(total_tipos.values())
    print("\n==== RESUMO (só prints únicos) ====")
    print(f"Prints únicos:       {unicos}")
    print(f"  com pessoa:        {total_tipos['pessoa']}")
    print(f"  tirados por você:  {total_tipos['manual']}")
    print(f"  sem ninguém:       {total_tipos['vazia']}")
    print(f"Pessoas recortadas:  {total_pessoas}")
    print(f"Repetidos:           {total_rep}")
    print(f"\nMeta da 1ª rodada de treino: ~300 prints únicos. Faltam ~{max(0, 300 - unicos)}.")


if __name__ == "__main__":
    main()
