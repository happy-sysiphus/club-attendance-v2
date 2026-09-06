import { api, esc, fmtDate, practiceLink, session, todayKst } from './api.js';
import { practiceFormHtml, bindPracticeControls } from './practice-editor.js';
import { icon, practiceBadge, emptyState } from './ui.js';

// 탭을 오가거나 연습을 저장해도 사용자가 보던 달과 날짜를 유지한다.
let selectedDate = todayKst();
let displayedMonth = selectedDate.slice(0, 7);
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

export function monthDays(month) {
  const [year, number] = month.split('-').map(Number);
  const first = new Date(Date.UTC(year, number - 1, 1));
  const offset = first.getUTCDay();
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(Date.UTC(year, number - 1, 1 - offset + index));
    const key = date.toISOString().slice(0, 10);
    return { key, day: date.getUTCDate(), inMonth: key.startsWith(month) };
  });
}

export async function calendarView(root, { refresh, toast }) {
  const list = await api('GET', '/practices');
  if (location.hash !== '#/schedule') return;
  const user = session();
  const conductor = user.role === 'conductor';
  const byDate = new Map();
  for (const p of [...list].sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.id - b.id)) {
    const key = p.starts_at.slice(0, 10);
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key).push(p);
  }

  function render(focus = '') {
    const [year, month] = displayedMonth.split('-').map(Number);
    const today = todayKst();
    const selected = byDate.get(selectedDate) || [];
    const monthCount = list.filter(p => p.starts_at.startsWith(displayedMonth)).length;
    root.innerHTML = `
      <section class="page-heading row between">
        <div>
          <p class="eyebrow">GLEE SCHEDULE</p>
          <h1>다음 만남을 확인해요.</h1>
          <p class="muted">우리의 목소리가 모이는 날.</p>
        </div>
        <button type="button" id="calendar-today" class="btn small">오늘</button>
      </section>
      <section class="card calendar" aria-labelledby="calendar-month">
        <div class="calendar-toolbar">
          <button type="button" id="calendar-prev" class="icon" aria-label="이전 달">${icon('chevron-left')}</button>
          <h2 id="calendar-month" aria-live="polite">${year}년 ${month}월</h2>
          <button type="button" id="calendar-next" class="icon" aria-label="다음 달">${icon('chevron-left', 'point-right')}</button>
        </div>
        <div class="calendar-weekdays" aria-hidden="true">
          ${WEEKDAYS.map(day => `<span>${day}</span>`).join('')}
        </div>
        <div class="calendar-grid">
          ${monthDays(displayedMonth).map(day => {
            const practices = byDate.get(day.key) || [];
            const label = `${day.key}, ${practices.length ? practices.map(p => `${p.starts_at.slice(11, 16)} ${p.title}`).join(', ') : '연습 없음'}`;
            return `<button type="button" data-day="${day.key}"
              class="calendar-day ${day.inMonth ? '' : 'outside'} ${day.key === today ? 'today' : ''}"
              aria-pressed="${day.key === selectedDate}" ${day.key === today ? 'aria-current="date"' : ''}
              aria-label="${esc(label)}">
              <span class="day-number">${day.day}</span>
              <span class="day-events" aria-hidden="true">
                ${practices.slice(0, 2).map(p => `<span class="day-event ${p.status === 'closed' ? 'closed' : ''}">${esc(p.title)}</span>`).join('')}
                ${practices.length > 2 ? `<span class="day-more">+${practices.length - 2}개</span>` : ''}
              </span>
            </button>`;
          }).join('')}
        </div>
        <p class="muted calendar-summary">이번 달 <strong>${monthCount}번의 연습</strong><span>날짜를 눌러 일정을 확인하세요.</span></p>
      </section>
      <section class="stack" aria-labelledby="selected-date">
        <div class="row between section-heading">
          <h2 id="selected-date" aria-live="polite">${fmtDate(`${selectedDate}T00:00:00`).replace(' 00:00', '')} 일정</h2>
          ${conductor ? '<button type="button" id="new" class="btn small">새 연습</button>' : ''}
        </div>
        ${selected.length ? `<ul class="list schedule-list">${selected.map(p => `
          <li>
            <div class="schedule-item">
              <div class="row between">
                <span class="eyebrow">${p.starts_at.slice(11, 16)}</span>
                ${practiceBadge(p)}
              </div>
              <h3>${esc(p.title)}</h3>
              <p class="muted">${esc(p.place || '장소 미정')}</p>
              <div class="row card-actions">
                ${user.role !== 'conductor' ? `<a class="btn small" href="#/practice/${p.id}">${p.status === 'closed' ? '내 출석 보기' : '내 출석 입력'}</a>` : ''}
                ${user.role !== 'member' ? `<a class="btn small" href="${practiceLink(p, user.role)}">현황판</a>` : ''}
                ${conductor && p.status === 'open' ? `
                  <button type="button" class="btn small" data-edit="${p.id}">수정</button>
                  <button type="button" class="btn small" data-del="${p.id}">삭제</button>` : ''}
              </div>
            </div>
          </li>`).join('')}</ul>`
          : emptyState('잠시 쉬어가는 날', '이 날짜에 등록된 연습이 없어요.')}
      </section>
      ${conductor ? practiceFormHtml() : ''}`;

    root.querySelector('#calendar-prev').onclick = () => moveMonth(-1, '#calendar-prev');
    root.querySelector('#calendar-next').onclick = () => moveMonth(1, '#calendar-next');
    root.querySelector('#calendar-today').onclick = () => {
      selectedDate = todayKst();
      displayedMonth = selectedDate.slice(0, 7);
      render('#calendar-today');
    };
    root.querySelectorAll('[data-day]').forEach(button => {
      button.onclick = () => {
        selectedDate = button.dataset.day;
        displayedMonth = selectedDate.slice(0, 7);
        render(`[data-day="${selectedDate}"]`);
      };
    });
    if (conductor) bindPracticeControls(root, list, { refresh, toast, date: selectedDate });
    if (focus) root.querySelector(focus)?.focus({ preventScroll: true });
  }

  function moveMonth(amount, focus) {
    const [year, month] = displayedMonth.split('-').map(Number);
    const first = new Date(Date.UTC(year, month - 1 + amount, 1));
    selectedDate = first.toISOString().slice(0, 10);
    displayedMonth = selectedDate.slice(0, 7);
    render(focus);
  }

  render();
}
