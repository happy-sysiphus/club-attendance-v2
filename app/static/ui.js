import { esc, fmtDate, todayKst, STATUS } from './api.js';

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
