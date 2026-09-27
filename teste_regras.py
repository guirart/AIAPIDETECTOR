"""Testes da lógica de regras (não precisa de câmera nem modelo). Rode: python teste_regras.py"""
from regras import ControleTemporal, Deteccao, avaliar_quadro

OBRIG = ["capacete", "colete"]
PESSOA = Deteccao("pessoa", (100, 100, 200, 400), 0.9, 1)          # altura 300
CAPACETE = Deteccao("capacete", (130, 95, 170, 130), 0.8)           # topo da pessoa
COLETE = Deteccao("colete", (110, 170, 190, 280), 0.8)              # tronco
CAPACETE_NA_MAO = Deteccao("capacete", (150, 300, 190, 340), 0.8)   # altura da cintura


def faltando(deteccoes):
    return avaliar_quadro(deteccoes, OBRIG)[0].faltando


def test_conforme():
    assert faltando([PESSOA, CAPACETE, COLETE]) == []


def test_sem_capacete():
    assert faltando([PESSOA, COLETE]) == ["capacete"]


def test_sem_nada():
    assert faltando([PESSOA]) == ["capacete", "colete"]


def test_capacete_na_mao_nao_conta():
    assert faltando([PESSOA, CAPACETE_NA_MAO, COLETE]) == ["capacete"]


def test_negativo_explicito_prevalece():
    sem = Deteccao("sem_capacete", (130, 95, 170, 130), 0.7)
    assert faltando([PESSOA, CAPACETE, COLETE, sem]) == ["capacete"]


def test_negativo_sem_pessoa_vira_infracao():
    sem = Deteccao("sem_colete", (10, 10, 50, 90), 0.7, 5)
    s = avaliar_quadro([sem], OBRIG)
    assert len(s) == 1 and s[0].faltando == ["colete"] and s[0].track_id == 5


def test_epi_nao_obrigatorio_ignorado():
    assert avaliar_quadro([PESSOA, CAPACETE], ["capacete"])[0].faltando == []


def test_pessoa_pequena_ignorada():
    assert avaliar_quadro([PESSOA], OBRIG, altura_minima_px=400) == []


def test_temporal_so_confirma_apos_tempo_minimo():
    c = ControleTemporal(tempo_minimo_s=2, intervalo_repeticao_s=60)
    s = avaliar_quadro([PESSOA], OBRIG)
    assert c.atualizar(s, 0.0) == []
    assert c.atualizar(s, 1.5) == []
    confirmadas = c.atualizar(s, 2.1)
    assert len(confirmadas) == 1 and confirmadas[0].faltando == ["capacete", "colete"]


def test_temporal_nao_repete_dentro_do_intervalo():
    c = ControleTemporal(tempo_minimo_s=2, intervalo_repeticao_s=60)
    s = avaliar_quadro([PESSOA], OBRIG)
    for t in (0, 2.5):
        c.atualizar(s, t)
    assert c.atualizar(s, 30) == []
    assert len(c.atualizar(s, 63)) == 1


def test_temporal_zera_quando_coloca_epi():
    c = ControleTemporal(tempo_minimo_s=2, intervalo_repeticao_s=60)
    sem = avaliar_quadro([PESSOA, COLETE], OBRIG)
    com = avaliar_quadro([PESSOA, CAPACETE, COLETE], OBRIG)
    c.atualizar(sem, 0)
    c.atualizar(com, 1.5)       # colocou o capacete antes de 2s
    assert c.atualizar(sem, 2.5) == []   # contagem recomeçou
    assert len(c.atualizar(sem, 4.6)) == 1


if __name__ == "__main__":
    testes = [f for n, f in dict(globals()).items() if n.startswith("test_")]
    for t in testes:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(testes)} testes passaram.")
