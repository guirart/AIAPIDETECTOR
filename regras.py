"""Regras de conformidade: associa EPIs às pessoas e decide quando há infração."""
from dataclasses import dataclass, field

# Região vertical da caixa da pessoa onde cada EPI deve aparecer (fração da altura)
REGIAO_EPI = {
    "capacete": (0.0, 0.35),
    "colete": (0.15, 0.80),
}
NEGATIVO = {"capacete": "sem_capacete", "colete": "sem_colete"}


@dataclass
class Deteccao:
    tipo: str              # pessoa, capacete, colete, sem_capacete, sem_colete
    caixa: tuple           # (x1, y1, x2, y2)
    confianca: float
    track_id: int | None = None


@dataclass
class Situacao:
    """Resultado de uma pessoa em um quadro."""
    track_id: int | None
    caixa: tuple
    faltando: list = field(default_factory=list)


def _centro(caixa):
    x1, y1, x2, y2 = caixa
    return (x1 + x2) / 2, (y1 + y2) / 2


def _dentro_da_regiao(caixa_epi, caixa_pessoa, regiao):
    cx, cy = _centro(caixa_epi)
    x1, y1, x2, y2 = caixa_pessoa
    h = y2 - y1
    topo, base = y1 + regiao[0] * h, y1 + regiao[1] * h
    return x1 <= cx <= x2 and topo <= cy <= base


def avaliar_quadro(deteccoes, epis_obrigatorios, altura_minima_px=0):
    """Retorna a Situacao de cada pessoa visível no quadro."""
    pessoas = [d for d in deteccoes if d.tipo == "pessoa"
               and (d.caixa[3] - d.caixa[1]) >= altura_minima_px]
    usados = set()
    situacoes = []

    for p in pessoas:
        faltando = []
        for epi in epis_obrigatorios:
            regiao = REGIAO_EPI[epi]
            positivos = [i for i, d in enumerate(deteccoes)
                         if d.tipo == epi and _dentro_da_regiao(d.caixa, p.caixa, regiao)]
            negativos = [i for i, d in enumerate(deteccoes)
                         if d.tipo == NEGATIVO[epi] and _dentro_da_regiao(d.caixa, p.caixa, regiao)]
            usados.update(negativos)
            # Um "sem EPI" explícito vale mais que a ausência de detecção
            if negativos or not positivos:
                faltando.append(epi)
        situacoes.append(Situacao(p.track_id, p.caixa, faltando))

    # Modelos sem classe "pessoa" (ou pessoa não detectada): o "sem EPI" solto já é infração
    for i, d in enumerate(deteccoes):
        if i in usados or not d.tipo.startswith("sem_"):
            continue
        epi = d.tipo.removeprefix("sem_")
        if epi in epis_obrigatorios:
            situacoes.append(Situacao(d.track_id, d.caixa, [epi]))

    return situacoes


class ControleTemporal:
    """Só confirma infração depois de X segundos seguidos, e não repete a mesma pessoa."""

    def __init__(self, tempo_minimo_s, intervalo_repeticao_s, esquecer_apos_s=10):
        self.tempo_minimo_s = tempo_minimo_s
        self.intervalo_repeticao_s = intervalo_repeticao_s
        self.esquecer_apos_s = esquecer_apos_s
        self._inicio_falta = {}     # (track_id, epi) -> instante em que começou a faltar
        self._ultimo_registro = {}  # track_id -> instante do último registro
        self._visto = {}            # track_id -> último instante visto

    def atualizar(self, situacoes, agora):
        """Retorna as situações que viraram infração confirmada neste instante."""
        confirmadas = []
        for s in situacoes:
            if s.track_id is None:
                continue  # sem rastreamento não dá para medir duração
            self._visto[s.track_id] = agora
            for epi in ("capacete", "colete"):
                chave = (s.track_id, epi)
                if epi in s.faltando:
                    self._inicio_falta.setdefault(chave, agora)
                else:
                    self._inicio_falta.pop(chave, None)

            persistentes = [epi for epi in s.faltando
                            if agora - self._inicio_falta[(s.track_id, epi)] >= self.tempo_minimo_s]
            ultimo = self._ultimo_registro.get(s.track_id)
            if persistentes and (ultimo is None or agora - ultimo >= self.intervalo_repeticao_s):
                self._ultimo_registro[s.track_id] = agora
                confirmadas.append(Situacao(s.track_id, s.caixa, persistentes))

        self._limpar(agora)
        return confirmadas

    def _limpar(self, agora):
        sumidos = [t for t, v in self._visto.items() if agora - v > self.esquecer_apos_s]
        for t in sumidos:
            self._visto.pop(t)
            self._inicio_falta.pop((t, "capacete"), None)
            self._inicio_falta.pop((t, "colete"), None)
        antigos = [t for t, v in self._ultimo_registro.items()
                   if agora - v > self.intervalo_repeticao_s and t not in self._visto]
        for t in antigos:
            self._ultimo_registro.pop(t)
