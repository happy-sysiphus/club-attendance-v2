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
// ---------- 사용 통계 (Mixpanel) ----------
// 공식 ES 모듈 빌드를 동적 import 한다. 정적 import 면 1.1MB 를 받는 동안 로그인 화면이
// 안 뜨고, 예전 <script src> 2줄 방식은 stub 없이는 window.mixpanel 을 만들지 않는다.
// 로드 전 호출은 큐에 담고, 차단되면(광고 차단기·구형 브라우저·오프라인) 조용히 버린다.
const MIXPANEL_TOKEN = '2a63dae296de3eb701023acef425dcb8';   // 공개 토큰. 쓰기 전용이라 노출돼도 된다
let mp = null;
let queued = [];
function withMixpanel(fn) {
  if (mp) { try { fn(mp); } catch { /* 통계 실패가 앱을 막지 않는다 */ } }
  else if (queued) queued.push(fn);
}
import('https://cdn.mxpnl.com/libs/mixpanel-js/dist/mixpanel.module.js').then(m => {
  mp = m.default;
  mp.init(MIXPANEL_TOKEN, {
    // 세션 리플레이. 기본값이 0 이라 켜 주지 않으면 녹화가 시작되지 않는다.
    // 30명 규모라 표본을 줄일 이유가 없다.
    record_sessions_percent: 100,
    // 마스킹은 기본값을 그대로 둔다(record_mask_all_text: true). 이름·학번·금액이
    // 전부 가려지고 화면 구조와 조작 위치만 남는다 — 동선 확인엔 그걸로 충분하다.
    // 녹화 엔진(rrweb)은 이 모듈에 포함돼 있어 별도 번들을 받지 않는다.
  });
  const waiting = queued;
  queued = null;
  waiting.forEach(fn => { try { fn(mp); } catch { /* 무시 */ } });
}).catch(() => { queued = null; });

export function setSession(s) {
  localStorage.setItem('session', JSON.stringify(s));
  // 이름·학번이 아니라 노션 페이지 UUID 로 식별한다. 파트·역할만 사람 속성으로.
  withMixpanel(m => { m.identify(s.id); m.people.set({ part: s.part, role: s.role, admin_role: s.admin_role || '' }); });
}
export function clearSession() {
  localStorage.removeItem('session');
  withMixpanel(m => m.reset());
}

// 이름·학번·자유 텍스트(사유·비고 등)는 절대 보내지 않는다. 상태값과 경로 종류만.
export function track(event, props) {
  withMixpanel(m => m.track(event, props));
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
