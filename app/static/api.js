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
export function setSession(s) { localStorage.setItem('session', JSON.stringify(s)); }
export function clearSession() { localStorage.removeItem('session'); }

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
