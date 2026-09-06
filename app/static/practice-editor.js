import { api } from './api.js';

// 출석 목록과 달력에서 같은 연습 등록·수정 폼을 사용한다.
export function practiceFormHtml() {
  return `
    <dialog id="pform" aria-labelledby="pform-title">
      <form class="stack">
        <p class="eyebrow">연습 일정</p>
        <h2 id="pform-title">새 연습</h2>
        <label>제목 <input name="title" required placeholder="예: 정기 연습"></label>
        <div class="form-columns"><label>날짜 <input name="date" type="date" required></label>
        <label>시작 시간 <input name="time" type="time" required></label></div>
        <label>장소 <input name="place" placeholder="연습 장소를 입력하세요"></label>
        <div class="row dialog-actions">
          <button type="button" id="pform-cancel" class="btn">취소</button>
          <button class="btn primary">저장</button>
        </div>
      </form>
    </dialog>`;
}

export function bindPracticeControls(root, list, { refresh, toast, date = '' }) {
  const dlg = root.querySelector('#pform');
  const form = dlg.querySelector('form');
  const f = form.elements;
  const save = form.querySelector('button[type="submit"], button:not([type])');
  const openForm = p => {
    form.reset();
    form.dataset.id = p ? p.id : '';
    save.disabled = false;
    dlg.querySelector('#pform-title').textContent = p ? '연습 수정' : '새 연습';
    if (p) {
      f.title.value = p.title;
      f.date.value = p.starts_at.slice(0, 10);
      f.time.value = p.starts_at.slice(11, 16);
      f.place.value = p.place;
    } else if (date) {
      f.date.value = date;
    }
    dlg.showModal();
  };
  root.querySelector('#new').onclick = () => openForm(null);
  root.querySelector('#pform-cancel').onclick = () => dlg.close();
  root.querySelectorAll('[data-edit]').forEach(b => {
    b.onclick = () => openForm(list.find(p => p.id === Number(b.dataset.edit)));
  });
  root.querySelectorAll('[data-del]').forEach(b => {
    b.onclick = async () => {
      if (!confirm('이 연습을 삭제할까요?')) return;
      b.disabled = true;
      try {
        await api('DELETE', `/practices/${b.dataset.del}`);
        toast('삭제했어요'); refresh();
      } catch (e) { toast(e.message, true); b.disabled = false; }
    };
  });
  form.onsubmit = async e => {
    e.preventDefault();
    if (save.disabled) return;
    save.disabled = true;
    const id = form.dataset.id;
    const body = { title: f.title.value, starts_at: `${f.date.value}T${f.time.value}`, place: f.place.value };
    try {
      await api(id ? 'PUT' : 'POST', id ? `/practices/${id}` : '/practices', body);
      dlg.close(); toast('저장했어요'); refresh();
    } catch (err) { toast(err.message, true); save.disabled = false; }
  };
}
