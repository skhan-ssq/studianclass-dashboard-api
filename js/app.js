// js/app.js — 방: select(진짜 값=opentalk_code), 닉네임: datalist, 업데이트 시각/타이틀 반영(최종본)
let progressData = []; // study_progress.json.rows
let certData = [];     // study_cert.json.rows (닉네임 보강용만 사용)
let chart;
let roomCodes = [];

const $ = s => document.querySelector(s);
const progressUrl = 'data/study_progress.json?v=' + Date.now();
const certUrl     = 'data/study_cert.json?v=' + Date.now();

/* ========== 유틸 ========== */
// progress JSON(rows 전용) 파싱
function getProgressRows(pj){
  if (pj && Array.isArray(pj.rows)) return pj.rows;
  if (pj && Array.isArray(pj.json_study_user_progress)) return pj.json_study_user_progress; // 예비
  return [];
}
// cert JSON(rows 전용) 파싱
function getCertRows(cj){
  if (cj && Array.isArray(cj.rows)) return cj.rows;
  if (cj && Array.isArray(cj.json_study_cert)) return cj.json_study_cert; // 예비
  return [];
}
// 업데이트 시각(fallback: 최신 progress_date)
function computeShownAt(pj, rows){
  const ga = pj && pj.generated_at ? new Date(pj.generated_at) : null;
  if (ga && !Number.isNaN(ga)) return ga;
  let m=null;
  for(const r of rows){
    const d = r?.progress_date ? new Date(String(r.progress_date)) : null;
    if(d && !Number.isNaN(d)) m = (!m || d>m) ? d : m;
  }
  return m;
}
// 코드 → 표시명
function roomLabelFromCode(code){
  if(!code) return '';
  const m = String(code).match(/^(\d{2})(\d{2})(.+)$/); // YY MM KEY
  if(!m) return code;
  const [, yy, mm, key] = m;
  const courseMap = { '기초':'기초 영어회화 100', '영어':'영어회화 100', '구동':'구동사 100' };
  const course = courseMap[key] || key;
  return `${yy}년 ${mm}월 ${course} 단톡방`;
}
// 방 select에서 코드 얻기
function getSelectedRoomCode(){
  const sel = $('#roomSelect');
  return sel && sel.value ? sel.value : null; // value=opentalk_code
}
// 날짜 라벨: MM/DD(요일)
function fmtDateLabel(iso){
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const w  = ['일','월','화','수','목','금','토'][d.getDay()];
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  return `${mm}/${dd}(${w})`;
}

/* ========== 차트 ========== */
function ensureChart(labels, data){
  const ctx = document.getElementById('progressChart').getContext('2d');
  if(chart) chart.destroy();
  chart = new Chart(ctx,{
    type:'line',
    data:{labels, datasets:[{label:'진도율', data, pointRadius:2, tension:0.2}]},
    options:{responsive:true, maintainAspectRatio:false, interaction:{mode:'index', intersect:false}, scales:{y:{beginAtZero:true, min:0, max:100}}}
  });
}

/* ========== 드롭다운/목록 ========== */
// ★ 방 목록은 progress(rows[].opentalk_code)만 사용
function fillRooms(){
  roomCodes = [...new Set(
    progressData.map(r=>r.opentalk_code).filter(Boolean)
  )].sort((a,b)=>a.localeCompare(b,'ko'));

  const sel = $("#roomSelect");
  sel.innerHTML = '<option value="">단톡방 명을 선택하세요 ▼</option>';

  roomCodes.forEach(code=>{
    const opt = document.createElement('option');
    opt.value = code;                // 내부 값: 코드
    opt.textContent = roomLabelFromCode(code); // 화면: 긴 이름
    sel.appendChild(opt);
  });

  // 닉네임 초기화(datalist)
  $('#nickInput').value = '';
  $("#nickList").innerHTML = '';
}

// 닉네임 목록: progress.nickname 우선 + cert.name 보강 (cert는 목록 보강만, 방엔 영향 X)
function fillNicknames(opentalkCode){
  const ndl = $("#nickList");
  ndl.innerHTML = '';
  if(!opentalkCode) return;

  const fromProgress = progressData
    .filter(r=>r.opentalk_code===opentalkCode)
    .map(r=>String(r.nickname||'').trim())
    .filter(Boolean);

  const nickSet = new Set(fromProgress);

  const fromCertOnly = certData
    .filter(r=>r.opentalk_code===opentalkCode && !nickSet.has(String(r.nickname||r.name||'').trim()))
    .map(r=>String((r.nickname||r.name||'')).trim())
    .filter(Boolean);

  const options = [...nickSet, ...new Set(fromCertOnly)].sort((a,b)=>a.localeCompare(b,'ko'));
  options.forEach(v=>{ const o=document.createElement('option'); o.value=v; ndl.appendChild(o); });
}

