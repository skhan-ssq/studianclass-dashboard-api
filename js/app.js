// js/app.js — 표시명 적용 + 닉네임 합집합 + 날짜포맷
let progressData = [],
certData = [],
chart, 
roomCodes = [];
let roomCodeByLabel = new Map();

const $ = s => document.querySelector(s);

const progressUrl = 'data/study_progress.json?v=' + Date.now();
const certUrl     = 'data/study_cert.json?v=' + Date.now();
const toArray = d => Array.isArray(d) ? d : (d && Array.isArray(d.rows) ? d.rows : []);

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


/*
  // 표시명 → 코드
function roomCodeFromLabel(label){
  const m = String(label).match(/^(\d{2})년\s*(\d{2})월\s*(.+?)\s*단톡방$/);
  if(!m) return label; // 이미 코드일 수 있음
  const [, yy, mm, courseText] = m;
  const rev = { '기초 영어회화 100':'기초', '영어회화 100':'영어', '구동사 100':'구동' };
  const key = rev[courseText] || courseText;
  return yy + mm + key;
}
*/


// 날짜 포맷: MM/DD(요일)
function fmtDateLabel(iso){
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const w = ['일','월','화','수','목','금','토'][d.getDay()];
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  return `${mm}/${dd}(${w})`;
}

function ensureChart(labels, data){
  const ctx = document.getElementById('progressChart').getContext('2d');
  if(chart) chart.destroy();
  chart = new Chart(ctx,{
    type:'line',
    data:{labels, datasets:[{label:'진도율', data, pointRadius:2, tension:0.2}]},
    options:{responsive:true, maintainAspectRatio:false, interaction:{mode:'index', intersect:false}, scales:{y:{beginAtZero:true, min:0, max:100}}}
  });
}

// 방 목록(datalist): 값=코드, 라벨=표시명
function fillRooms(){
  // (수정) progressData만 사용
  roomCodes = [...new Set(progressData.map(r=>r.opentalk_code).filter(Boolean))].sort();

  const dl = $("#roomList"); dl.innerHTML = '';

  // (추가) 라벨→코드 맵 초기화
  roomCodeByLabel = new Map();

  roomCodes.forEach(code=>{
    const opt = document.createElement('option');
    // (수정) 값=라벨만 보이게
    const label = roomLabelFromCode(code);
    opt.value = label;
    // (추가) 라벨→코드 보관
    roomCodeByLabel.set(label, code);
    dl.appendChild(opt);
  });

  // (수정) 입력값(라벨)→코드 변환해서 전달
  const selectedCode = roomCodeByLabel.get($('#roomInput').value.trim()) || null;
  fillNicknames(selectedCode);
}

// 닉네임 목록: progress + cert 합집합
function fillNicknames(opentalkCode){
  const ndl=$("#nickList"); ndl.innerHTML='';
  if(!opentalkCode) return;
  const fromProgress = progressData.filter(r=>r.opentalk_code===opentalkCode).map(r=>r.nickname);
  const fromCert     = certData.filter(r=>r.opentalk_code===opentalkCode).map(r=>r.name);
  const nicks = [...new Set(fromProgress.concat(fromCert).filter(Boolean))].sort();
  nicks.forEach(n=>{ const o=document.createElement('option'); o.value=n; ndl.appendChild(o); });
}

function renderChart(code,nick){
  if(!(code&&nick)){ ensureChart([],[]); return; }
  const rows = progressData
    .filter(r=>r.opentalk_code===code && r.nickname===nick)
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
  const top = all.sort((a,b)=>(a.user_rank??9999)-(b.user_rank??9999)).slice(0,20);

  top.forEach(r=>{
    const rank=r.user_rank??'';
    const cls = rank==1?'rank-1':rank==2?'rank-2':rank==3?'rank-3':'';
    const avg = (r.average_week!=null && r.average_week!=='')? Number.parseFloat(r.average_week).toFixed(1):'';
    const tr=document.createElement('tr');
    tr.innerHTML = `<td class="${cls}">${rank}</td><td>${r.name??''}</td><td>${r.cert_days_count??''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });

  const label = roomLabelFromCode(code);
  $("#certCount").textContent = `[${label}] 총 ${all.length}명 중 상위 20명`;
}

async function load(){
  const [p,c]=await Promise.all([
    fetch(progressUrl,{cache:'no-store'}),
    fetch(certUrl,{cache:'no-store'})
  ]);
  progressData = toArray(await p.json());
  certData     = toArray(await c.json());
  fillRooms();
  ensureChart([],[]);
}

// 입력 변경: 라벨로 입력해도 코드로 환원
$('#roomInput').addEventListener('change', ()=>{
  let val = $('#roomInput').value.trim();
  if(val && !roomCodes.includes(val)){
    val = roomCodeFromLabel(val);
    $('#roomInput').value = val;
  }
  fillNicknames(val);
  $('#nickInput').value = '';
});

// 적용 클릭: 표시명/제목 모두 갱신
$('#applyBtn').addEventListener('click', ()=>{
  let code = $('#roomInput').value.trim();
  if(code && !roomCodes.includes(code)) code = roomCodeFromLabel(code);
  const nick = $('#nickInput').value.trim();
  const label = roomLabelFromCode(code);

  $('#picked').textContent = (code?`[${label}]`:'') + (nick?` ${nick}`:'');
  const titleEl = document.getElementById('chartTitle');
  if(titleEl) titleEl.textContent = (code && nick) ? `${label} ${nick}님의 진도율(%)` : '진도율(%)';

  renderChart(code, nick);
  renderTable(code);
});

load().catch(e=>{
  console.error(e);
  document.body.insertAdjacentHTML('beforeend','<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
