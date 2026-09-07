import {api,esc,todayKst,PART} from './api.js';
import {emptyState} from './ui.js';
import {ui,conductor,music,canceled,performance,back,badge,money,dateText,input,bindActions,act,dialog,eventEditor,songEditor,uploadDialog} from './operations-ui.js';

function songList(songs,assigned=new Set()){
  const s=ui.state;
  return songs.length?`<ul class="list">${songs.map(song=>`<li><a href="#/song/${song.id}"><span class="practice-copy"><strong>${esc(song.title)}</strong><span class="muted">${esc([song.composer,song.arranger].filter(Boolean).join(' · '))}${assigned.has(song.id)?'':' · 공연 미정'}</span></span></a>${badge(s.missing_materials.filter(id=>s.materials.find(m=>m.id===id)?.song===song.id).length)}</li>`).join('')}</ul>`:emptyState('등록된 곡이 없어요');
}

export function musicView(){
  if(!music()){ui.root.innerHTML=emptyState('지휘 탭 접근 권한이 없어요');return;}
  const s=ui.state,concerts=s.events.filter(performance),assigned=new Set(concerts.flatMap(e=>e.songs));
  ui.root.innerHTML=`<section class="page-heading"><p class="eyebrow">MUSIC LIBRARY</p><h1>함께 준비하는 음악</h1><p class="muted">공연별 곡과 연습 자료를 확인하세요.</p></section>${s.missing_materials.length?'<p class="warn">확인하지 않은 필수 자료가 있어요. 곡을 눌러 확인해 주세요.</p>':''}${conductor()?'<div class="row"><button class="btn" data-write data-new-event="regular">새 공연</button><button class="btn" data-write id="new-song">새 곡</button></div>':''}
    <section class="stack"><h2>공연</h2>${concerts.length?`<ul class="list">${concerts.map(e=>`<li><a href="#/concert/${e.id}"><span class="practice-copy"><strong>${esc(e.title)}</strong><span class="muted">${esc(dateText(e))} · ${e.songs.length}곡${canceled(e)?' · 취소':''}</span></span></a></li>`).join('')}</ul>`:emptyState('등록된 공연이 없어요')}</section><section class="stack"><h2>공연 미정 · 전체 곡 목록</h2><input id="library-search" type="search" placeholder="곡명·작곡가·편곡자 검색"><div id="library"></div></section>`;
  const draw=()=>{const q=ui.root.querySelector('#library-search').value.toLowerCase();ui.root.querySelector('#library').innerHTML=songList(s.songs.filter(x=>`${x.title} ${x.composer} ${x.arranger}`.toLowerCase().includes(q)),assigned);};
  ui.root.querySelector('#library-search').oninput=draw;draw();ui.root.querySelector('#new-song')?.addEventListener('click',()=>songEditor());bindActions();
}

export function concertView(id){
  if(!music()){ui.root.innerHTML=emptyState('지휘 탭 접근 권한이 없어요');return;}
  const s=ui.state,event=s.events.find(e=>e.id===id&&performance(e));
  if(!event){ui.root.innerHTML=emptyState('공연이 없어요');return;}
  const songs=event.songs.map(id=>s.songs.find(x=>x.id===id)).filter(Boolean);
  ui.root.innerHTML=`${back('#/music','지휘 탭')}<section class="page-heading"><p class="eyebrow">${esc(event.kind)}</p><h1>${esc(event.title)}</h1><p class="muted">${esc(dateText(event))}</p></section><div class="row"><a class="btn" href="#/event/${id}">공연 상세</a>${conductor()&&!canceled(event)?'<button class="btn" id="program" data-write>곡 선택·순서 변경</button>':''}</div>${songList(songs,new Set(event.songs))}`;
  ui.root.querySelector('#program')?.addEventListener('click',()=>eventEditor(event));bindActions();
}

