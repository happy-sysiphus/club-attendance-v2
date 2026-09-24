import { api, session, setSession, clearSession, track, esc, fmtDate, todayKst, PART, PARTS, ROLE, STATUS, ApiError } from './api.js';
import { icon, dateTile, practiceBadge, practiceMeta, backLink, emptyState, describe, lockCopy, statusForm, myStatusForm, clearDrafts } from './ui.js';
import { loadOperations, showCached, getState, operationsHome, operationsCalendar, eventView, dayView, adminView, suggestionsView } from './operations-ui.js';
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
  finally { clearSession(); clearDrafts(); sessionStorage.removeItem('glee-semester'); changeSource?.close(); location.hash = '#/login'; }
};

// ---------- 로그인 ----------
async function loginView() {
  const toolbar = document.getElementById('semester-toolbar');
  if (toolbar) toolbar.hidden = true;
  if (session()) { location.hash = '#/home'; return; }
  view.innerHTML = `
    <section class="login-brand">
      <span class="logo-window login-logo"><img src="/assets/glee-logo.svg" alt="Glee — Choir Club of Ajou" width="1256" height="778"></span>
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

// ---------- 내 출석 입력 ----------
async function practiceView(id) {
  if (session().role === 'conductor') { location.hash = `#/board/${id}`; return; }
  const list = getState().events;
  const me = getState().my_attendance[id];
  if (location.hash !== `#/practice/${id}`) return;
  const p = list.find(x => x.id === id);
  if (!p || !me) throw new ApiError(404, '출석 대상 일정 없음');
  const closed = p.status === 'closed';
  const confirmed = !!p.confirmations?.[getState().me.part]; // 시작 시각이 아니라 파트 확인이 잠금 기준
  const hint = lockCopy(getState().me);
  const noun = p.category === '지휘' ? '연습' : '일정'; // 출석 받는 행정 일정도 이 화면을 쓴다
  view.innerHTML = `
    ${backLink()}
    <section class="page-heading">
      <div class="row between"><p class="eyebrow">내 출석</p>${practiceBadge(p)}</div>
      <h1>${esc(p.title)}</h1>
      ${practiceMeta(p)}
    </section>
    <section class="card stack attendance-form-card">
      <div class="current-status"><p class="eyebrow">현재 출석 상태</p><p class="current ${me.status ?? ''}">${describe(me)}</p></div>
      ${!closed && !confirmed ? `<div class="section-heading"><h2>이번 ${noun}, 함께할 수 있나요?</h2><p class="muted">${hint.open}</p></div>` : ''}
      ${closed ? `<p class="muted">마감된 ${noun}입니다.</p>`
        : confirmed ? `<p class="muted">파트 확인이 끝나 여기서는 바꿀 수 없어요. ${hint.locked}</p>` : ''}
      <div id="form"></div>
    </section>`;
  view.querySelector('#form').replaceWith(myStatusForm(id, me, closed || confirmed || getState().stale, toast, route));
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
  let seenAt = ''; // data 를 받은 스냅숏의 조회 시각. 화면을 안 갈아 끼우고 ui.state 만 새로워질 수 있어 data 와 같이 잡아 둔다
  let busy = false;
  let lastList = '';
  let alive = true;

  async function load() {
    if (busy || !alive) return;
    if (!view.querySelector('#board-list')) return; // 뷰가 이미 교체됨
    busy = true;
    try {
      data = getState().boards[id]; seenAt = getState().loaded_at;
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
    if (alive) load(); else route(true); // 저장하는 사이 뒤에서 온 스냅숏이 화면을 새로 그렸으면 이 인스턴스는 죽어 있다
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
            <div class="segment quick-status" role="group" aria-label="${esc(m.name)} 출석">
              ${['present', 'late', 'absent'].map(v => `<button type="button" data-quick="${m.member_id}" data-status="${v}" aria-pressed="${m.status === v}" ${open ? '' : 'disabled'}>${STATUS[v]}</button>`).join('')}
            </div>
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
        if (confirm(`${PART[b.dataset.confirm]} 확인 완료로 표시할까요?`)) act(api('POST', `/practices/${id}/part/confirm`, { part: b.dataset.confirm, seen_at: seenAt }), '확인 완료'); // 이 화면에 그린 데이터의 조회 시각. 그 뒤 바뀐 입력이 있으면 서버가 409
      };
    });
    const member = mid => Object.values(data.parts).flatMap(x => x.members).find(x => x.member_id === mid);
    // 전체 폼 모달. 이름을 누르거나(사유 입력용) 줄의 '지각'을 눌렀을 때(사유·도착시간 필수) 연다.
    function openEdit(m, status = m.status) {
      q('#edit-name').textContent = m.name;
      const form = statusForm({ ...m, status }, false);
      q('#edit-form').replaceChildren(form);
      form.onsubmit = async e => {
        e.preventDefault();
        const btn = form.querySelector('button');
        if (btn) btn.disabled = true;
        const ok = await act(api('PUT', `/practices/${id}/members/${m.member_id}`, form.read()), '저장했어요');
        if (ok) dlg.close();
        else if (btn) btn.disabled = false;
      };
      dlg.showModal();
    }
    view.querySelectorAll('[data-member]').forEach(b => { b.onclick = () => openEdit(member(b.dataset.member)); });
    // 줄의 출석·결석은 한 번에 저장, 지각만 모달. 버튼이라 눌린 표시는 서버 상태에서만 오고, 실패해도 되돌릴 게 없다.
    view.querySelectorAll('[data-quick]').forEach(b => {
      b.onclick = () => {
        const m = member(b.dataset.quick), status = b.dataset.status;
        if (status === m.status) return;
        if (status === 'late') { openEdit(m, 'late'); return; }
        act(api('PUT', `/practices/${id}/members/${m.member_id}`, { status }), `${m.name} · ${STATUS[status]}`);
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
  [/^#\/suggest$/, suggestionsView],
  [/^#\/practice\/([\w-]+)$/, practiceView],
  [/^#\/board\/([\w-]+)$/, boardView],
];

let generation = 0;
let lastHash = '';
let redraw = null;      // 지금 화면을 다시 그리는 함수 (실시간 갱신용)
let staleView = false;  // 새 스냅숏은 받았는데 입력 중이라 화면을 못 갈아 끼운 상태
// 입력 중이거나 화면 안의 창(현황판 수정 창)이 열려 있으면 다시 그리지 않는다 — 쓰던 내용이 사라진다.
// :focus 는 창이 뒤에 있으면 안 맞는다(쓰다가 다른 앱에 다녀온 경우) → activeElement 로 본다.
const editing = () => (view.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) || !!view.querySelector('dialog[open]');

// quick: 화면 이동(hashchange). 직전 스냅숏으로 바로 그리고, 새 스냅숏은 뒤에서 받아 내용이 달라졌을 때만 다시 그린다.
// 그 외(첫 진입·저장 직후·새로고침·학기 변경)는 예전처럼 최신 스냅숏을 기다린다.
async function route(quick = false) {
  if (location.hash && !location.hash.startsWith('#/')) return; // #view 같은 일반 앵커(스킵링크)는 브라우저에 맡김
  const gen = ++generation;
  staleView = false;
  if (cleanup) { cleanup(); cleanup = null; }
  const hash = location.hash || '#/home';
  if (hash !== lastHash) clearDrafts(); // 출석 입력 초안은 같은 화면을 다시 그릴 때만 남긴다
  lastHash = hash;
  const match = routes.find(([re]) => re.test(hash));
  if (!match) { location.hash = '#/home'; return; }
  const [re, fn] = match;
  if (fn !== loginView && !session()) { location.hash = '#/login'; return; }
  track('page_view', { route: hash.split('/')[1] || 'home' });
  renderHeader();
  const show = async () => {
    if (cleanup) { cleanup(); cleanup = null; } // 같은 화면을 두 번 그릴 수 있다 (즉시 + 갱신)
    const done = (await fn(...hash.match(re).slice(1))) || null;
    if (gen !== generation) { if (done) done(); return; } // 그 사이 다른 화면으로 이동
    cleanup = done;
  };
  redraw = fn === loginView ? null : show;
  let shown = false; // 직전 스냅숏으로 이미 화면을 그렸는가
  try {
    if (fn === loginView) { view.innerHTML = ''; await show(); return; }
    const loading = loadOperations(view, { refresh: route, toast, isCurrent: () => gen === generation });
    loading.catch(() => {}); // 즉시 그리기가 먼저 실패해도 '처리 안 된 거부' 경고가 남지 않게. 아래 await 가 같은 오류를 다시 받는다.
    const instant = quick === true && showCached();
    if (instant) { await show(); shown = true; } else view.innerHTML = '<p class="muted">불러오는 중…</p>';
    const changed = await loading;
    if (gen !== generation) return;
    // 파트를 고르기 전에는 어떤 화면도 그리지 않는다. 창은 고른 뒤 route() 를 다시 돌린다.
    if (!getState().me.part) { if (!document.querySelector('.part-picker')) partPicker(); return; }
    if (!instant) await show(); else if (changed) await redrawWhenIdle();
    watchChanges();
  } catch (e) {
    if (gen !== generation) return;
    if (e.status === 404) { toast('연습이 없어요', true); location.hash = '#/home'; }
    else if (e.status !== 401) { toast(e.message, true); if (!shown) failed(); } // 이미 그린 화면은 갱신 실패로 지우지 않는다
  }
}

// 입력이 끝날 때까지 기다렸다가 다시 그린다. 그 사이 다른 화면으로 가면 route() 가 staleView 를 내려 그만둔다.
async function redrawWhenIdle() {
  if (!editing()) { staleView = false; if (redraw) await redraw(); return; }
  if (staleView) return; // 이미 기다리는 중
  staleView = true;
  const timer = setInterval(() => {
    if (!staleView) clearInterval(timer);
    else if (!editing()) { clearInterval(timer); staleView = false; if (redraw) redraw(); }
  }, 1500);
}

// ---------- 실시간 반영 ----------
// 누군가 저장하면 서버가 /api/changes(SSE)로 번호를 보낸다. 번호가 바뀌면 스냅숏을 다시 받아 달라졌을 때만 다시 그린다.
// 첫 메시지는 기준 번호. 끊겼다 다시 붙으면(화면 잠금·터널·재배포) 그 사이 번호가 달라져 있어 놓친 저장도 따라잡는다.
let changeSource = null, lastChange = null, refreshTimer = null;
function watchChanges() {
  if (changeSource && changeSource.readyState !== EventSource.CLOSED) return;
  changeSource = new EventSource('/api/changes');
  changeSource.onmessage = e => {
    const known = lastChange !== null && lastChange !== e.data;
    lastChange = e.data;
    if (known) refreshSoon();
  };
}
// ponytail: 저장 1건에 열린 화면 전부가 /api/state 를 다시 읽는다(30명 규모 전제). 0.3~1.5초로 흩고 몰린 알림은 한 번으로 합친다.
// 단원이 크게 늘면 알림에 바뀐 일정 ID를 실어 해당 화면만 읽게 한다.
function refreshSoon() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(async () => {
    refreshTimer = null;
    if (!session() || !getState() || !redraw) return;
    const gen = generation;
    try {
      const changed = await loadOperations(view, { refresh: route, toast, isCurrent: () => gen === generation });
      if (gen === generation && changed) await redrawWhenIdle();
    } catch { /* 조용히 넘어간다. 다음 알림이나 화면 이동 때 다시 받는다 */ }
  }, 300 + Math.random() * 1200);
}
// 화면을 다시 볼 때(앱 전환·잠금 해제) 한 번 따라잡는다. 멈춰 있던 연결은 끊긴 줄 모르고 있을 수 있다.
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshSoon(); });

window.addEventListener('hashchange', () => route(true));
route();
