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

function render(st) {
  if (!episMontados) {
    $('#epis').innerHTML = st.epis.map((e) => `<span class="chip">${ICONES[e] || ''}${esc(NOMES[e] || e)}</span>`).join('');
    $('#camName').textContent = st.camera;
    episMontados = true;
  }

  $('#sbPessoas').textContent = st.online ? st.pessoas : '–';
  $('#sbIrregulares').textContent = st.online ? st.irregulares : '–';
  $('#sbIrregulares').classList.toggle('bad', st.irregulares > 0);
  $('#sbHoje').textContent = st.infracoes_hoje;
  $('#sbHoje').classList.toggle('bad', st.infracoes_hoje > 0);

  if (!st.online) setStatus('off', 'Câmera sem sinal');
  else if (st.alerta) setStatus('alert', `<b>Alerta:</b> ${esc(st.alerta)}`);
  else if (st.irregulares > 0) setStatus('check', `<b>Atenção:</b> ${plural(st.irregulares, 'pessoa', 'pessoas')} sem EPI na área`);
  else if (st.pessoas > 0) setStatus('ok', `Todos com EPI ✓ · ${plural(st.pessoas, 'pessoa', 'pessoas')} na área`);
  else setStatus('empty', 'Nenhuma pessoa na área');

  const cam = $('#cam');
  cam.classList.toggle('bad', st.online && st.irregulares > 0);
  cam.classList.toggle('off', !st.online);
  const tag = $('#camTag');
  tag.className = `tag ${st.online ? 'live' : 'nosignal'}`;
  tag.textContent = st.online ? 'Ao vivo' : 'Sem sinal';

  const hist = st.historico || [];
  const vazios = Array(Math.max(0, 35 - hist.length)).fill('');
  $('#meter').innerHTML = [...vazios, ...hist].map((h) => `<i class="${h}"></i>`).join('');
  $('#camMeta').innerHTML = `Pessoas <b>${st.pessoas}</b> · Sem EPI <b class="${st.irregulares ? 'bad' : ''}">${st.irregulares}</b> · Nesta sessão <b>${st.infracoes_sessao}</b>`;
  $('#camLat').innerHTML = st.ultima_analise_s != null ? `Análise <b>${st.ultima_analise_s.toFixed(1).replace('.', ',')} s</b>` : '';
  $('#camErr').hidden = !st.erro;
  $('#camErr').textContent = st.erro ? `Erro na detecção: ${st.erro}` : '';

  $('#hint').innerHTML = `Detecção: <b>${esc(st.motor)}</b> · Regra: <b>${String(st.tempo_minimo_s).replace('.', ',')} s</b> seguidos sem EPI = infração registrada com foto`;

  // Nova infração nesta sessão: pisca a tela e atualiza a lista
  if (infracoesSessao !== null && st.infracoes_sessao > infracoesSessao) {
    flash();
    toast(st.alerta ? `Nova infração · ${st.alerta}` : 'Nova infração registrada');
    carregarLista();
  }
  infracoesSessao = st.infracoes_sessao;
}

async function carregarStatus() {
  try {
    const r = await fetch('/api/status', { cache: 'no-store' });
    render(await r.json());
  } catch {
    setStatus('off', 'Monitor desligado');
    $('#camTag').className = 'tag nosignal';
    $('#camTag').textContent = 'Sem sinal';
  }
}

// ---------- Vídeo ----------
function conectarVideo() {
  $('#video').src = `/video.mjpg?t=${Date.now()}`;
}
$('#video').addEventListener('error', () => setTimeout(conectarVideo, 3000));

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

conectarVideo();
carregarStatus();
carregarLista();
setInterval(carregarStatus, 1000);
setInterval(carregarLista, 5000);
