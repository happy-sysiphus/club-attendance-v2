import { api, session, esc, fmtDate, todayKst, STATUS } from './api.js';

// Figma에서 내보낸 원본 아이콘. 글리 로고도 제공받은 JPG 원본을 사용한다.
export function icon(name, extra = '') {
  return `<img class="ui-icon ${extra}" src="/assets/${name}.svg" alt="" width="20" height="20">`;
}

export function dateTile(iso) {
  const [, month, day] = iso.slice(0, 10).split('-').map(Number);
  return `<span class="date-tile" aria-hidden="true"><small>${month}월</small><strong>${day}</strong></span>`;
}

export function practiceBadge(p) {
  if (p.status === 'closed') return '<span class="badge">마감</span>';
  const date = p.starts_at.slice(0, 10);
  if (date === todayKst()) return '<span class="badge active">오늘</span>';
  return `<span class="badge ${date > todayKst() ? 'upcoming' : ''}">${date > todayKst() ? '예정' : '진행중'}</span>`;
}

export function practiceMeta(p) {
  return `<p class="practice-meta">${fmtDate(p.starts_at)}<span class="meta-divider" aria-hidden="true">·</span>${esc(p.place || '장소 미정')}</p>`;
}

export function backLink() {
  return `<a href="#/home" class="back-link">${icon('chevron-left')}출석으로 돌아가기</a>`;
}

export function emptyState(title, description = '') {
  return `<div class="empty-state">${icon('calendar')}<strong>${esc(title)}</strong>${description ? `<p class="muted">${esc(description)}</p>` : ''}</div>`;
}

// 본인 출석 잠금 안내. 반주자 파트는 지휘자가 확인하고, 파트장은 잠긴 뒤에도 현황판에서 직접 고친다.
export function lockCopy(me) {
  if (me.part === 'accompanist') return { open: '지휘자가 확인하기 전까지 바꿀 수 있어요.', locked: '바꿀 내용은 지휘자에게 알려 주세요.' };
  if (me.role === 'part_leader') return { open: '확인 완료를 누르기 전까지 바꿀 수 있어요.', locked: '고칠 내용은 우리 파트 현황에서 바꿀 수 있어요.' };
  return { open: '파트장이 확인하기 전까지 바꿀 수 있어요.', locked: '바꿀 내용은 파트장에게 알려 주세요.' };
}

// 출석 상태 한 줄 요약. 내 출석 화면·홈 카드가 같이 쓴다.
export function describe(me) {
  if (me.status == null) return '미입력';
  let s = STATUS[me.status] + (me.source === 'auto' ? '(자동)' : '');
  if (me.status === 'late') s += ` · ${esc(me.reason)} · 도착 ${esc(me.eta)}`;
  else if (me.reason) s += ` · ${esc(me.reason)}`;
  return s;
}

// ---------- 출석 상태 폼 (홈 카드 · 내 출석 · 현황판 수정 창 공용) ----------
// draftKey 가 있으면 고르던 상태와 적던 사유를 기억한다. 같은 화면이 실시간 갱신으로 다시 그려져도 입력이 남게 하려는 것뿐이라,
// 초안은 그 초안을 시작할 때의 서버 값(base)과 함께 둔다. 서버 값이 바뀌었거나(다른 기기·파트장 수정) 화면을 옮기면 버린다.
const drafts = new Map();   // key → { base, value }
const saving = new Set();   // 저장 중인 key: 다시 그려진 폼도 버튼을 끈 채로 둔다 (중복 저장 방지)
export const clearDrafts = () => drafts.clear();   // 화면 이동·로그아웃 때 app.js 가 부른다
const baseOf = x => JSON.stringify([x?.status ?? null, x?.reason ?? null, x?.eta ?? null]);

export function statusForm(initial, locked, draftKey) {
  const base = baseOf(initial);   // 초안을 합치기 전의 서버 값
  const draft = !locked && draftKey && drafts.get(draftKey);
  if (draft && draft.base === base) initial = { ...initial, ...draft.value };
  else if (draftKey) drafts.delete(draftKey);
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
    if (btn) btn.disabled = (draftKey && saving.has(draftKey)) || !st || (st === 'late' && !(f.reason.value.trim() && f.eta.value));
  };
  form.oninput = () => {
    sync();
    if (draftKey) drafts.set(draftKey, { base, value: { status: f.status.value || null, reason: f.reason.value, eta: f.eta.value } });
  };
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

// 단원 본인 입력: 홈 카드와 '내 출석' 화면이 같은 폼·같은 저장을 쓴다.
// 시작 후 아무것도 안 누른 '결석(자동)'은 본인이 고른 게 아니므로, 아직 바꿀 수 있으면 선택하지 않은 채로 연다.
export function myStatusForm(practiceId, mine, locked, toast, refresh) {
  const key = `me:${session()?.id}:${practiceId}`;   // 같은 기기에서 다른 단원이 로그인해도 초안이 섞이지 않게
  const initial = mine?.source === 'auto' && !locked ? { ...mine, status: null, reason: null, eta: null } : (mine || {});
  const form = statusForm(initial, locked, key);
  form.onsubmit = async e => {
    e.preventDefault();
    if (saving.has(key)) return;
    saving.add(key);
    const button = form.querySelector('button');
    if (button) button.disabled = true;
    try {
      await api('PUT', `/practices/${practiceId}/me`, form.read());
      drafts.delete(key);
      saving.delete(key);
      toast('저장했어요');
      await refresh();
    } catch (err) {
      saving.delete(key);
      toast(err.message, true);
      if (err.status === 403 || err.status === 409) { drafts.delete(key); await refresh(); } // 그 사이 잠겼거나 마감됨
      else if (button) button.disabled = false;
    }
  };
  return form;
}
