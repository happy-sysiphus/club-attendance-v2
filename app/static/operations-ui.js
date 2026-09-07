import {api, esc, fmtDate, todayKst, session, setSession, setReadOnly, isReadOnly, PART} from './api.js';
import {dateTile, emptyState} from './ui.js';

export const ui = {state: null, root: null, refresh: null, toast: null};
export const getState = () => ui.state;
export const conductor = () => ui.state.me.role === 'conductor';
export const music = () => ['conductor','part_leader'].includes(ui.state.me.role) || ui.state.me.part === 'accompanist';
export const photos = () => ['head','publicity'].includes(ui.state.me.admin_role);
export const canceled = e => ['cancelled','cancelling','deleting'].includes(e.status);
export const performance = e => ['정기공연','외부공연'].includes(e.kind);
export const back = (href = '#/home', label = '뒤로') => `<a class="back-link" href="${href}">← ${label}</a>`;
export const badge = n => n ? `<span class="notification-badge" aria-label="미완료 ${n}개">${n}</span>` : '';
export const money = x => `${Number(x || 0).toLocaleString('ko-KR')}원`;
export const fileURL = f => /^https:\/\//i.test(f?.[f?.type]?.url || '') ? esc(f[f.type].url) : '';
export const dateText = e => `${e.all_day ? e.starts_at.slice(0,10) + ' · 종일' : fmtDate(e.starts_at)}${e.ends_at?.slice(0,10) !== e.starts_at.slice(0,10) ? ' ~ ' + e.ends_at.slice(0,10) : ''}`;
export const input = (name,label,value='',type='text',required=false) => `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${required ? 'required' : ''}></label>`;
const kinds = {rehearsal:'연습', regular:'정기공연', external:'외부공연', admin:'행정'};
const adminNames = {head:'단장',publicity:'홍보',treasurer:'총무'};
const editable = e => e.category === '지휘' ? conductor() : ui.state.me.admin_role === 'head';
const danger = e => ui.state.missing_photos.includes(e.id) ? '<span class="photo-alert" title="사진 등록 필요" aria-label="사진 등록 필요">!</span>' : '';
const tag = e => `<span class="badge ${performance(e) && !canceled(e) ? 'concert-badge' : ''}">${canceled(e) ? '취소' : esc(e.kind)}</span>`;
const list = events => events.length ? `<ul class="list practice-list">${events.map(e => `<li><a href="#/event/${e.id}">${dateTile(e.starts_at)}<span class="practice-copy"><strong>${esc(e.title)} ${danger(e)}</strong><span class="muted">${esc(dateText(e))} · ${esc(e.place)}</span></span></a>${tag(e)}</li>`).join('')}</ul>` : emptyState('등록된 일정이 없어요');

export async function loadOperations(root, callbacks) {
  ui.root = root; Object.assign(ui,callbacks);
  const semester = sessionStorage.getItem('glee-semester') || '';
  const fresh = sessionStorage.getItem('glee-fresh') === '1'; sessionStorage.removeItem('glee-fresh');
  const query = [semester && 'semester=' + encodeURIComponent(semester), fresh && 'fresh=1'].filter(Boolean).join('&');
  let state;
  try { state = await api('GET', `/api/state${query ? '?' + query : ''}`); }
  catch (error) {
    if (![0,503].includes(error.status) || !ui.state || ui.state.me.id !== session()?.id || (semester && ui.state.semester.id !== semester)) throw error;
    state = {...ui.state, stale:true};
  }
  if (callbacks.isCurrent && !callbacks.isCurrent()) return;
  ui.state = state; setSession(state.me); setReadOnly(state.stale); navigation();
}

