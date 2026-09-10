export const PARTS = ['soprano', 'alto', 'tenor', 'bass', 'accompanist'];
export const PART = { soprano: '소프라노', alto: '알토', tenor: '테너', bass: '베이스', accompanist: '반주자', conductor: '지휘자' };
export const ROLE = { member: '단원', part_leader: '파트장', conductor: '지휘자' };
export const STATUS = { present: '출석', late: '지각', absent: '결석', null: '미확정' };

export function session() {
  try {
    const s = JSON.parse(localStorage.getItem('session'));
    // 기존 브라우저에 남은 지휘자 성부 표시도 새 분류에 맞춘다.
    if (s?.role === 'conductor') s.part = 'conductor';
    if (s?.part === 'accompanist') s.role = 'member';
    return s;
  } catch { return null; }
}
export function setSession(s) {
  localStorage.setItem('session', JSON.stringify(s));
  // 분석 도구가 차단·미로딩이어도 로그인은 그대로 동작해야 한다 — 실패는 조용히 무시.
  try { window.mixpanel?.identify(s.id); window.mixpanel?.people.set({ part: s.part, role: s.role, admin_role: s.admin_role || '' }); } catch { /* 무시 */ }
}
export function clearSession() {
  localStorage.removeItem('session');
  try { window.mixpanel?.reset(); } catch { /* 무시 */ }
}

// 이름·학번·자유 텍스트(사유·비고 등)는 절대 보내지 않는다. 상태값과 경로 종류만.
export function track(event, props) {
  try { window.mixpanel?.track(event, props); } catch { /* 무시 */ }
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

let readOnly = false;
export function setReadOnly(value) { readOnly = Boolean(value); }
export function isReadOnly() { return readOnly; }

export async function api(method, path, body) {
  if (readOnly && !['GET', 'HEAD'].includes(method) && !path.startsWith('/auth/')) {
    throw new ApiError(503, '최신 정보가 아니에요. 연결을 복구한 뒤 다시 저장해 주세요.');
  }
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    });
  } catch {
    throw new ApiError(0, '서버에 연결하지 못했어요');
  }
  if (res.status === 401) {
    clearSession();
    location.hash = '#/login';
    throw new ApiError(401, '로그인 필요');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail ?? res.statusText);
  // 핵심 행동 몇 가지만 여기 한 곳에서 추적한다 — 저장 지점마다 손대지 않도록.
  // 값이 아니라 종류만 보낸다: 상태(출석/지각/결석)와 누가 입력했는지(본인/파트장·지휘자).
  if (path === '/auth/login') track('login');
  else if (path === '/auth/logout') track('logout');
  else if (method === 'PUT' && body?.status && /^\/practices\/[\w-]+\/(me|members\/[\w-]+)$/.test(path)) {
    track('attendance_marked', { status: body.status, source: path.includes('/members/') ? 'staff' : 'self' });
  }
  return data;
}

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ESC[c]); }

const DAYS = '일월화수목금토';
export function fmtDate(iso) {
  // API의 날짜는 KST-naive. 기기의 시간대와 무관하게 같은 날짜를 표시한다.
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return `${month}/${day} (${DAYS[weekday]}) ${iso.slice(11, 16)}`;
}

export function todayKst() {
  return new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export function practiceLink(p, role) {
  return role === 'member' ? `#/practice/${p.id}` : `#/board/${p.id}`;
}
