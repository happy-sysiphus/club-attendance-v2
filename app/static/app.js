import { api, session, setSession, clearSession, esc, fmtDate, todayKst, PART, PARTS, ROLE, STATUS, ApiError } from './api.js';
import { icon, dateTile, practiceBadge, practiceMeta, backLink, emptyState } from './ui.js';
import { loadOperations, getState, operationsHome, operationsCalendar, eventView, dayView, adminView } from './operations-ui.js';
import { musicView, concertView, songView, financeView, settingsView } from './library-finance.js';

const view = document.getElementById('view');
let cleanup = null;
let toastTimer;

export function toast(msg, error = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = error ? 'show error' : 'show';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, 3000);
}

function failed() {
  view.innerHTML = `
    <section class="card stack">
      <p>불러오지 못했어요. 연결을 확인해 주세요.</p>
      <button type="button" id="retry" class="btn primary">다시 시도</button>
    </section>`;
  view.querySelector('#retry').onclick = () => route();
}

function renderHeader() {
  const s = session();
  document.body.classList.toggle('is-login', !s);
  document.getElementById('user').textContent = s
    ? s.role === 'conductor' ? `${s.name} · 지휘자` : `${s.name} · ${PART[s.part] || '파트 미정'} · ${ROLE[s.role]}`
    : '';
  document.getElementById('logout').hidden = !s;
  const tabs = document.getElementById('tabs');
  tabs.hidden = !s;
  const active = location.hash === '#/schedule' ? 'schedule' : 'attendance';
  tabs.querySelectorAll('a').forEach(link => {
    if (link.dataset.tab === active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}
document.getElementById('logout').onclick = async () => {
  try { await api('POST', '/auth/logout'); }
  finally { clearSession(); sessionStorage.removeItem('glee-semester'); location.hash = '#/login'; }
};

// ---------- 로그인 ----------
async function loginView() {
  const toolbar = document.getElementById('semester-toolbar');
  if (toolbar) toolbar.hidden = true;
  if (session()) { location.hash = '#/home'; return; }
  view.innerHTML = `
    <section class="login-brand">
      <span class="logo-window login-logo"><img src="/assets/glee-logo-2024.jpg" alt="Glee — Choir Club of Ajou" width="1668" height="1668"></span>
      <p class="eyebrow">아주대학교 합창단 글리</p>
      <h1>우리의 목소리가<br>하나 되는 시간.</h1>
      <p class="muted">출석을 남기고, 다음 만남을 확인하세요.</p>
    </section>
    <section class="login-panel">
      <div class="section-heading"><h2>반가워요!</h2><p class="muted">이름과 학번으로 시작해요.</p></div>
      <form id="login" class="stack">
        <label>이름 <input name="name" required autocomplete="name" placeholder="이름을 입력하세요"></label>
        <label>학번 <input name="student_id" required autocomplete="off" placeholder="학번을 입력하세요" aria-describedby="login-err"></label>
        <p id="login-err" class="err" role="alert" hidden>명단에 없어요. 이름과 학번을 확인하세요.</p>
        <button class="btn primary full-width">로그인 ${icon('chevron-left', 'point-right inverse')}</button>
      </form>
      <p class="login-help">로그인이 되지 않나요?<br>이름과 학번을 확인한 뒤 총무에게 문의해 주세요.</p>
    </section>`;
  const form = view.querySelector('#login');
  try {
    const saved = JSON.parse(localStorage.getItem('login')) || {};
    form.elements.name.value = saved.name || '';
    form.elements.student_id.value = saved.student_id || '';
  } catch { /* 저장된 값 없음 */ }
  form.onsubmit = async e => {
    e.preventDefault();
    const f = e.target.elements;
    const creds = { name: f.name.value, student_id: f.student_id.value };
    try {
      setSession(await api('POST', '/auth/login', creds));
      localStorage.setItem('login', JSON.stringify(creds));
      location.hash = '#/home';
    } catch (err) {
      if (err.status === 401) view.querySelector('#login-err').hidden = false;
      else toast(err.message, true);
    }
  };
}

// ---------- 파트 선택 (파트 미정 단원, 로그인 후 1회) ----------
const CHOOSABLE = ['soprano', 'alto', 'tenor', 'bass']; // 반주자·지휘자는 지휘자가 노션에서 지정
function partPicker() {
  const d = document.createElement('dialog');
  d.className = 'part-picker';
  d.setAttribute('aria-labelledby', 'part-picker-title');
  d.innerHTML = `
    <form class="stack">
      <h2 id="part-picker-title">파트를 선택해 주세요</h2>
      <p class="muted">출석은 파트별로 관리돼요. 한 번 정하면 바꿀 수 없고, 변경은 지휘자에게 문의해 주세요.</p>
      <div class="segment" role="radiogroup" aria-label="파트">
        ${CHOOSABLE.map(v => `<label><input type="radio" name="part" value="${v}"><span>${PART[v]}</span></label>`).join('')}
      </div>
      <p class="err" role="alert" hidden></p>
      <button class="btn primary full-width" disabled>선택 완료</button>
    </form>`;
  document.body.append(d);
  const form = d.querySelector('form'), btn = form.querySelector('button'), err = form.querySelector('.err');
  form.oninput = () => { btn.disabled = !form.elements.part.value; };
  d.addEventListener('cancel', e => e.preventDefault()); // Esc 로 닫지 못한다 — 고르기 전에는 앱을 쓸 수 없다
  form.onsubmit = async e => {
    e.preventDefault();
    btn.disabled = true;
    err.hidden = true;
    try {
      await api('POST', '/api/me/part', { part: form.elements.part.value });
      d.remove();
      route();
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
      btn.disabled = false;
    }
  };
  d.showModal();
}

// ---------- 상태 폼 (단원 본인 입력 · 현황판 수정 시트 공용) ----------
function statusForm(initial, locked) {
  const form = document.createElement('form');
  form.className = 'status-form stack';
  const dis = locked ? 'disabled' : '';
  form.innerHTML = `
    <div class="segment" role="radiogroup" aria-label="출석 상태">
      ${['present', 'late', 'absent'].map(v => `
        <label><input type="radio" name="status" value="${v}" ${initial.status === v ? 'checked' : ''} ${dis}><span>${STATUS[v]}</span></label>`).join('')}
    </div>
    <label class="f-reason">사유 <input name="reason" value="${esc(initial.reason)}" placeholder="예: 수업, 버스 지연" ${dis}></label>
    <label class="f-eta">도착 예정 <input name="eta" type="time" value="${esc(initial.eta)}" ${dis}></label>
    ${locked ? '' : '<button class="btn primary full-width">출석 상태 저장</button>'}`;
  const f = form.elements;
  const sync = () => {
    const st = f.status.value;
    form.dataset.status = st;
    const btn = form.querySelector('button');
    if (btn) btn.disabled = !st || (st === 'late' && !(f.reason.value.trim() && f.eta.value));
  };
  form.oninput = sync;
  sync();
  form.read = () => {
    const st = f.status.value;
    return {
      status: st,
      reason: st === 'present' ? null : (f.reason.value.trim() || null),
      eta: st === 'late' ? f.eta.value : null,
    };
  };
  return form;
}

// ---------- 내 출석 입력 ----------
function describe(me) {
  if (me.status == null) return '미입력';
  let s = STATUS[me.status] + (me.source === 'auto' ? '(자동)' : '');
  if (me.status === 'late') s += ` · ${esc(me.reason)} · 도착 ${esc(me.eta)}`;
  else if (me.reason) s += ` · ${esc(me.reason)}`;
  return s;
}

async function practiceView(id) {
  if (session().role === 'conductor') { location.hash = `#/board/${id}`; return; }
  const list = getState().events;
  const me = getState().my_attendance[id];
  if (location.hash !== `#/practice/${id}`) return;
  const p = list.find(x => x.id === id);
  if (!p || !me) throw new ApiError(404, '출석 대상 일정 없음');
  const started = new Date() >= new Date(`${p.starts_at}+09:00`);
  const closed = p.status === 'closed';
  view.innerHTML = `
    ${backLink()}
    <section class="page-heading">
      <div class="row between"><p class="eyebrow">내 출석</p>${practiceBadge(p)}</div>
      <h1>${esc(p.title)}</h1>
      ${practiceMeta(p)}
    </section>
    <section class="card stack attendance-form-card">
      <div class="current-status"><p class="eyebrow">현재 출석 상태</p><p class="current ${me.status ?? ''}">${describe(me)}</p></div>
      ${!closed && !started ? '<div class="section-heading"><h2>이번 연습, 함께할 수 있나요?</h2><p class="muted">연습 시작 전까지 변경할 수 있어요.</p></div>' : ''}
      ${closed ? '<p class="muted">마감된 연습입니다.</p>'
        : started ? '<p class="muted">연습이 시작돼 파트장·지휘자만 수정할 수 있어요.</p>' : ''}
      <div id="form"></div>
    </section>`;
  const form = statusForm(me, closed || started || getState().stale);
  view.querySelector('#form').replaceWith(form);
  form.onsubmit = async e => {
    e.preventDefault();
    try { await api('PUT', `/practices/${id}/me`, form.read()); toast('저장했어요'); route(); }
    catch (err) { toast(err.message, true); if (err.status === 403 || err.status === 409) route(); }
  };
}

// ---------- 현황판 ----------
const ORDER = { null: 0, late: 1, absent: 2, present: 3 }; // 확인 필요 우선
function sortMembers(members) {
  return [...members].sort((a, b) => ORDER[a.status] - ORDER[b.status]); // 안정 정렬 → 그룹 안은 이름순 유지
}

async function boardView(id) {
  const s = session();
  if (s.role === 'member') { toast('파트장·지휘자만 볼 수 있어요', true); location.hash = '#/home'; return; }
  const conductor = s.role === 'conductor';
  view.innerHTML = `
    ${backLink()}
    <div id="board-head"></div>
    <div id="board-list" class="stack"></div>
    <dialog id="edit" aria-labelledby="edit-name">
      <div class="stack">
        <p class="eyebrow">출석 상태 변경</p>
        <h2 id="edit-name"></h2>
        <div id="edit-form"></div>
        <button type="button" id="edit-cancel" class="btn">취소</button>
      </div>
    </dialog>`;
  const dlg = view.querySelector('#edit');
  view.querySelector('#edit-cancel').onclick = () => dlg.close();
  let data;
  let busy = false;
  let lastList = '';
  let alive = true;

  async function load() {
    if (busy || !alive) return;
    if (!view.querySelector('#board-list')) return; // 뷰가 이미 교체됨
    busy = true;
    try {
      data = getState().boards[id];
      if (!data) throw new ApiError(404, '출석 대상 일정 없음');
    }
    catch (e) {
      if (e.status === 403 || e.status === 404) { toast(e.status === 404 ? '연습이 없어요' : e.message, true); location.hash = '#/home'; }
      else if (!data) { const h = view.querySelector('#board-head'); if (h) h.innerHTML = '<p class="muted">불러오지 못했어요. 다시 시도하는 중…</p>'; }
      return; // 이미 데이터가 있으면 조용히 다음 주기에 재시도
    }
    finally { busy = false; }
    if (alive && view.querySelector('#board-list')) render();
  }

  async function act(promise, okMsg) {
    let ok = false;
    try { await promise; ok = true; if (okMsg) toast(okMsg); }
    catch (e) {
      const mp = e.detail && e.detail.missing_parts;
      toast(mp ? `${mp.map(k => PART[k]).join('·')} 확인이 필요해요` : e.message, true);
    }
    try { await loadOperations(view, { refresh: route, toast }); } catch (e) { toast(e.message, true); }
    load();
    return ok;
  }

  function render() {
    const p = data.practice, open = p.status === 'open' && !getState().stale;
    const parts = PARTS.filter(k => data.parts[k]);
    const missing = parts.filter(k => !data.parts[k].confirmed);
    const allConfirmed = conductor && missing.length === 0;
    const now = new Date().toTimeString().slice(0, 8);
    view.querySelector('#board-head').innerHTML = `
      ${data.roster_warnings.length ? `<div class="warn">명단 확인 필요<br>${data.roster_warnings.map(esc).join('<br>')}</div>` : ''}
      <section class="page-heading board-heading">
        <div class="row between"><p class="eyebrow">${conductor ? '전체 출석 현황' : PART[s.part] + ' 출석 현황'}</p><span class="refresh-label">${now} 갱신</span></div>
        <h1>${esc(p.title)}</h1>
        ${practiceMeta(p)}
      </section>
      <section class="card board-summary">
        <div class="summary-grid">
          <div class="summary-stat present"><span>출석</span><strong>${data.totals.present}</strong></div>
          <div class="summary-stat late"><span>지각</span><strong>${data.totals.late}</strong></div>
          <div class="summary-stat absent"><span>결석</span><strong>${data.totals.absent}</strong></div>
          <div class="summary-stat none"><span>미확정</span><strong>${data.totals.unconfirmed}</strong></div>
        </div>
        ${!conductor ? '' : open ? `
          <div class="board-close">
            <div><p class="confirmation-label">파트 확인 <strong>${parts.length - missing.length} / ${parts.length}</strong></p>
            <p class="muted">${allConfirmed ? '모든 파트 확인이 끝났어요.' : `${missing.map(k => PART[k]).join(' · ')} 확인 대기`}</p></div>
            <button type="button" id="close" class="btn primary" ${allConfirmed ? '' : 'disabled'}>출석 마감</button>
          </div>` : `
          <p class="muted sync-message">${p.notion_synced_at ? `노션 동기화 완료 ${p.notion_synced_at.slice(11, 16)}` : '노션 동기화 중…'}</p>
          <div class="row">
            ${p.notion_synced_at ? '' : '<button type="button" id="resync" class="btn">동기화 재시도</button>'}
            <button type="button" id="reopen" class="btn">재오픈</button>
          </div>`}
      </section>`;
    const html = parts.map(k => {
      const part = data.parts[k], c = part.counts;
      return `
      <section class="part">
        <header class="row between">
          <h2>${PART[k]} <span class="count-label">${part.members.length}명</span><small class="muted">출석 ${c.present} · 지각 ${c.late} · 결석 ${c.absent} · 미확정 ${c.unconfirmed}</small></h2>
          ${part.confirmed ? '<span class="badge done">확인 완료</span>'
            : open ? `<button type="button" class="btn small" data-confirm="${k}">확인 완료</button>` : ''}
        </header>
        <ul class="list">${sortMembers(part.members).map(m => `
          <li class="m ${m.status ?? 'none'}">
            <button type="button" data-member="${m.member_id}" ${open ? '' : 'disabled'}>
              <strong>${esc(m.name)}</strong>
              <span class="chip ${m.status ?? 'none'}">${STATUS[m.status]}${m.source === 'auto' ? ' · 자동' : ''}</span>
              ${m.status === 'late' ? `<span class="muted">${esc(m.reason)} · 도착 ${esc(m.eta)}</span>`
                : m.reason ? `<span class="muted">${esc(m.reason)}</span>` : ''}
            </button>
          </li>`).join('')}</ul>
      </section>`;
    }).join('');
    if (html !== lastList) {
      lastList = html;
      view.querySelector('#board-list').innerHTML = html;
    }
    bind();
  }

  function bind() {
    const q = sel => view.querySelector(sel);
    if (q('#close')) q('#close').onclick = () => {
      if (confirm('마감하면 미확정 단원은 결석 처리됩니다. 마감할까요?')) act(api('POST', `/practices/${id}/close`), '마감했어요');
    };
    if (q('#resync')) q('#resync').onclick = () => act(api('POST', `/practices/${id}/close`), '동기화를 다시 요청했어요');
    if (q('#reopen')) q('#reopen').onclick = () => {
      if (confirm('연습을 다시 열까요?')) act(api('POST', `/practices/${id}/reopen`), '다시 열었어요');
    };
    view.querySelectorAll('[data-confirm]').forEach(b => {
      b.onclick = () => {
        if (confirm(`${PART[b.dataset.confirm]} 확인 완료로 표시할까요?`)) act(api('POST', `/practices/${id}/part/confirm`, { part: b.dataset.confirm }), '확인 완료');
      };
    });
    view.querySelectorAll('[data-member]').forEach(b => {
      b.onclick = () => {
        const mid = b.dataset.member;
        const m = Object.values(data.parts).flatMap(x => x.members).find(x => x.member_id === mid);
        q('#edit-name').textContent = m.name;
        const form = statusForm(m, false);
        q('#edit-form').replaceChildren(form);
        form.onsubmit = async e => {
          e.preventDefault();
          const btn = form.querySelector('button');
          if (btn) btn.disabled = true;
          const ok = await act(api('PUT', `/practices/${id}/members/${mid}`, form.read()), '저장했어요');
          if (ok) dlg.close();
          else if (btn) btn.disabled = false;
        };
        dlg.showModal();
      };
    });
  }

  // The header refresh button reloads Notion. Avoid polling every database per 5 seconds.
  load();
  return () => { alive = false; };
}

// ---------- 라우터 ----------
const routes = [
  [/^#\/login$/, loginView],
  [/^#\/home$/, operationsHome],
  [/^#\/schedule$/, operationsCalendar],
  [/^#\/day\/(\d{4}-\d{2}-\d{2})$/, dayView],
  [/^#\/event\/([\w-]+)$/, eventView],
  [/^#\/admin$/, adminView],
  [/^#\/music$/, musicView],
  [/^#\/concert\/([\w-]+)$/, concertView],
  [/^#\/song\/([\w-]+)$/, songView],
  [/^#\/finance$/, financeView],
  [/^#\/settings$/, settingsView],
  [/^#\/practice\/([\w-]+)$/, practiceView],
  [/^#\/board\/([\w-]+)$/, boardView],
];

let generation = 0;

async function route() {
  if (location.hash && !location.hash.startsWith('#/')) return; // #view 같은 일반 앵커(스킵링크)는 브라우저에 맡김
  const gen = ++generation;
  if (cleanup) { cleanup(); cleanup = null; }
  const hash = location.hash || '#/home';
  const match = routes.find(([re]) => re.test(hash));
  if (!match) { location.hash = '#/home'; return; }
  const [re, fn] = match;
  if (fn !== loginView && !session()) { location.hash = '#/login'; return; }
  renderHeader();
  view.innerHTML = '<p class="muted">불러오는 중…</p>';
  try {
    if (fn !== loginView) {
      await loadOperations(view, { refresh: route, toast, isCurrent: () => gen === generation });
      if (gen !== generation) return;
      // 파트를 고르기 전에는 어떤 화면도 그리지 않는다. 창은 고른 뒤 route() 를 다시 돌린다.
      if (!getState().me.part) { if (!document.querySelector('.part-picker')) partPicker(); return; }
    }
    const done = (await fn(...hash.match(re).slice(1))) || null;
    if (gen !== generation) { if (done) done(); return; } // 그 사이 다른 화면으로 이동
    cleanup = done;
  } catch (e) {
    if (gen !== generation) return;
    if (e.status === 404) { toast('연습이 없어요', true); location.hash = '#/home'; }
    else if (e.status !== 401) { toast(e.message, true); failed(); }
  }
}
window.addEventListener('hashchange', route);
route();