function navigation() {
  const s = ui.state, active = location.hash.split('/')[1] || 'home';
  document.getElementById('user').textContent = `${s.me.name} · ${PART[s.me.part]}${s.me.admin_role ? ' · '+adminNames[s.me.admin_role] : ''}`;
  const tabs = [['home','출석'],['schedule','일정']];
  if (music()) tabs.push(['music','지휘',s.missing_materials.length]);
  if (photos()) tabs.push(['admin','행정',s.missing_photos.length]);
  tabs.push(['finance','재정']);
  document.getElementById('tabs').innerHTML = tabs.map(([path,label,n]) => `<a href="#/${path}" ${path === active || path === 'schedule' && ['event','day'].includes(active) || path === 'music' && ['song','concert'].includes(active) ? 'aria-current="page"' : ''}>${label}${badge(n)}</a>`).join('');
  let toolbar = document.getElementById('semester-toolbar');
  if (!toolbar) { toolbar = document.createElement('div'); toolbar.id='semester-toolbar'; document.getElementById('tabs').after(toolbar); }
  toolbar.hidden = false;
  toolbar.innerHTML = `<label class="semester-label">학기<select id="semester-select">${s.semesters.filter(x => x.state !== 'pending').map(x => `<option value="${x.id}" ${x.id === s.semester.id ? 'selected' : ''}>${esc(x.title)}${x.id === s.current_semester ? ' · 현재' : ''}</option>`).join('')}</select></label><button class="text-action" id="reload-data">새로고침</button>${s.me.admin_role === 'head' ? '<a class="text-action" href="#/settings">학기 관리</a>' : ''}${s.stale ? `<p class="warn full-width" role="alert">최신 정보가 아닙니다 · ${esc(s.loaded_at)} 조회. 연결 복구 전까지 편집할 수 없어요.</p>` : ''}`;
  toolbar.querySelector('select').onchange = e => { sessionStorage.setItem('glee-semester',e.target.value); ui.refresh(); };
  toolbar.querySelector('#reload-data').onclick = () => { sessionStorage.setItem('glee-fresh', '1'); ui.refresh(); }; // 캐시를 건너뛰고 노션에서 다시 읽는다
}

export function bindActions() {
  ui.root.querySelectorAll('[data-new-event]').forEach(b => b.onclick = () => eventEditor(null,b.dataset.newEvent));
  if (ui.state.stale) ui.root.querySelectorAll('[data-write]').forEach(b => b.disabled=true);
}

export async function act(question, action) {
  if (isReadOnly()) { ui.toast('최신 정보를 불러온 뒤 다시 시도해 주세요.',true); return; }
  if (!confirm(question)) return;
  try { await action(); ui.toast('반영했어요'); await ui.refresh(); }
  catch (e) { ui.toast(e.message,true); }
}

export function dialog(title, contents, submit, onSave) {
  const d=document.createElement('dialog'), requestId=crypto.randomUUID();
  d.setAttribute('aria-label',title);
  d.innerHTML=`<form class="stack"><h2>${esc(title)}</h2>${contents}<p class="err" role="alert" hidden></p><div class="row dialog-actions"><button class="btn" type="button" data-cancel>취소</button><button class="btn primary" type="submit">${submit}</button></div></form>`;
  document.body.append(d); d.addEventListener('close',()=>d.remove());
  d.querySelector('[data-cancel]').onclick=()=>d.close();
  d.querySelector('form').onsubmit=async e=>{
    e.preventDefault(); const b=d.querySelector('[type=submit]'), error=d.querySelector('.err');
    if (b.disabled) return; b.disabled=true; error.hidden=true; b.textContent='노션에 저장 중…';
    try { if (isReadOnly()) throw new Error('연결을 복구하고 다시 시도해 주세요.'); await onSave(e.target.elements,requestId,d); d.close(); }
    catch(err) { error.textContent=err.message; error.hidden=false; }
    finally { b.disabled=false; b.textContent=submit; }
  };
  d.showModal(); return d;
}