export function songView(id){
  if(!music()){ui.root.innerHTML=emptyState('지휘 탭 접근 권한이 없어요');return;}
  const s=ui.state,song=s.songs.find(x=>x.id===id);
  if(!song){ui.root.innerHTML=emptyState('곡이 없어요');return;}
  const materials=s.materials.filter(m=>m.song===id).sort((a,b)=>b.uploaded_at.localeCompare(a.uploaded_at));
  const concerts=s.events.filter(e=>performance(e)&&e.songs.includes(id));
  ui.root.innerHTML=`${back('#/music','곡 목록')}<section class="page-heading"><h1>${esc(song.title)}</h1><p class="muted">${esc([song.composer,song.arranger].filter(Boolean).join(' · '))}</p><p class="muted">${concerts.length?concerts.map(e=>esc(e.title)).join(' · '):'공연 미정 · 확인 의무 없음'}</p></section>${conductor()?'<div class="row"><button class="btn" id="add-material" data-write>자료 업로드</button><button class="btn" id="edit-song" data-write>곡 정보 수정</button></div>':''}
    <section class="stack">${materials.length?materials.map(m=>{
      const required=s.required_materials.includes(m.id),own=s.acknowledgements.find(a=>a.material===m.id&&a.member===s.me.id),confirmed=new Set(s.acknowledgements.filter(a=>a.material===m.id&&a.confirmed_at).map(a=>a.member));
      return `<article class="card stack"><div class="row between"><h2>${esc(m.title)}</h2><span class="badge">${m.kind==='score'?'필기본':'연습 음원'}${required?' · 확인 필수':''}</span></div><p class="muted">${esc(m.created_by)} · ${esc(m.uploaded_at?.replace('T',' '))}${m.rehearsal_date?'<br>연습 날짜 '+esc(m.rehearsal_date):''}</p>
        <div class="row"><a class="btn primary" href="/api/materials/${m.id}/open?semester=${s.semester.id}" target="_blank" rel="noopener">파일 열기</a>${!conductor()&&required?`<button class="btn" data-confirm-material="${m.id}" data-write ${own?.confirmed_at?'disabled':''}>${own?.confirmed_at?'확인 완료':'확인 완료하기'}</button>`:''}</div>${own?.confirmed_at?`<p class="muted">확인 시각 ${esc(own.confirmed_at.replace('T',' '))}</p>`:''}
        ${conductor()?`<div class="row"><button class="text-action" data-material-settings="${m.id}" data-write>자료 설정</button><button class="text-action" data-delete-material="${m.id}" data-write>삭제</button></div>${required?`<details><summary>확인 ${s.recipients.filter(r=>confirmed.has(r.id)).length} / ${s.recipients.length}명</summary><ul class="list">${[...s.recipients].sort((a,b)=>Number(confirmed.has(a.id))-Number(confirmed.has(b.id))).map(r=>{const a=s.acknowledgements.find(a=>a.material===m.id&&a.member===r.id);return `<li class="ack-row"><span>${esc(r.name)} · ${PART[r.part]}</span><span class="${a?.confirmed_at?'muted':'err'}">${a?.confirmed_at?esc(a.confirmed_at.replace('T',' ')):'미확인'}</span></li>`;}).join('')}</ul></details>`:'<p class="muted">현재 학기 확인 대상이 아닙니다.</p>'}`:''}</article>`;
    }).join(''):emptyState('등록된 자료가 없어요')}</section>`;
  ui.root.querySelector('#add-material')?.addEventListener('click',()=>uploadDialog('materials',id));ui.root.querySelector('#edit-song')?.addEventListener('click',()=>songEditor(song));
  ui.root.querySelectorAll('[data-confirm-material]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api('POST',`/api/materials/${b.dataset.confirmMaterial}/confirm`,{semester:s.semester.id});await ui.refresh();}catch(e){b.disabled=false;ui.toast(e.message,true);}});
  ui.root.querySelectorAll('[data-delete-material]').forEach(b=>b.onclick=()=>act('자료를 삭제할까요? 기존 확인 기록은 보존됩니다.',()=>api('DELETE',`/api/materials/${b.dataset.deleteMaterial}`)));
  ui.root.querySelectorAll('[data-material-settings]').forEach(b=>b.onclick=()=>{const m=materials.find(m=>m.id===b.dataset.materialSettings);dialog('자료 설정',`${input('title','자료명',m.title,'text',true)}<label class="check"><input type="checkbox" name="required" ${m.required?'checked':''}>확인 필수</label>`,'저장',async f=>{await api('PUT',`/api/materials/${m.id}`,{title:f.title.value,required:f.required.checked});await ui.refresh();});});bindActions();
}

export function financeView(){
  const s=ui.state,f=s.finance,canEdit=s.me.admin_role==='treasurer';
  ui.root.innerHTML=`<section class="page-heading"><p class="eyebrow">FINANCE · ${esc(s.semester.title)}</p><h1>투명하게, 함께</h1><p class="muted">글리의 수입과 지출을 확인하세요.</p></section><section class="card stack"><p class="eyebrow">현재 잔액</p><p class="balance">${money(f.balance)}</p><div class="stat-breakdown"><span>이월 ${money(f.carry)}</span><span>수입 ${money(f.income)}</span><span>지출 ${money(f.expense)}</span></div><p class="muted">전체 기간 수입 − 지출: ${money(f.all_time_net)} (이월금 중복 제외)</p></section>${f.ignored_rows?`<p class="warn">노션 장부에 제목이 없거나 구분이 수입·지출이 아닌 행이 ${f.ignored_rows}건 있어 잔액 계산에서 빠졌어요. 노션의 잔액 수식과 다를 수 있습니다.</p>`:''}
    ${canEdit&&f.carry_needs_confirmation?`<section class="warn stack"><strong>이월금 확인이 필요합니다</strong><p>전 학기 잔액 ${money(f.carry_suggested)} · 현재 확정액 ${money(f.carry)}</p><button class="btn" id="confirm-carry" data-write>이월금 확인·확정</button></section>`:''}<section class="stack"><h2>분류별 지출</h2><div class="category-summary">${Object.entries(f.categories).map(([k,v])=>`<span class="badge">${esc(k)} ${money(v)}</span>`).join('')||'<p class="muted">아직 지출 내역이 없어요.</p>'}</div></section>
    <section class="stack"><div class="row between"><h2>회계 내역</h2>${canEdit?'<button class="btn small" id="new-ledger" data-write>항목 추가</button>':''}</div><div class="row"><select id="finance-filter" aria-label="수입·지출 필터"><option value="">전체</option><option>수입</option><option>지출</option></select><input id="finance-search" type="search" placeholder="내용·담당자 검색"></div><div id="ledger-rows"></div></section>`;
  const draw=()=>{const direction=ui.root.querySelector('#finance-filter').value,q=ui.root.querySelector('#finance-search').value.toLowerCase();ui.root.querySelector('#ledger-rows').innerHTML=f.rows.filter(r=>(!direction||r.direction===direction)&&`${r.title} ${r.owner}`.toLowerCase().includes(q)).map(r=>`<article class="ledger-row"><div class="row between"><strong>${esc(r.title)}</strong><strong class="${r.direction==='수입'?'income':'expense'}">${r.direction==='수입'?'+':'−'}${money(r.amount)}</strong></div><p class="muted">${esc(r.date)} · ${esc(r.classification)} · 담당 ${esc(r.owner)}</p>${r.note?`<p class="prose">${esc(r.note)}</p>`:''}${canEdit?`<div class="row"><button class="text-action" data-edit-ledger="${r.id}" data-write>수정</button><button class="text-action" data-delete-ledger="${r.id}" data-write>삭제</button></div>`:''}</article>`).join('')||emptyState('회계 내역이 없어요');ui.root.querySelectorAll('[data-edit-ledger]').forEach(b=>b.onclick=()=>ledgerEditor(f.rows.find(r=>r.id===b.dataset.editLedger)));ui.root.querySelectorAll('[data-delete-ledger]').forEach(b=>b.onclick=()=>act('노션 장부에서 이 항목을 삭제할까요?',()=>api('DELETE',`/api/ledger/${b.dataset.deleteLedger}`)));bindActions();};
  ui.root.querySelector('#finance-filter').onchange=draw;ui.root.querySelector('#finance-search').oninput=draw;draw();ui.root.querySelector('#new-ledger')?.addEventListener('click',()=>ledgerEditor());
  ui.root.querySelector('#confirm-carry')?.addEventListener('click',()=>act(`${money(f.carry_suggested)}을 전 학기 이월금으로 확정할까요?`,()=>api('POST',`/api/semesters/${s.semester.id}/carry`,{amount:f.carry_suggested})));
}

function ledgerEditor(row=null){
  dialog(row?'회계 항목 수정':'회계 항목 추가',`${input('title','내용',row?.title||'','text',true)}${input('date','날짜',row?.date||todayKst(),'date',true)}<div class="form-columns"><label>구분<select name="direction">${['수입','지출'].map(x=>`<option ${row?.direction===x?'selected':''}>${x}</option>`).join('')}</select></label><label>분류<select name="classification">${ui.state.finance.classifications.map(x=>`<option ${row?.classification===x?'selected':''}>${esc(x)}</option>`).join('')}</select></label></div>${input('amount','금액 (원)',row?.amount||'','number',true)}${input('owner','담당자',row?.owner||ui.state.me.name)}<label>비고<textarea name="note" rows="3">${esc(row?.note||'')}</textarea></label>`,'저장',async(f,requestId)=>{await api(row?'PUT':'POST',`/api/ledger${row?'/'+row.id:''}`,{request_id:requestId,edited_at:row?.edited_at,title:f.title.value,date:f.date.value,direction:f.direction.value,classification:f.classification.value,amount:Number(f.amount.value),owner:f.owner.value,note:f.note.value,semester:ui.state.semester.id});await ui.refresh();});
}

export function settingsView(){
  const s=ui.state;
  if(s.me.admin_role!=='head'){ui.root.innerHTML=emptyState('단장만 학기를 마감할 수 있어요');return;}
  const current=s.semesters.find(x=>x.state==='active'&&x.transition_at)||s.semesters.find(x=>x.id===s.current_semester),next=s.next_semester_title; // 이름 규칙은 서버 한 곳(next_semester)에만 둔다
  ui.root.innerHTML=`${back()}<section class="page-heading"><h1>학기 관리</h1><p class="muted">이전 학기 기록은 마감 후에도 수정할 수 있어요.</p></section><section class="card stack"><h2>${esc(current.title)}</h2><p>마감하면 ${esc(next)}가 바로 시작됩니다. 아직 시작하지 않은 일정은 자동으로 옮겨집니다.</p><button class="btn primary" id="close-semester" data-write>이번 학기 마감하기</button></section>`;
  ui.root.querySelector('#close-semester').onclick=()=>act(`${current.title}를 마감하고 ${next}를 시작할까요?`,async()=>{const result=await api('POST',`/api/semesters/${current.id}/close`);sessionStorage.setItem('glee-semester',result.id);});bindActions();
}
