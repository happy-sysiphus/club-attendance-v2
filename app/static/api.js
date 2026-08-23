export const PARTS = ['soprano', 'alto', 'tenor', 'bass'];
export const PART = { soprano: '소프라노', alto: '알토', tenor: '테너', bass: '베이스' };
export const ROLE = { member: '단원', part_leader: '파트장', conductor: '지휘자' };
export const STATUS = { present: '출석', late: '지각', absent: '결석', null: '미확정' };

export function session() {
  try { return JSON.parse(localStorage.getItem('session')); } catch { return null; }
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

export async function api(method, path, body) {
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
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getMonth() + 1}/${d.getDate()} (${DAYS[d.getDay()]}) ${hh}:${mm}`;
}