export function operationsHome() {
  const s=ui.state, today=todayKst(), events=s.events.filter(e=>!canceled(e)&&(e.ends_at||e.starts_at).slice(0,10)>=today).sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
  const next=events[0], stats=s.stats;
  ui.root.innerHTML=`<section class="page-heading"><p class="eyebrow">${esc(s.me.name)}님, 반가워요</p><h1>오늘도, 함께 노래해요.</h1><p class="muted">우리의 다음 만남과 출석을 확인하세요.</p></section>
    ${s.missing_photos.length ? `<a class="warn notice-link" href="#/admin">사진 등록이 필요한 일정 ${s.missing_photos.length}개${badge(s.missing_photos.length)}</a>` : ''}
    ${s.missing_materials.length ? `<a class="warn notice-link" href="#/music">확인하지 않은 필수 자료 ${s.missing_materials.length}개${badge(s.missing_materials.length)}</a>` : ''}
    ${s.me.admin_role==='treasurer'&&s.finance.carry_needs_confirmation ? '<a class="warn notice-link" href="#/finance">학기 이월금을 확인해 주세요.</a>' : ''}
    <div class="home-overview ${conductor()?'without-stats':''}"><section class="card next-practice">${next ? `<div class="row between"><p class="eyebrow">가장 가까운 일정</p>${tag(next)}</div><div class="next-detail">${dateTile(next.starts_at)}<div><h2>${esc(next.title)}</h2><p class="muted">${esc(dateText(next))}<br>${esc(next.place)}</p></div></div><a class="btn primary" href="#/event/${next.id}">일정 자세히 보기</a>` : emptyState('예정된 일정이 없어요')}</section>
    ${!conductor()?`<section class="card attendance-summary"><p class="eyebrow">나의 출석 · ${esc(s.semester.title)}</p><p class="big">${stats.total?Math.round(stats.rate*100)+'<span>%</span>':'—'}</p><progress class="attendance-progress" max="100" value="${Math.round(stats.rate*100)}"></progress><div class="stat-breakdown"><span>출석 <b>${stats.present}</b></span><span>지각 <b>${stats.late}</b></span><span>결석 <b>${stats.absent}</b></span></div></section>`:''}</div>
    <section class="stack"><div class="row between"><h2>다가오는 일정 <span class="count-label">${events.length}</span></h2><div class="row">${conductor()?'<button class="btn small" data-write data-new-event="rehearsal">지휘 일정 등록</button>':''}${s.me.admin_role==='head'?'<button class="btn small" data-write data-new-event="admin">행정 일정 등록</button>':''}</div></div>${list(events)}</section>`;
  bindActions();
}

let month=todayKst().slice(0,7);
export function operationsCalendar() {
  const [year,mm]=month.split('-').map(Number), first=new Date(Date.UTC(year,mm-1,1)), start=new Date(first);
  start.setUTCDate(1-first.getUTCDay());
  const cells=Array.from({length:42},(_,i)=>{const d=new Date(start);d.setUTCDate(start.getUTCDate()+i);return d.toISOString().slice(0,10);});
  ui.root.innerHTML=`<section class="page-heading"><p class="eyebrow">GLEE SCHEDULE</p><h1>우리의 일정</h1><p class="muted">날짜를 눌러 일정과 사진을 확인하세요.</p></section><section class="card calendar"><div class="calendar-toolbar"><button class="icon" id="prev-month" aria-label="이전 달">←</button><h2>${year}년 ${mm}월</h2><button class="icon" id="next-month" aria-label="다음 달">→</button></div><div class="calendar-weekdays">${[...'일월화수목금토'].map(x=>`<span>${x}</span>`).join('')}</div><div class="calendar-grid">${cells.map(day=>{
    const events=ui.state.events.filter(e=>e.starts_at.slice(0,10)<=day&&(e.ends_at||e.starts_at).slice(0,10)>=day);
    return `<button class="calendar-day ${day.slice(0,7)!==month?'outside':''} ${day===todayKst()?'today':''} ${events.some(e=>performance(e)&&!canceled(e))?'concert-day':''}" data-day="${day}" aria-label="${day}, 일정 ${events.length}개"><span class="day-number">${Number(day.slice(8))}</span><span class="day-events">${events.slice(0,2).map(e=>`<span class="day-event ${canceled(e)?'cancelled':performance(e)?'concert-badge':''}">${esc(e.title)}</span>`).join('')}${events.length>2?`<span class="day-more">+${events.length-2}</span>`:''}</span></button>`;
  }).join('')}</div><div class="calendar-summary"><span>강조된 날짜는 정기·외부공연입니다.</span><button class="text-action" id="this-month">이번 달</button></div></section>`;
  const move=delta=>{month=new Date(Date.UTC(year,mm-1+delta,1)).toISOString().slice(0,7);operationsCalendar();};
  ui.root.querySelector('#prev-month').onclick=()=>move(-1);ui.root.querySelector('#next-month').onclick=()=>move(1);
  ui.root.querySelector('#this-month').onclick=()=>{month=todayKst().slice(0,7);operationsCalendar();};
  ui.root.querySelectorAll('[data-day]').forEach(b=>b.onclick=()=>{const events=ui.state.events.filter(e=>e.starts_at.slice(0,10)<=b.dataset.day&&(e.ends_at||e.starts_at).slice(0,10)>=b.dataset.day);location.hash=events.length===1?`#/event/${events[0].id}`:`#/day/${b.dataset.day}`;});
}

