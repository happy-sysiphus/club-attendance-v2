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
  const [list, stats] = await Promise.all([api('GET', '/practices'), api('GET', '/me/stats')]);
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
    <dialog id="pform">
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

// ---------- 라우터 ----------
const routes = [
  [/^#\/login$/, loginView],
  [/^#\/home$/, homeView],
];

async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  const hash = location.hash || '#/home';
  const match = routes.find(([re]) => re.test(hash));
  if (!match) { location.hash = '#/home'; return; }
  const [re, fn] = match;
  if (fn !== loginView && !session()) { location.hash = '#/login'; return; }
  renderHeader();
  view.innerHTML = '<p class="muted">불러오는 중…</p>';
  try {
    cleanup = (await fn(...hash.match(re).slice(1).map(Number))) || null;
  } catch (e) {
    if (e.status === 404) { toast('연습이 없어요', true); location.hash = '#/home'; }
    else if (e.status !== 401) toast(e.message, true);
  }
}
window.addEventListener('hashchange', route);
route();
