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

// ---------- 임시 홈 (Task 3에서 교체) ----------
async function homeView() {
  const s = session();
  view.innerHTML = `<section class="card"><h1 class="display">${esc(s.name)}</h1><p class="muted">홈은 Task 3에서 만든다</p></section>`;
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
