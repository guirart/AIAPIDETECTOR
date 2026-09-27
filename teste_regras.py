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


def test_exigir_pessoa_ignora_sem_epi_solto():
    # Alarme falso real: "sem colete" nos botões do app Tapo, sem ninguém na imagem
    botoes = Deteccao("sem_colete", (1340, 400, 1452, 750), 0.5, 1)
    assert avaliar_quadro([botoes], OBRIG, exigir_pessoa=True) == []
    # mas o "sem EPI" em cima de uma pessoa continua valendo
    sem = Deteccao("sem_capacete", (130, 95, 170, 130), 0.7)
    assert avaliar_quadro([PESSOA, COLETE, sem], OBRIG, exigir_pessoa=True)[0].faltando == ["capacete"]


def test_exigir_evidencia_ignora_objeto_confundido_com_pessoa():
    # Alarme falso real: latas de tinta viraram "Person" (74%), sem capacete/colete e sem NO-Hardhat
    latas = Deteccao("pessoa", (218, 407, 287, 568), 0.74, 1)
    assert avaliar_quadro([latas], OBRIG, exigir_evidencia=True)[0].faltando == []
    assert avaliar_quadro([latas], OBRIG, exigir_evidencia=False)[0].faltando == ["capacete", "colete"]


def test_exigir_evidencia_pega_quem_o_modelo_viu_sem_epi():
    sem_capacete = Deteccao("sem_capacete", (130, 95, 170, 130), 0.8)
    s = avaliar_quadro([PESSOA, sem_capacete], OBRIG, exigir_evidencia=True)
    assert s[0].faltando == ["capacete"]


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


def test_sem_colete_fora_da_regiao_fica_com_a_pessoa():
    # Webcam de perto: o modelo marcou "sem colete" na parte de baixo da imagem (abaixo do tronco).
    # Antes isso virava uma segunda "pessoa" e gerava alerta duplicado.
    perto = Deteccao("pessoa", (100, 100, 400, 480), 0.9, 1)
    sem_colete = Deteccao("sem_colete", (150, 400, 350, 480), 0.7, 3)
    s = avaliar_quadro([perto, sem_colete], OBRIG)
    assert len(s) == 1 and s[0].track_id == 1 and s[0].faltando == ["capacete", "colete"]


def test_sem_epi_de_outra_pessoa_nao_se_mistura():
    outra = Deteccao("pessoa", (500, 100, 600, 400), 0.9, 2)
    sem_capacete_da_outra = Deteccao("sem_capacete", (530, 95, 570, 130), 0.8)
    s = avaliar_quadro([PESSOA, CAPACETE, COLETE, outra, COLETE_DA(outra), sem_capacete_da_outra], OBRIG)
    assert [x.faltando for x in s] == [[], ["capacete"]]


def COLETE_DA(p):
    x1, y1, x2, y2 = p.caixa
    return Deteccao("colete", (x1 + 10, y1 + 70, x2 - 10, y1 + 180), 0.8)


def test_troca_de_numero_nao_duplica_infracao():
    c = ControleTemporal(tempo_minimo_s=2, intervalo_repeticao_s=60)
    s1 = avaliar_quadro([PESSOA], OBRIG)
    c.atualizar(s1, 0)
    assert len(c.atualizar(s1, 2.5)) == 1
    # rastreador perdeu e deu número novo (#9) para a mesma pessoa no mesmo lugar
    s9 = avaliar_quadro([Deteccao("pessoa", (105, 102, 205, 402), 0.9, 9)], OBRIG)
    c.atualizar(s9, 4)
    assert c.atualizar(s9, 6.5) == []


def test_outra_pessoa_em_outro_lugar_ainda_registra():
    c = ControleTemporal(tempo_minimo_s=2, intervalo_repeticao_s=60)
    duas = avaliar_quadro([PESSOA, Deteccao("pessoa", (500, 100, 600, 400), 0.9, 2)], OBRIG)
    c.atualizar(duas, 0)
    assert len(c.atualizar(duas, 2.5)) == 2


def test_mesmo_lugar_depois_da_janela_registra_de_novo():
    c = ControleTemporal(tempo_minimo_s=2, intervalo_repeticao_s=60, janela_duplicata_s=15)
    c.atualizar(avaliar_quadro([PESSOA], OBRIG), 0)
    c.atualizar(avaliar_quadro([PESSOA], OBRIG), 2.5)
    nova = avaliar_quadro([Deteccao("pessoa", PESSOA.caixa, 0.9, 7)], OBRIG)
    c.atualizar(nova, 30)
    assert len(c.atualizar(nova, 32.5)) == 1


if __name__ == "__main__":
    testes = [f for n, f in dict(globals()).items() if n.startswith("test_")]
    for t in testes:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(testes)} testes passaram.")
