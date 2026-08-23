import { api, session, setSession, clearSession, esc, fmtDate, PART, PARTS, ROLE, STATUS, ApiError } from './api.js';

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
  document.getElementById('user').textContent = s ? `${s.name} · ${PART[s.part]} · ${ROLE[s.role]}` : '';
  document.getElementById('logout').hidden = !s;
}
document.getElementById('logout').onclick = () => { clearSession(); location.hash = '#/login'; };

// ---------- 로그인 ----------
async function loginView() {
  if (session()) { location.hash = '#/home'; return; }
  view.innerHTML = `
    <form id="login" class="card stack">
      <p class="eyebrow">이름과 학번으로 로그인</p>
      <label>이름 <input name="name" required autocomplete="name"></label>
      <label>학번 <input name="student_id" required autocomplete="off"></label>
      <p id="login-err" class="err" hidden>명단에 없어요. 이름과 학번을 확인하세요.</p>
      <button class="btn primary">로그인</button>
    </form>`;
  view.querySelector('#login').onsubmit = async e => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      setSession(await api('POST', '/auth/login', { name: f.name.value, student_id: f.student_id.value }));
      location.hash = '#/home';
    } catch (err) {
      if (err.status === 401) view.querySelector('#login-err').hidden = false;
      else toast(err.message, true);
    }
  };
}

// ---------- 홈 ----------
function practiceLink(p, role) {
  return role === 'member' ? `#/practice/${p.id}` : `#/board/${p.id}`;
}

function nextPractice(list) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const open = list.filter(p => p.status === 'open');
  const upcoming = open.filter(p => new Date(p.starts_at) >= today)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  return upcoming[0] || open[0] || null; // 목록은 최신순이라 open[0]이 가장 최근
}

function when(p) { return `${fmtDate(p.starts_at)}${p.place ? ' · ' + esc(p.place) : ''}`; }

