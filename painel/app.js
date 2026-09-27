const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const ICONES = {
  capacete: '<svg viewBox="0 0 24 24"><path d="M3 17c0-5 4-9 9-9s9 4 9 9" fill="#ffd23f"/><rect x="1.5" y="16" width="21" height="3.5" rx="1.7" fill="#ffd23f"/><path d="M10.5 8V6h3v2" fill="#ffd23f" stroke="#ffd23f"/></svg>',
  colete: '<svg viewBox="0 0 24 24"><path d="M7 3l-4 4v14h6v-9l3-3 3 3v9h6V7l-4-4-2 3h-6z" fill="#ff7a1a"/><rect x="3" y="14" width="6" height="2" fill="#e8ecf3"/><rect x="15" y="14" width="6" height="2" fill="#e8ecf3"/></svg>',
};
const NOMES = { capacete: 'Capacete', colete: 'Colete refletivo' };
const MESES = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];

let dias = 1;
let infracoesSessao = null;
let episMontados = false;
let idsVistos = null;

function toast(msg, ms = 4000) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), ms);
}

function flash() {
  const f = $('#flash');
  f.classList.remove('go');
  void f.offsetWidth;
  f.classList.add('go');
}

// ---------- Relógio ----------
setInterval(() => ($('#clock').textContent = new Date().toLocaleTimeString('pt-BR')), 1000);

// ---------- Situação ----------
function setStatus(classe, html) {
  const bar = $('#statusBar');
  if (!bar.classList.contains(classe)) bar.className = `status-bar ${classe}`;
  if ($('#statusText').innerHTML !== html) $('#statusText').innerHTML = html;
}

function plural(n, um, varios) { return `${n} ${n === 1 ? um : varios}`; }

// ---------- Câmeras ----------
function cartaoCamera(c) {
  const card = document.createElement('div');
  card.className = 'cam';
  card.dataset.cam = c.id;
  card.innerHTML = `
    <div class="screen">
      <img alt="Vídeo ao vivo: ${esc(c.camera)}">
      <span class="tag live">Ao vivo</span>
      <span class="tag num">Cam ${String(c.id + 1).padStart(2, '0')}</span>
      <span class="cam-name">${esc(c.camera)}</span>
    </div>
    <div class="cam-info">
      <div class="meter" title="Últimas análises: verde = todos com EPI, vermelho = alguém sem EPI"></div>
      <div class="cam-meta"><span class="meta"></span><span class="lat"></span></div>
      <div class="err" hidden></div>
    </div>`;
  const img = card.querySelector('img');
  const conectar = () => (img.src = `/video/${c.id}.mjpg?t=${Date.now()}`);
  img.addEventListener('error', () => setTimeout(conectar, 3000));
  conectar();
  return card;
}

function renderCamera(c) {
  const el = $('#cameras');
  let card = el.querySelector(`[data-cam="${c.id}"]`);
  if (!card) el.append((card = cartaoCamera(c)));
  card.classList.toggle('bad', c.online && c.irregulares > 0);
  card.classList.toggle('off', !c.online);
  const tag = card.querySelector('.tag.live, .tag.nosignal');
  tag.className = `tag ${c.online ? 'live' : 'nosignal'}`;
  tag.textContent = c.online ? 'Ao vivo' : 'Sem sinal';

  const hist = c.historico || [];
  const vazios = Array(Math.max(0, 35 - hist.length)).fill('');
  card.querySelector('.meter').innerHTML = [...vazios, ...hist].map((h) => `<i class="${h}"></i>`).join('');
  card.querySelector('.meta').innerHTML = `Pessoas <b>${c.pessoas}</b> · Sem EPI <b class="${c.irregulares ? 'bad' : ''}">${c.irregulares}</b> · Nesta sessão <b>${c.infracoes_sessao}</b>`;
  card.querySelector('.lat').innerHTML = c.ultima_analise_s != null ? `Análise <b>${c.ultima_analise_s.toFixed(1).replace('.', ',')} s</b>` : '';
  const err = card.querySelector('.err');
  err.hidden = !c.erro;
  err.textContent = c.erro ? (c.online ? `Erro na detecção: ${c.erro}` : c.erro) : '';
}

