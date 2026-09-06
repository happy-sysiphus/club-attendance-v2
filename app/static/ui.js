import { esc, fmtDate, todayKst } from './api.js';

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
