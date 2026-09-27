"""Alertas em tempo real: som e mensagem no console."""
import threading
import time

try:
    import winsound
except ImportError:  # fora do Windows
    winsound = None


class Alertas:
    def __init__(self, som=True):
        self.som = som and winsound is not None
        self._tocando = False

    def disparar(self, camera, quando, faltando):
        print(f"[ALERTA] {quando:%d/%m/%Y %H:%M:%S} | {camera} | Sem: {faltando}", flush=True)
        if self.som and not self._tocando:
            threading.Thread(target=self._bipar, daemon=True).start()

    def _bipar(self):
        self._tocando = True
        try:
            for _ in range(3):
                winsound.Beep(1500, 250)
                time.sleep(0.1)
        finally:
            self._tocando = False