// ---------- Situação geral (todas as câmeras) ----------
function render(st) {
  const cams = st.cameras;
  if (!episMontados) {
    $('#epis').innerHTML = st.epis.map((e) => `<span class="chip">${ICONES[e] || ''}${esc(NOMES[e] || e)}</span>`).join('');
    $('#cameras').classList.toggle('uma', cams.length === 1);
    episMontados = true;
  }
  cams.forEach(renderCamera);

  const online = cams.filter((c) => c.online);
  const pessoas = online.reduce((s, c) => s + c.pessoas, 0);
  const irregulares = online.reduce((s, c) => s + c.irregulares, 0);
  const sessao = cams.reduce((s, c) => s + c.infracoes_sessao, 0);
  const comAlerta = online.find((c) => c.alerta);
  const varias = cams.length > 1;

  $('#sbPessoas').textContent = online.length ? pessoas : '–';
  $('#sbIrregulares').textContent = online.length ? irregulares : '–';
  $('#sbIrregulares').classList.toggle('bad', irregulares > 0);
  $('#sbHoje').textContent = st.infracoes_hoje;
  $('#sbHoje').classList.toggle('bad', st.infracoes_hoje > 0);
  $('#camCount').textContent = varias ? `${online.length} de ${cams.length} ao vivo` : '';

  if (!online.length) setStatus('off', varias ? 'Câmeras sem sinal' : 'Câmera sem sinal');
  else if (comAlerta) setStatus('alert', `<b>Alerta${varias ? ` · ${esc(comAlerta.camera)}` : ''}:</b> ${esc(comAlerta.alerta)}`);
  else if (irregulares > 0) setStatus('check', `<b>Atenção:</b> ${plural(irregulares, 'pessoa', 'pessoas')} sem EPI na área`);
  else if (pessoas > 0) setStatus('ok', `Todos com EPI ✓ · ${plural(pessoas, 'pessoa', 'pessoas')} na área`);
  else setStatus('empty', 'Nenhuma pessoa na área');

  const semSinal = cams.length - online.length;
  $('#hint').innerHTML = `Detecção: <b>${esc(st.motor)}</b> · Regra: <b>${String(st.tempo_minimo_s).replace('.', ',')} s</b> seguidos sem EPI = infração registrada com foto`
    + (semSinal && online.length ? ` · <b style="color:var(--warn)">${plural(semSinal, 'câmera', 'câmeras')} sem sinal</b>` : '');

  // Nova infração nesta sessão: pisca a tela e atualiza a lista
  if (infracoesSessao !== null && sessao > infracoesSessao) {
    flash();
    toast(comAlerta ? `Nova infração · ${varias ? comAlerta.camera + ' · ' : ''}${comAlerta.alerta}` : 'Nova infração registrada');
    carregarLista();
  }
  infracoesSessao = sessao;
}

async function carregarStatus() {
  try {
    const r = await fetch('/api/status', { cache: 'no-store' });
    render(await r.json());
  } catch {
    setStatus('off', 'Monitor desligado');
    for (const tag of document.querySelectorAll('.cam .tag.live')) {
      tag.className = 'tag nosignal';
      tag.textContent = 'Sem sinal';
    }
  }
}

// ---------- Infrações ----------
function cartao(inf, novo) {
  const d = new Date(inf.data_hora);
  const hh = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const ss = `:${String(d.getSeconds()).padStart(2, '0')}`;
  const pessoa = inf.pessoa_id != null ? `Pessoa #${inf.pessoa_id}` : 'Pessoa';
  const badges = inf.faltando.map((f) => `<span class="status">Sem ${esc(f.toLowerCase())}</span>`).join('');
  return `<article class="inf${novo ? ' new' : ''}" data-id="${inf.id}">
    <div class="inf-time"><span class="d">${d.getDate()} de ${MESES[d.getMonth()]}</span><span class="h">${hh}</span><span class="s">${ss}</span></div>
    <div class="inf-body">
      <div class="inf-head">
        <div class="inf-title">${esc(pessoa)}</div>
        <div class="badges">${badges}</div>
        <div class="inf-sub">${esc(inf.camera)}</div>
        <div><button class="icon-btn" data-foto="${inf.id}">Abrir foto</button></div>
      </div>
      <button class="thumb" data-foto="${inf.id}" aria-label="Ampliar foto"><img loading="lazy" src="/api/infracoes/${inf.id}/foto" alt="Foto da infração"></button>
    </div>
  </article>`;
}

async function carregarLista() {
  let dados;
  try {
    dados = await (await fetch(`/api/infracoes?dias=${dias}`, { cache: 'no-store' })).json();
  } catch { return; }
  const el = $('#lista');
  $('#count').textContent = plural(dados.total, 'infração', 'infrações');
  if (!dados.infracoes.length) {
    el.innerHTML = `<p class="empty">Nenhuma infração ${dias === 1 ? 'hoje' : 'no período'}. Tudo certo por aqui. 👷</p>`;
    idsVistos = new Set();
    return;
  }
  const antes = idsVistos;
  idsVistos = new Set(dados.infracoes.map((i) => i.id));
  const assinatura = dados.infracoes.map((i) => i.id).join(',');
  if (el.dataset.assinatura === assinatura) return; // nada mudou: não recarrega as fotos
  el.dataset.assinatura = assinatura;
  el.innerHTML = dados.infracoes.map((i) => cartao(i, antes && !antes.has(i.id))).join('');
}

$('#periodo').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-dias]');
  if (!b) return;
  for (const x of $('#periodo').children) x.setAttribute('aria-checked', String(x === b));
  dias = Number(b.dataset.dias);
  idsVistos = null;
  carregarLista();
});

// ---------- Foto ampliada ----------
$('#lista').addEventListener('click', (e) => {
  const b = e.target.closest('[data-foto]');
  if (!b) return;
  $('#viewer img').src = `/api/infracoes/${b.dataset.foto}/foto`;
  $('#viewer').hidden = false;
});
const fecharFoto = () => ($('#viewer').hidden = true);
$('#viewer').addEventListener('click', (e) => { if (e.target.tagName !== 'IMG') fecharFoto(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') fecharFoto(); });

carregarStatus();
carregarLista();
setInterval(carregarStatus, 1000);
setInterval(carregarLista, 5000);