/* ========== 렌더 ========== */
function updateChartTitle(code, nick){
  const el = $('#chartTitle');
  if(!el) return;
  if(code && nick){ el.textContent = `[${roomLabelFromCode(code)}]의 ${nick}님의 진도율(%)`; }
  else if(code){    el.textContent = `[${roomLabelFromCode(code)}]의 진도율(%)`; }
  else{             el.textContent = '진도율(%)'; }
}

function renderChart(code, nick){
  if(!(code && nick)){ ensureChart([],[]); return; }
  const rows = progressData
    .filter(r=>r.opentalk_code===code && String(r.nickname||'').trim()===(nick||'').trim())
    .map(r=>({ d:String(r.progress_date).slice(0,10), v:Number.parseFloat(r.progress) }))
    .filter(x=>x.d && Number.isFinite(x.v))
    .sort((a,b)=>a.d.localeCompare(b.d));
  ensureChart(rows.map(x=>fmtDateLabel(x.d)), rows.map(x=>x.v));
}

function renderTable(code){
  const tb=$("#certTbody"); tb.innerHTML='';
  $("#certCount").textContent='';
  if(!code) return;

  const all = certData.filter(r=>r.opentalk_code===code);
  const top = all.slice().sort((a,b)=>(a.user_rank??9999)-(b.user_rank??9999)).slice(0,20);

  top.forEach(r=>{
    const rank=r.user_rank??'';
    const cls = rank==1?'rank-1':rank==2?'rank-2':rank==3?'rank-3':'';
    const displayName = (r.nickname && r.nickname.trim())
      ? r.nickname.trim()
      : (r.name && r.name.trim()) ? r.name.trim() : '';
    const avg = (r.average_week!=null && r.average_week!=='')
      ? Number.parseFloat(r.average_week).toFixed(1) : '';
    const tr=document.createElement('tr');
    tr.innerHTML = `<td class="${cls}">${rank}</td><td>${displayName}</td><td>${r.cert_days_count??''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });

  $("#certCount").textContent = `[${roomLabelFromCode(code)}] 총 ${all.length}명 중 상위 20명`;
}

/* ========== 이벤트 ========== */
$('#roomSelect').addEventListener('change', ()=>{
  const code = getSelectedRoomCode();
  fillNicknames(code);
  updateChartTitle(code, ($('#nickInput').value||'').trim());
});
$('#nickInput').addEventListener('input', ()=>{
  const code = getSelectedRoomCode();
  updateChartTitle(code, ($('#nickInput').value||'').trim());
});
$('#applyBtn').addEventListener('click', ()=>{
  const code = getSelectedRoomCode();
  const nick = ($('#nickInput').value || '').trim();
  updateChartTitle(code, nick);
  renderChart(code, nick);
  renderTable(code);
});

/* ========== 데이터 로드 ========== */
async function load(){
  const [p,c] = await Promise.all([
    fetch(progressUrl,{cache:'no-store'}),
    fetch(certUrl,{cache:'no-store'})
  ]);
  const pj = await p.json().catch(()=>({}));
  const cj = await c.json().catch(()=>({}));

  // 방 목록은 progress(rows)만 사용
  progressData = getProgressRows(pj);
  // 닉네임 보강용 cert(rows) (방 리스트에는 영향 없음)
  certData = getCertRows(cj);

  fillRooms();
  ensureChart([],[]);
  updateChartTitle(null,'');

  // 업데이트 시각 표시(우측)
  const shownAt = computeShownAt(pj, progressData);
  $('#updateTime').textContent = shownAt
    ? `최근 업데이트 시각 : ${shownAt.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}`
    : '';

  // 방 데이터가 전혀 없을 때 안내
  if(roomCodes.length===0){
    $('#roomSelect').innerHTML = '<option value="">단톡방 데이터를 찾지 못했습니다</option>';
  }
}
load().catch(e=>{
  console.error(e);
  document.body.insertAdjacentHTML('beforeend','<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