export function dayView(date) {
  ui.root.innerHTML=`${back('#/schedule','캘린더')}<h1>${esc(date)} 일정</h1>${list(ui.state.events.filter(e=>e.starts_at.slice(0,10)<=date&&(e.ends_at||e.starts_at).slice(0,10)>=date).sort((a,b)=>a.starts_at.localeCompare(b.starts_at)))}`;
}

export function eventView(id) {
  const s=ui.state,e=s.events.find(e=>e.id===id);
  if(!e){ui.root.innerHTML=`${back('#/schedule')}${emptyState('이 학기에 해당 일정이 없어요')}`;return;}
  const songs=e.songs.map(id=>s.songs.find(x=>x.id===id)).filter(Boolean);
  ui.root.innerHTML=`${back('#/schedule','캘린더')}<section class="page-heading"><div class="row">${tag(e)}${danger(e)}</div><h1>${esc(e.title)}</h1><p class="muted">${esc(dateText(e))}<br>${esc(e.place)}</p></section>${e.description?`<section class="card prose">${esc(e.description)}</section>`:''}
    <div class="row">${!canceled(e)&&e.category==='지휘'?`${!conductor()?`<a class="btn primary" href="#/practice/${id}">내 출석</a>`:''}${['conductor','part_leader'].includes(s.me.role)?`<a class="btn" href="#/board/${id}">출석 현황</a>`:''}`:''}
    ${editable(e)?`${!canceled(e)?'<button class="btn" id="edit-event" data-write>일정 수정</button><button class="text-action" id="cancel-event" data-write>일정 취소</button>':''}<button class="text-action" id="delete-event" data-write>삭제</button>`:''}</div>
    ${performance(e)?`<section class="stack"><h2>공연 곡</h2>${songs.length?`<ol class="song-program">${songs.map(x=>`<li>${esc(x.title)} <span class="muted">${esc([x.composer,x.arranger].filter(Boolean).join(' · '))}</span></li>`).join('')}</ol>`:'<p class="muted">곡 목록이 아직 정해지지 않았어요.</p>'}${music()?`<a class="btn" href="#/concert/${id}">지휘 탭에서 자료 보기</a>`:''}</section>`:''}
    <section class="stack"><div class="row between"><h2>함께한 순간 <span class="count-label">${e.photos.length}장</span></h2>${photos()?'<button class="btn small" id="add-photo" data-write>사진 추가</button>':''}</div>${!e.photos.length?emptyState('아직 등록된 사진이 없어요',photos()?'일정당 최소 한 장을 등록해 주세요.':''):`<div class="photo-grid">${e.photos.map(f=>{const meta=e.photo_meta[f.name];return `<figure><a href="${fileURL(f)}" target="_blank" rel="noopener"><img src="${fileURL(f)}" alt="${esc(f.name.replace(/^[0-9a-f-]{36}--/,''))}" loading="lazy"></a><figcaption>${esc(meta?.by||'노션 등록')} ${esc(meta?.at?.slice(0,16).replace('T',' ')||'')}<a href="${fileURL(f)}" target="_blank" rel="noopener">원본 보기</a>${photos()?`<div class="row"><button class="text-action" data-replace-photo="${esc(f.name)}" data-write>교체</button><button class="text-action" data-delete-photo="${esc(f.name)}" data-write>삭제</button></div>`:''}</figcaption></figure>`;}).join('')}</div>`}</section>`;
  ui.root.querySelector('#edit-event')?.addEventListener('click',()=>eventEditor(e));
  ui.root.querySelector('#cancel-event')?.addEventListener('click',()=>act('일정을 취소하고 입력된 출석을 삭제할까요?',()=>api('POST',`/api/events/${id}/cancel`)));
  ui.root.querySelector('#delete-event')?.addEventListener('click',()=>act('일정과 출석 기록을 삭제할까요?',async()=>{await api('DELETE',`/api/events/${id}`);location.hash='#/schedule';}));
  ui.root.querySelector('#add-photo')?.addEventListener('click',()=>uploadDialog('photos',id));
  ui.root.querySelectorAll('[data-delete-photo]').forEach(b=>b.onclick=()=>act('사진을 삭제할까요?',()=>api('DELETE',`/api/events/${id}/photos/${encodeURIComponent(b.dataset.deletePhoto)}`)));
  ui.root.querySelectorAll('[data-replace-photo]').forEach(b=>b.onclick=()=>uploadDialog('photos',id,b.dataset.replacePhoto));bindActions();
}

