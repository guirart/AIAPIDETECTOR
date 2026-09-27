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


def _area(caixa):
    return max(0.0, caixa[2] - caixa[0]) * max(0.0, caixa[3] - caixa[1])


def _intersecao(a, b):
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def sobreposicao(a, b):
    """Quanto da caixa MENOR está dentro da outra (0 a 1)."""
    menor = min(_area(a), _area(b))
    return _intersecao(a, b) / menor if menor > 0 else 0.0


# "Sem EPI" com pelo menos metade da caixa em cima de uma pessoa pertence a ela
SOBREPOSICAO_MINIMA = 0.5


def avaliar_quadro(deteccoes, epis_obrigatorios, altura_minima_px=0):
    """Retorna a Situacao de cada pessoa visível no quadro."""
    pessoas = [d for d in deteccoes if d.tipo == "pessoa"
               and (d.caixa[3] - d.caixa[1]) >= altura_minima_px]
    faltando = [[] for _ in pessoas]

    # EPI presente: precisa estar na região certa do corpo (capacete na mão não vale)
    for n, p in enumerate(pessoas):
        for epi in epis_obrigatorios:
            if not any(d.tipo == epi and _dentro_da_regiao(d.caixa, p.caixa, REGIAO_EPI[epi])
                       for d in deteccoes):
                faltando[n].append(epi)

    # "Sem EPI" explícito: vai para a pessoa em que ele mais se sobrepõe, em qualquer altura
    # (de perto, o modelo às vezes marca fora da região esperada - antes isso virava uma "pessoa" a mais)
    soltos = []
    for d in deteccoes:
        epi = d.tipo.removeprefix("sem_")
        if not d.tipo.startswith("sem_") or epi not in epis_obrigatorios:
            continue
        melhor = max(range(len(pessoas)), key=lambda n: sobreposicao(d.caixa, pessoas[n].caixa), default=None)
        if melhor is not None and sobreposicao(d.caixa, pessoas[melhor].caixa) >= SOBREPOSICAO_MINIMA:
            if epi not in faltando[melhor]:
                faltando[melhor].append(epi)
        else:
            soltos.append(d)

    situacoes = [Situacao(p.track_id, p.caixa, [e for e in epis_obrigatorios if e in f])
                 for p, f in zip(pessoas, faltando)]
    # "Sem EPI" longe de qualquer pessoa (ex.: modelo sem classe pessoa): já é infração por si
    for d in soltos:
        situacoes.append(Situacao(d.track_id, d.caixa, [d.tipo.removeprefix("sem_")]))
    return situacoes


class ControleTemporal:
    """Só confirma infração depois de X segundos seguidos, e não repete a mesma pessoa."""

    def __init__(self, tempo_minimo_s, intervalo_repeticao_s, esquecer_apos_s=10, janela_duplicata_s=15):
        self.tempo_minimo_s = tempo_minimo_s
        self.intervalo_repeticao_s = intervalo_repeticao_s
        self.esquecer_apos_s = esquecer_apos_s
        # O rastreador às vezes troca o número da mesma pessoa (#1 vira #3). Infração no mesmo lugar
        # da imagem, com os mesmos EPIs, dentro desta janela é considerada a mesma pessoa.
        self.janela_duplicata_s = janela_duplicata_s
        self._inicio_falta = {}     # (track_id, epi) -> instante em que começou a faltar
        self._ultimo_registro = {}  # track_id -> instante do último registro
        self._visto = {}            # track_id -> último instante visto
        self._recentes = []         # [(instante, caixa, epis)] das últimas infrações registradas

    def _duplicada(self, s, agora):
        return any(agora - t <= self.janela_duplicata_s and set(s.faltando) <= epis
                   and sobreposicao(s.caixa, caixa) >= SOBREPOSICAO_MINIMA
                   for t, caixa, epis in self._recentes)

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
                self._ultimo_registro[s.track_id] = agora  # duplicada ou não, este número já foi tratado
                confirmada = Situacao(s.track_id, s.caixa, persistentes)
                if not self._duplicada(confirmada, agora):
                    self._recentes.append((agora, s.caixa, set(persistentes)))
                    confirmadas.append(confirmada)

        self._limpar(agora)
        return confirmadas

    def _limpar(self, agora):
        self._recentes = [r for r in self._recentes if agora - r[0] <= self.janela_duplicata_s]
        sumidos = [t for t, v in self._visto.items() if agora - v > self.esquecer_apos_s]
        for t in sumidos:
            self._visto.pop(t)
            self._inicio_falta.pop((t, "capacete"), None)
            self._inicio_falta.pop((t, "colete"), None)
        antigos = [t for t, v in self._ultimo_registro.items()
                   if agora - v > self.intervalo_repeticao_s and t not in self._visto]
        for t in antigos:
            self._ultimo_registro.pop(t)
