// js/app.js — 라벨 표시 + 닉네임 우선 + 날짜포맷 + 완전본
let progressData = [];
let certData = [];
let chart;
let roomCodes = [];
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

// 입력창(라벨) → 코드
function getSelectedRoomCode(){
  const label = ($('#roomInput').value || '').trim();
  if (!label) return null;
  // 라벨로 매칭 실패 시: 혹시 사용자가 코드를 직접 넣었을 수도 있으니 그대로 사용
  return roomCodeByLabel.get(label) || (roomCodes.includes(label) ? label : null);
}

// 날짜 포맷: MM/DD(요일)
function fmtDateLabel(iso){
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const w  = ['일','월','화','수','목','금','토'][d.getDay()];
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

// 방 목록(datalist): 화면엔 라벨만, 내부는 코드 매핑
function fillRooms(){
  // progress + cert 합집합(둘 중 하나에만 있어도 방으로 노출)
  roomCodes = [...new Set(
    progressData.map(r=>r.opentalk_code)
      .concat(certData.map(r=>r.opentalk_code))
      .filter(Boolean)
  )].sort((a,b)=>a.localeCompare(b,'ko'));

  roomCodeByLabel = new Map();
  const dl = $("#roomList");
  dl.innerHTML = '';
  roomCodes.forEach(code=>{
    const label = roomLabelFromCode(code);
    roomCodeByLabel.set(label, code);
    const opt = document.createElement('option');
    opt.value = label; // 사용자는 긴 이름만 보게
    dl.appendChild(opt);
  });

  // 처음엔 닉네임 비워둠(placeholder 유지)
  $('#nickInput').value = '';
  $("#nickList").innerHTML = '';
}

// 닉네임 목록: progress(nickname) + cert(name) 합집합
function fillNicknames(opentalkCode){
  const ndl = $("#nickList");
  ndl.innerHTML = '';
  if(!opentalkCode) return;

  const fromProgress = progressData
    .filter(r=>r.opentalk_code===opentalkCode)
    .map(r=>r.nickname && r.nickname.trim())
    .filter(Boolean);

  const nickSet = new Set(fromProgress);

  const fromCertOnly = certData
    .filter(r=>r.opentalk_code===opentalkCode && !nickSet.has(r.name))
    .map(r=>r.name && r.name.trim())
    .filter(Boolean);

  const options = [...nickSet, ...new Set(fromCertOnly)].sort((a,b)=>a.localeCompare(b,'ko'));
  options.forEach(v=>{ const o=document.createElement('option'); o.value=v; ndl.appendChild(o); });
}

function renderChart(code, nick){
  if(!(code && nick)){ ensureChart([],[]); return; }
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
    // 이름 우선순위: nickname > name
    const displayName = (r.nickname && r.nickname.trim())
      ? r.nickname.trim()
      : (r.name && r.name.trim()) ? r.name.trim() : '';
    const avg = (r.average_week!=null && r.average_week!=='')
      ? Number.parseFloat(r.average_week).toFixed(1) : '';
    const tr=document.createElement('tr');
    tr.innerHTML =
      `<td class="${cls}">${rank}</td>
       <td>${displayName}</td>
       <td>${r.cert_days_count??''}</td>
       <td>${avg}</td>`;
    tb.appendChild(tr);
  });

  const label = roomLabelFromCode(code);
  $("#certCount").textContent = `[${label}] 총 ${all.length}명 중 상위 20명`;
}

// ▼ 이벤트
$('#roomInput').addEventListener('change', ()=>{
  const code = getSelectedRoomCode();
  fillNicknames(code);
  $('#nickInput').value = '';
});
$('#roomInput').addEventListener('input', ()=>{
  const code = getSelectedRoomCode();
  fillNicknames(code);
});

$('#applyBtn').addEventListener('click', ()=>{
  const code = getSelectedRoomCode();
  const nick = ($('#nickInput').value || '').trim();

  const label = code ? roomLabelFromCode(code) : '';
  const titleEl = document.getElementById('chartTitle');
  if(titleEl) titleEl.textContent = (code && nick) ? `${label} ${nick}님의 진도율(%)` : '진도율(%)';

  renderChart(code, nick);
  renderTable(code);
});

// ▼ 데이터 로드 (빠졌던 부분)
async function load(){
  const [p,c] = await Promise.all([
    fetch(progressUrl,{cache:'no-store'}),
    fetch(certUrl,{cache:'no-store'})
  ]);
  progressData = toArray(await p.json());
  certData     = toArray(await c.json());

  fillRooms();           // 방 목록 채우기
  ensureChart([],[]);    // 빈 차트 준비
}
load().catch(e=>{
  console.error(e);
  document.body.insertAdjacentHTML('beforeend','<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