export function adminView(){
  if(!photos()){ui.root.innerHTML=emptyState('행정 탭 접근 권한이 없어요');return;}
  ui.root.innerHTML=`<section class="page-heading"><p class="eyebrow">ADMINISTRATION</p><h1>일정과 사진 기록</h1><p class="muted">빨간 느낌표가 있는 일정에 사진을 등록해 주세요.</p></section>${ui.state.me.admin_role==='head'?'<button class="btn" data-write data-new-event="admin">행정 일정 등록</button>':''}${list([...ui.state.events].sort((a,b)=>b.starts_at.localeCompare(a.starts_at)))}`;bindActions();
}

export function eventEditor(event=null,defaultKind='rehearsal') {
  let chosen=[...(event?.songs||[])];
  const kind=event?Object.keys(kinds).find(k=>kinds[k]===event.kind):defaultKind;
  const allowed=(event?event.category==='행정':defaultKind==='admin')?['admin']:['rehearsal','regular','external'];
  const start=event?.starts_at||todayKst()+'T18:00:00';
  const d=dialog(event?'일정 수정':'일정 등록',`<label>종류<select name="kind">${allowed.map(k=>`<option value="${k}" ${k===kind?'selected':''}>${kinds[k]}</option>`).join('')}</select></label>${input('title','일정 이름',event?.title||'','text',true)}<div class="form-columns">${input('date','날짜',start.slice(0,10),'date',true)}<label class="event-time">시작 시간<input type="time" name="time" value="${start.slice(11,16)}" required></label></div><div class="admin-fields">${input('end_date','종료 날짜',event?.ends_at?.slice(0,10)||start.slice(0,10),'date',true)}<label class="check"><input type="checkbox" name="all_day" ${event?.all_day?'checked':''}>종일 일정</label></div>${input('place','장소',event?.place||'')}<label>설명<textarea name="description" rows="4">${esc(event?.description||'')}</textarea></label><section class="concert-fields stack"><h3>공연 곡</h3><p class="muted">곡 없이 먼저 등록해도 됩니다.</p><div id="selected-songs"></div><input type="search" id="song-search" placeholder="곡명·작곡가·편곡자 검색"><div class="song-picker"></div><button class="btn small" type="button" id="inline-song">새 곡 등록</button></section>`,'저장',async(f,requestId)=>{
    const admin=f.kind.value==='admin', allDay=admin&&f.all_day.checked;
    await api(event?'PUT':'POST',`/api/events${event?'/'+event.id:''}`,{request_id:requestId,edited_at:event?.edited_at,title:f.title.value,kind:f.kind.value,starts_at:`${f.date.value}T${allDay?'00:00':f.time.value}:00`,ends_at:`${admin?f.end_date.value:f.date.value}T${admin?'23:59:59':f.time.value+':00'}`,all_day:allDay,place:f.place.value,description:f.description.value,semester:event?.semester||ui.state.semester.id,songs:chosen});ui.toast('일정을 저장했어요');await ui.refresh();
  });
  const f=d.querySelector('form').elements;
  const sync=()=>{const admin=f.kind.value==='admin';d.querySelector('.admin-fields').hidden=!admin;d.querySelector('.event-time').hidden=admin&&f.all_day.checked;f.time.required=!(admin&&f.all_day.checked);d.querySelector('.concert-fields').hidden=!['regular','external'].includes(f.kind.value);};
  const redraw=()=>{
    const q=d.querySelector('#song-search').value.toLowerCase();
    d.querySelector('.song-picker').innerHTML=ui.state.songs.filter(s=>`${s.title} ${s.composer} ${s.arranger}`.toLowerCase().includes(q)).map(s=>`<label class="check"><input type="checkbox" data-pick="${s.id}" ${chosen.includes(s.id)?'checked':''}>${esc(s.title)} <span class="muted">${esc(s.composer)} ${esc(s.arranger)}</span></label>`).join('');
    d.querySelector('#selected-songs').innerHTML=chosen.map((id,i)=>`<div class="row between"><span>${i+1}. ${esc(ui.state.songs.find(s=>s.id===id)?.title)}</span><span><button type="button" class="text-action" data-up="${i}" ${i===0?'disabled':''} aria-label="곡 위로">↑</button><button type="button" class="text-action" data-down="${i}" ${i===chosen.length-1?'disabled':''} aria-label="곡 아래로">↓</button></span></div>`).join('');
    d.querySelectorAll('[data-pick]').forEach(c=>c.onchange=()=>{chosen=c.checked?[...chosen,c.dataset.pick]:chosen.filter(id=>id!==c.dataset.pick);redraw();});
    for(const [attr,delta] of [['up',-1],['down',1]])d.querySelectorAll(`[data-${attr}]`).forEach(b=>b.onclick=()=>{const i=Number(b.dataset[attr]);[chosen[i],chosen[i+delta]]=[chosen[i+delta],chosen[i]];redraw();});
  };
  f.kind.onchange=sync;f.all_day.onchange=sync;d.querySelector('#song-search').oninput=redraw;
  d.querySelector('#inline-song').onclick=()=>songEditor(null,async id=>{const next=await api('GET','/api/state?semester='+ui.state.semester.id);ui.state.songs=next.songs;chosen.push(id);redraw();});sync();redraw();
}

