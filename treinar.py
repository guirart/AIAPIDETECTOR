"""Treina o modelo de EPI a partir de um dataset no formato YOLO e salva em modelos/epi.pt.

Uso:
    python treinar.py --dados datasets/epi/data.yaml
    python treinar.py --dados datasets/epi/data.yaml --epocas 30 --dispositivo cpu

Sem placa de vídeo NVIDIA o treino é lento (horas). Veja no README como treinar grátis no Google Colab.
"""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

PASTA = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True, help="caminho do data.yaml do dataset")
    ap.add_argument("--epocas", type=int, default=50)
    ap.add_argument("--base", default="yolo11n.pt", help="modelo inicial (n = mais leve, ideal para CPU)")
    ap.add_argument("--tamanho", type=int, default=640)
    ap.add_argument("--dispositivo", default=None, help="cpu, 0 (GPU)... padrão: automático")
    args = ap.parse_args()

    modelo = YOLO(args.base)
    modelo.train(data=args.dados, epochs=args.epocas, imgsz=args.tamanho, device=args.dispositivo,
                 project=str(PASTA / "treinos"), name="epi", exist_ok=True, patience=15)

    melhor = PASTA / "treinos" / "epi" / "weights" / "best.pt"
    destino = PASTA / "modelos" / "epi.pt"
    destino.parent.mkdir(exist_ok=True)
    shutil.copy(melhor, destino)
    print(f"\nModelo salvo em {destino}. Classes: {YOLO(destino).names}")


if __name__ == "__main__":
    main()
