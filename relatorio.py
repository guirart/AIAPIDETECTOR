"""Gera um relatório HTML das infrações registradas e abre no navegador.

Uso:
    python relatorio.py              # todas as infrações
    python relatorio.py --dias 7     # últimos 7 dias
"""
import argparse
import html
import os
import sqlite3
import webbrowser
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import yaml

PASTA = Path(__file__).resolve().parent


def main():
    os.chdir(PASTA)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, help="considerar só os últimos N dias")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--nao-abrir", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    banco = Path(cfg["registro"]["banco"])
    if not banco.exists():
        raise SystemExit("Nenhuma infração registrada ainda (banco não existe).")

    con = sqlite3.connect(banco)
    sql, params = "SELECT data_hora, camera, pessoa_id, epis_faltando, imagem FROM infracoes", []
    if args.dias:
        sql += " WHERE data_hora >= ?"
        params.append((datetime.now() - timedelta(days=args.dias)).isoformat())
    linhas = con.execute(sql + " ORDER BY data_hora DESC", params).fetchall()
    con.close()

    saida = Path(cfg["registro"]["pasta"]) / "relatorio.html"
    saida.write_text(montar_html(linhas, args.dias, saida.parent.resolve()), encoding="utf-8")
    print(f"Relatório gerado: {saida.resolve()} ({len(linhas)} infrações)")
    if not args.nao_abrir:
        webbrowser.open(saida.resolve().as_uri())


def montar_html(linhas, dias, pasta_saida):
    total = len(linhas)
    sem_capacete = sum("Capacete" in l[3] for l in linhas)
    sem_colete = sum("Colete" in l[3] for l in linhas)
    por_hora = Counter(datetime.fromisoformat(l[0]).hour for l in linhas)
    por_camera = Counter(l[1] for l in linhas)
    maior = max(por_hora.values(), default=1)

    barras = "".join(
        f'<div class="barra" title="{h:02d}h: {por_hora[h]}"><span style="height:{por_hora[h] / maior * 100:.0f}%">'
        f'</span><small>{h:02d}</small></div>' for h in range(24))
    cameras = "".join(f"<li>{html.escape(c)}: <b>{n}</b></li>" for c, n in por_camera.most_common())

    def img_rel(caminho):
        try:
            return Path(os.path.relpath(caminho, pasta_saida)).as_posix()
        except ValueError:
            return Path(caminho).as_uri()

    tabela = "".join(
        f"<tr><td>{datetime.fromisoformat(d):%d/%m/%Y %H:%M:%S}</td><td>{html.escape(c)}</td>"
        f"<td>#{p if p is not None else '-'}</td><td class='falta'>{html.escape(f)}</td>"
        f"<td><a href='{img_rel(i)}' target='_blank'><img src='{img_rel(i)}' loading='lazy'></a></td></tr>"
        for d, c, p, f, i in linhas)
    periodo = f"últimos {dias} dias" if dias else "todo o período"

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório de EPI</title><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f5f7;color:#1f2328}}
header{{background:#1f2937;color:#fff;padding:18px 24px}} header h1{{margin:0;font-size:20px}}
header p{{margin:4px 0 0;opacity:.75;font-size:13px}}
main{{padding:20px 24px;max-width:1200px;margin:auto}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.card{{background:#fff;border-radius:8px;padding:14px 16px;box-shadow:0 1px 2px #0001}}
.card b{{display:block;font-size:28px}} .card span{{font-size:13px;color:#57606a}}
.vermelho b{{color:#c62828}} section{{background:#fff;border-radius:8px;padding:16px;margin-top:16px;box-shadow:0 1px 2px #0001}}
h2{{font-size:15px;margin:0 0 12px}}
.grafico{{display:flex;align-items:flex-end;gap:4px;height:140px}}
.barra{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%;text-align:center}}
.barra span{{background:#c62828;border-radius:3px 3px 0 0;min-height:1px}} .barra small{{font-size:10px;color:#57606a}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{padding:8px;border-bottom:1px solid #eee;text-align:left}}
th{{background:#fafafa}} td img{{height:70px;border-radius:4px}} .falta{{color:#c62828;font-weight:600}}
.tabela{{overflow-x:auto}}
</style></head><body>
<header><h1>Relatório de uso de EPI</h1><p>{periodo} · gerado em {datetime.now():%d/%m/%Y %H:%M}</p></header>
<main>
<div class="cards">
 <div class="card vermelho"><b>{total}</b><span>Infrações registradas</span></div>
 <div class="card"><b>{sem_capacete}</b><span>Sem capacete</span></div>
 <div class="card"><b>{sem_colete}</b><span>Sem colete refletivo</span></div>
</div>
<section><h2>Infrações por hora do dia</h2><div class="grafico">{barras}</div></section>
<section><h2>Por câmera</h2><ul>{cameras or '<li>-</li>'}</ul></section>
<section><h2>Ocorrências</h2><div class="tabela"><table>
<tr><th>Data/hora</th><th>Câmera</th><th>Pessoa</th><th>EPI faltando</th><th>Evidência</th></tr>
{tabela or '<tr><td colspan="5">Nenhuma infração no período.</td></tr>'}
</table></div></section>
</main></body></html>"""


if __name__ == "__main__":
    main()