async function homeView() {
  const s = session();
  const list = await api('GET', '/practices');
  const stats = await api('GET', '/me/stats');
  if (!location.hash.startsWith('#/home') && location.hash !== '') return;
  const next = nextPractice(list);
  const staff = s.role !== 'member';
  const conductor = s.role === 'conductor';
  view.innerHTML = `
    ${next ? `
    <section class="card">
      <p class="eyebrow">다음 연습</p>
      <h2 class="display">${esc(next.title)}</h2>
      <p>${when(next)}</p>
      <div class="row">
        <a class="btn primary" href="#/practice/${next.id}">내 출석 입력</a>
        ${staff ? `<a class="btn" href="#/board/${next.id}">현황판</a>` : ''}
      </div>
    </section>` : ''}
    <section class="card">
      <p class="eyebrow">내 출석률</p>
      ${stats.total
        ? `<p class="big">${Math.round(stats.rate * 100)}<span>%</span></p>
           <p class="muted">출석 ${stats.present} · 지각 ${stats.late} · 결석 ${stats.absent} / 총 ${stats.total}</p>`
        : '<p class="muted">아직 마감된 연습이 없어요</p>'}
    </section>
    <section class="stack">
      <div class="row between">
        <h2>연습</h2>
        ${conductor ? '<button type="button" id="new" class="btn small">새 연습</button>' : ''}
      </div>
      ${list.length ? `<ul class="list">${list.map(p => `
        <li class="${p.status}">
          <a href="${practiceLink(p, s.role)}">
            <strong>${esc(p.title)}</strong>
            <span class="muted">${when(p)}</span>
          </a>
          <span class="badge">${p.status === 'open' ? '진행중' : '마감'}</span>
          ${conductor && p.status === 'open' ? `
            <button type="button" class="icon" data-edit="${p.id}" aria-label="수정">✎</button>
            <button type="button" class="icon" data-del="${p.id}" aria-label="삭제">✕</button>` : ''}
        </li>`).join('')}</ul>` : '<p class="muted">연습이 없어요</p>'}
    </section>
    <dialog id="pform" aria-labelledby="pform-title">
      <form class="stack">
        <h2 id="pform-title">새 연습</h2>
        <label>제목 <input name="title" required></label>
        <label>시작 <input name="starts_at" type="datetime-local" required></label>
        <label>장소 <input name="place"></label>
        <div class="row">
          <button type="button" id="pform-cancel" class="btn">취소</button>
          <button class="btn primary">저장</button>
        </div>
      </form>
    </dialog>`;

  if (!conductor) return;
  const dlg = view.querySelector('#pform');
  const form = dlg.querySelector('form');
  const f = form.elements; // form.title은 HTML 속성이라 elements로 접근
  const openForm = p => {
    form.reset();
    form.dataset.id = p ? p.id : '';
    dlg.querySelector('#pform-title').textContent = p ? '연습 수정' : '새 연습';
    if (p) { f.title.value = p.title; f.starts_at.value = p.starts_at.slice(0, 16); f.place.value = p.place; }
    dlg.showModal();
  };
  view.querySelector('#new').onclick = () => openForm(null);
  view.querySelector('#pform-cancel').onclick = () => dlg.close();
  view.querySelectorAll('[data-edit]').forEach(b => {
    b.onclick = () => openForm(list.find(p => p.id === Number(b.dataset.edit)));
  });
  view.querySelectorAll('[data-del]').forEach(b => {
    b.onclick = async () => {
      if (!confirm('이 연습을 삭제할까요?')) return;
      try { await api('DELETE', `/practices/${b.dataset.del}`); toast('삭제했어요'); route(); }
      catch (e) { toast(e.message, true); }
    };
  });
  form.onsubmit = async e => {
    e.preventDefault();
    const id = form.dataset.id;
    const body = { title: f.title.value, starts_at: f.starts_at.value, place: f.place.value };
    try {
      await api(id ? 'PUT' : 'POST', id ? `/practices/${id}` : '/practices', body);
      dlg.close(); toast('저장했어요'); route();
    } catch (err) { toast(err.message, true); }
  };
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
    ${locked ? '' : '<button class="btn primary">저장</button>'}`;
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
  const list = await api('GET', '/practices');
  const me = await api('GET', `/practices/${id}/me`);
  if (location.hash !== `#/practice/${id}`) return;
  const p = list.find(x => x.id === id);
  if (!p) throw new ApiError(404, '연습 없음');
  const started = new Date() >= new Date(p.starts_at);
  const closed = p.status === 'closed';
  view.innerHTML = `
    <section class="card">
      <p class="eyebrow">${closed ? '마감' : '진행중'}</p>
      <h1 class="display">${esc(p.title)}</h1>
      <p>${when(p)}</p>
    </section>
    <section class="card stack">
      <p class="eyebrow">내 상태</p>
      <p class="current ${me.status ?? ''}">${describe(me)}</p>
      ${closed ? '<p class="muted">마감된 연습입니다.</p>'
        : started ? '<p class="muted">연습이 시작돼 파트장·지휘자만 수정할 수 있어요.</p>' : ''}
      <div id="form"></div>
    </section>`;
  const form = statusForm(me, closed || started);
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
    <div id="board-head"></div>
    <div id="board-list" class="stack"></div>
    <dialog id="edit" aria-labelledby="edit-name">
      <div class="stack">
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

  async function load() {
    if (busy) return;
    if (!view.querySelector('#board-list')) return; // 뷰가 이미 교체됨
    busy = true;
    try { data = await api('GET', `/practices/${id}/board`); }
    catch (e) {
      if (e.status === 403 || e.status === 404) { toast(e.status === 404 ? '연습이 없어요' : e.message, true); location.hash = '#/home'; }
      else if (!data) { const h = view.querySelector('#board-head'); if (h) h.innerHTML = '<p class="muted">불러오지 못했어요. 다시 시도하는 중…</p>'; }
      return; // 이미 데이터가 있으면 조용히 다음 주기에 재시도
    }
    finally { busy = false; }
    if (view.querySelector('#board-list')) render();
  }

  async function act(promise, okMsg) {
    let ok = false;
    try { await promise; ok = true; if (okMsg) toast(okMsg); }
    catch (e) {
      const mp = e.detail && e.detail.missing_parts;
      toast(mp ? `${mp.map(k => PART[k]).join('·')} 확인이 필요해요` : e.message, true);
    }
    load();
    return ok;
  }

  function render() {
    const p = data.practice, open = p.status === 'open';
    const parts = PARTS.filter(k => data.parts[k]);
    const missing = parts.filter(k => !data.parts[k].confirmed);
    const allConfirmed = conductor && missing.length === 0;
    const now = new Date().toTimeString().slice(0, 8);
    view.querySelector('#board-head').innerHTML = `
      ${data.roster_warnings.length ? `<div class="warn">명단 확인 필요<br>${data.roster_warnings.map(esc).join('<br>')}</div>` : ''}
      <section class="card">
        <p class="eyebrow">${open ? '진행중' : '마감'} · 갱신 ${now}</p>
        <h1 class="display">${esc(p.title)}</h1>
        <p>${when(p)}</p>
        <div class="chips">
          <span class="chip present">출석 ${data.totals.present}</span>
          <span class="chip late">지각 ${data.totals.late}</span>
          <span class="chip absent">결석 ${data.totals.absent}</span>
          <span class="chip none">미확정 ${data.totals.unconfirmed}</span>
        </div>
        ${!conductor ? '' : open ? `
          <div class="row" style="margin-top:12px">
            <button type="button" id="close" class="btn primary" ${allConfirmed ? '' : 'disabled'}>마감</button>
            ${allConfirmed ? '' : `<p class="muted">${missing.map(k => PART[k]).join('·')} 확인 대기</p>`}
          </div>` : `
          <p class="muted" style="margin-top:12px">${p.notion_synced_at ? `노션 동기화 완료 ${p.notion_synced_at.slice(11, 16)}` : '노션 동기화 중…'}</p>
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
          <h2>${PART[k]}<small class="muted">출석 ${c.present} · 지각 ${c.late} · 결석 ${c.absent} · 미확정 ${c.unconfirmed}</small></h2>
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
        const mid = Number(b.dataset.member);
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

  const timer = setInterval(load, 5000);
  load();
  return () => clearInterval(timer);
}

// ---------- 라우터 ----------
const routes = [
  [/^#\/login$/, loginView],
  [/^#\/home$/, homeView],
  [/^#\/practice\/(\d+)$/, practiceView],
  [/^#\/board\/(\d+)$/, boardView],
];

let generation = 0;

async function route() {
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
    const done = (await fn(...hash.match(re).slice(1).map(Number))) || null;
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
