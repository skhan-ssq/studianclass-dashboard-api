// js/app.js — 표시명 적용 + 닉네임 합집합 + 날짜포맷
let progressData = [];
let certData = [];
let chart;
let roomCodes = [];
let roomCodeByLabel = new Map();

const $ = s => document.querySelector(s);

const progressUrl = 'data/study_progress.json?v=' + Date.now();
const certUrl = 'data/study_cert.json?v=' + Date.now();
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

// 라벨 → 코드
function getSelectedRoomCode(){
  const label = $('#roomInput').value.trim();
  return roomCodeByLabel.get(label) || null;
}

// 날짜 포맷: MM/DD(요일)
function fmtDateLabel(iso){
  const d = new Date(iso);
  if(Number.isNaN(d.getTime())) return iso;
  const w = ['일','월','화','수','목','금','토'][d.getDay()];
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${mm}/${dd}(${w})`;
}

function ensureChart(labels, data){
  const ctx = document.getElementById('progressChart').getContext('2d');
  if(chart) chart.destroy();
  chart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: '진도율', data, pointRadius: 2, tension: 0.2 }] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, scales: { y: { beginAtZero: true, min: 0, max: 100 } } }
  });
}

// 방 목록(datalist): 화면엔 라벨만, 내부는 코드 매핑
function fillRooms(){
  roomCodes = [...new Set(progressData.map(r => r.opentalk_code).filter(Boolean))].sort();
  roomCodeByLabel = new Map();
  const dl = $("#roomList");
  dl.innerHTML = '';
  roomCodes.forEach(code => {
    const label = roomLabelFromCode(code);
    roomCodeByLabel.set(label, code);
    const opt = document.createElement('option');
    opt.value = label; // 긴 이름만 표시
    dl.appendChild(opt);
  });
  fillNicknames(getSelectedRoomCode());
}

// 닉네임 목록: progress + cert 합집합(선택된 코드 기준)
function fillNicknames(opentalkCode){
  const ndl = $("#nickList");
  ndl.innerHTML = '';
  if(!opentalkCode) return;
  const fromProgress = progressData
    .filter(r => r.opentalk_code === opentalkCode)
    .map(r => r.nickname && r.nickname.trim())
    .filter(Boolean);
  const fromCert = certData
    .filter(r => r.opentalk_code === opentalkCode)
    .map(r => r.name && r.name.trim())
    .filter(Boolean);
  const nicks = [...new Set(fromProgress.concat(fromCert))].sort((a, b) => a.localeCompare(b, 'ko'));
  nicks.forEach(n => { const o = document.createElement('option'); o.value = n; ndl.appendChild(o); });
}

function renderChart(code, nick){
  if(!(code && nick)){ ensureChart([], []); return; }
  const rows = progressData
    .filter(r => r.opentalk_code === code && r.nickname === nick)
    .map(r => ({ d: String(r.progress_date).slice(0, 10), v: Number.parseFloat(r.progress) }))
    .filter(x => x.d && Number.isFinite(x.v))
    .sort((a, b) => a.d.localeCompare(b.d));
  ensureChart(rows.map(x => fmtDateLabel(x.d)), rows.map(x => x.v));
}

function renderTable(code, label){
  const tb = $("#certTbody");
  tb.innerHTML = '';
  $("#certCount").textContent = '';
  const title = document.getElementById('certTitle'); // HTML에 <h3 id="certTitle"> 준비
  if(title) title.textContent = code ? `${label} 의 인증 현황` : '인증 현황 (상위 20명)';
  if(!code) return;
  const all = certData.filter(r => r.opentalk_code === code);
  const top = all.sort((a, b) => (a.user_rank ?? 9999) - (b.user_rank ?? 9999)).slice(0, 20);
  top.forEach(r => {
    const rank = r.user_rank ?? '';
    const cls = rank == 1 ? 'rank-1' : rank == 2 ? 'rank-2' : rank == 3 ? 'rank-3' : '';
    const avg = (r.average_week != null && r.average_week !== '') ? Number.parseFloat(r.average_week).toFixed(1) : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="${cls}">${rank}</td><td>${r.name ?? ''}</td><td>${r.cert_days_count ?? ''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });
  $("#certCount").textContent = `[${label}] 총 ${all.length}명 중 상위 20명`;
}

async function load(){
  const [p, c] = await Promise.all([
    fetch(progressUrl,{cache:'no-store'}),
    fetch(certUrl,{cache:'no-store'})
  ]);
  const pj = await p.json();
  const cj = await c.json();
  progressData = toArray(pj);
  certData = toArray(cj);
  fillRooms();
  ensureChart([],[]);
  const updateAt = (pj && pj.generated_at) || (cj && cj.generated_at);
  if(updateAt){
    const d = new Date(updateAt);
    const formatted = d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
    $('#updateTime').textContent = `최근 업데이트 시각 : ${formatted}`;
  }else{
    $('#updateTime').textContent = '';
  }
}


$('#roomInput').addEventListener('change', () => {
  fillNicknames(getSelectedRoomCode());
  $('#nickInput').value = '';
});
$('#roomInput').addEventListener('input', () => {
  fillNicknames(getSelectedRoomCode());
});

$('#applyBtn').addEventListener('click', () => {
  const code = getSelectedRoomCode();
  const nick = $('#nickInput').value.trim();
  const label = roomLabelFromCode(code);

  // 그래프 제목: "[긴 단톡방 명] [닉네임]님의 진도율(%)"
  const titleEl = document.getElementById('chartTitle'); // HTML에 <h3 id="chartTitle"> 준비
  if(titleEl) titleEl.textContent = (code && nick) ? `${label} ${nick}님의 진도율(%)` : '진도율(%)';
  renderChart(code, nick);
  renderTable(code, label);
});

load().catch(e => {
  console.error(e);
  document.body.insertAdjacentHTML('beforeend', '<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
