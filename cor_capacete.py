"""Confere pela COR o que o modelo disse sobre a cabeça (capacete x sem capacete).

Capacetes são de cor viva (amarelo, laranja, verde, azul, vermelho) ou brancos; cabelo e cabeça são
escuros/sem cor. Em imagens pequenas (grade do app, tela de proteção na frente) o modelo público às vezes
chama cabelo preto de "capacete" (79%!) ou capacete verde de "sem capacete".

Calibrado com 28 cabeças reais das câmeras (28/09): capacetes 32-77% de "cor de capacete",
cabeças sem capacete 2-27%. Só corrigimos quando não há dúvida:
  - "capacete" com menos de 15%  -> "sem_capacete" (era cabelo)
  - "sem_capacete" com mais de 45% -> "capacete"  (era capacete colorido)
No meio, vale o que o modelo disse.
"""
from dataclasses import replace

import cv2
import numpy as np


def cor_de_capacete(imagem, caixa):
    """% dos pixels da caixa com cor viva (saturada e clara) ou muito claros (capacete branco)."""
    h, w = imagem.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in caixa)
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    hsv = cv2.cvtColor(imagem[y1:y2, x1:x2], cv2.COLOR_BGR2HSV).reshape(-1, 3)
    s, v = hsv[:, 1].astype(int), hsv[:, 2].astype(int)
    return float((((s > 90) & (v > 90)) | (v > 190)).mean() * 100)


def corrigir_cabecas(imagem, deteccoes, rebaixar_abaixo=15, promover_acima=45):
    """Devolve as detecções com capacete/sem_capacete corrigidos pela cor (as outras ficam iguais)."""
    corrigidas = []
    for d in deteccoes:
        if d.tipo in ("capacete", "sem_capacete"):
            cor = cor_de_capacete(imagem, d.caixa)
            if cor is not None:
                if d.tipo == "capacete" and cor < rebaixar_abaixo:
                    d = replace(d, tipo="sem_capacete")
                elif d.tipo == "sem_capacete" and cor > promover_acima:
                    d = replace(d, tipo="capacete")
        corrigidas.append(d)
    return corrigidas
