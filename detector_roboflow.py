"""Detecção via workflow do Roboflow (modelo público construction-site-safety/27).

A definição do workflow fica em workflows/epi_workflow.json e é executada na nuvem do Roboflow.
O rastreamento (número # de cada pessoa) é feito aqui no PC, com ByteTrack.
"""
import base64
import json
import os
import warnings

import cv2
import numpy as np
import requests

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import supervision as sv

from regras import Deteccao
from segredos import ler_variavel


class DetectorRoboflow:
    def __init__(self, cfg_roboflow, mapa_classes, confianca):
        self.api_key = ler_variavel("ROBOFLOW_API_KEY")
        if not self.api_key:
            raise SystemExit(
                "Falta a chave do Roboflow. No PowerShell rode (com a SUA chave):\n"
                '    setx ROBOFLOW_API_KEY "sua_chave_aqui"\n'
                "e abra um terminal novo. A chave fica em app.roboflow.com > Settings > API Keys.")
        with open(cfg_roboflow["workflow"], encoding="utf-8") as f:
            self.especificacao = json.load(f)
        self.url = cfg_roboflow["url"].rstrip("/") + "/workflows/run"
        self.largura_envio = cfg_roboflow["largura_envio"]
        self.confianca = confianca
        # nome da classe (minúsculo) -> tipo interno
        self.mapa = {nome.lower(): tipo for tipo, nomes in mapa_classes.items() for nome in nomes}
        self.sessao = requests.Session()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            self.rastreador = sv.ByteTrack()

    def detectar(self, quadro):
        escala = min(1.0, self.largura_envio / quadro.shape[1])
        img = cv2.resize(quadro, None, fx=escala, fy=escala) if escala < 1 else quadro
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        resposta = self.sessao.post(self.url, timeout=20, json={
            "api_key": self.api_key,
            "specification": self.especificacao,
            "inputs": {"image": {"type": "base64", "value": base64.b64encode(jpg.tobytes()).decode()},
                       "confianca": self.confianca},
        })
        if resposta.status_code in (401, 403):  # chave errada: não adianta continuar tentando
            raise SystemExit(f"Chave do Roboflow recusada ({resposta.status_code}): {resposta.text[:200]}")
        if resposta.status_code != 200:
            raise RuntimeError(f"Roboflow respondeu {resposta.status_code}: {resposta.text[:200]}")
        return self._converter(extrair_predicoes(resposta.json()), escala)

    def _converter(self, predicoes, escala):
        itens = [p for p in predicoes if p["class"].lower() in self.mapa]
        if not itens:
            self.rastreador.update_with_detections(sv.Detections.empty())
            return []
        # Roboflow devolve centro + largura/altura; convertemos para cantos na escala original
        xyxy = np.array([[p["x"] - p["width"] / 2, p["y"] - p["height"] / 2,
                          p["x"] + p["width"] / 2, p["y"] + p["height"] / 2] for p in itens]) / escala
        dets = sv.Detections(xyxy=xyxy.astype(np.float32),
                             confidence=np.array([p["confidence"] for p in itens], dtype=np.float32),
                             class_id=np.arange(len(itens)),  # índice para recuperar o item original
                             data={"tipo": np.array([self.mapa[p["class"].lower()] for p in itens])})
        dets = self.rastreador.update_with_detections(dets)
        return [Deteccao(str(tipo), tuple(float(v) for v in caixa), float(conf), int(tid))
                for caixa, conf, tid, tipo in zip(dets.xyxy, dets.confidence, dets.tracker_id, dets.data["tipo"])]


def extrair_predicoes(corpo):
    """A resposta vem como {"outputs": [{"predictions": {"predictions": [...]}}]}."""
    saidas = corpo.get("outputs") or [{}]
    pred = saidas[0].get("predictions", {})
    return pred.get("predictions", []) if isinstance(pred, dict) else pred