export function songEditor(song=null,done=null){
  const concerts=ui.state.events.filter(e=>performance(e)&&!canceled(e));
  const selection=!song&&!done?`<label>공연 선택<select name="concert"><option value="">공연 미정</option>${concerts.map(e=>`<option value="${e.id}">${esc(e.title)}</option>`).join('')}</select></label>`:'';
  dialog(song?'곡 정보 수정':'새 곡 등록',`${input('title','곡 제목',song?.title||'','text',true)}${input('composer','작곡가',song?.composer||'')}${input('arranger','편곡자',song?.arranger||'')}${selection}`,'저장',async(f,requestId)=>{
    const result=await api(song?'PUT':'POST',`/api/songs${song?'/'+song.id:''}`,{request_id:requestId,edited_at:song?.edited_at,title:f.title.value,composer:f.composer.value,arranger:f.arranger.value});
    if(f.concert?.value){
      const event=concerts.find(e=>e.id===f.concert.value);
      await api('POST',`/api/events/${event.id}/songs`,{song_id:result.id});
    }
    if(done)await done(result.id);else await ui.refresh();
  });
}

export function uploadDialog(target,id,replace=''){
  const photo=target==='photos';
  const d=dialog(photo?'일정 사진 등록':'곡 자료 등록',`${!photo?'<label>자료 종류<select name="kind"><option value="score">악보 필기본</option><option value="audio">연습 음원</option></select></label>':''}<label>파일<input name="file" type="file" required accept="${photo?'.jpg,.jpeg,.png,.heic':'.pdf,.jpg,.jpeg,.png,.heic'}"></label><p class="muted">${photo?'JPG · PNG · HEIC':'악보 PDF·이미지 / 음원 MP3·M4A·WAV'} · 노션에 원본으로 저장됩니다.</p>${!photo?`${input('rehearsal_date','연습 날짜 (선택)','','date')}<label class="check"><input name="required" type="checkbox" checked>확인 필수</label>`:''}`,'업로드',async(f,requestId)=>{
    const file=f.file.files[0];const res=await fetch(`/api/upload/${target}/${id}`,{method:'POST',credentials:'same-origin',body:file,headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name),'X-Request-Id':requestId,...(replace?{'X-Replace-Photo':encodeURIComponent(replace)}:{}),...(!photo?{'X-Material-Kind':f.kind.value,'X-Required':String(f.required.checked),'X-Rehearsal-Date':f.rehearsal_date.value}:{})}});
    if(!res.ok){const error=await res.json();throw new Error(error.detail||'업로드에 실패했어요');}ui.toast('파일을 저장했어요');await ui.refresh();
  });
  if(!photo)d.querySelector('[name=kind]').onchange=e=>{const score=e.target.value==='score';d.querySelector('[name=required]').checked=score;d.querySelector('[name=file]').accept=score?'.pdf,.jpg,.jpeg,.png,.heic':'.mp3,.m4a,.wav';};
}
