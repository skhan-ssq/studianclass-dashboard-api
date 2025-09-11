// rows 구조 지원 + 문자열 숫자 변환(datalist 버전)
let progressData = [], certData = [], chart;
const $ = s => document.querySelector(s);

const progressUrl = 'data/study_progress.json?v=' + Date.now();
const certUrl     = 'data/study_cert.json?v=' + Date.now();

// 최상위 배열도, {rows:[...]}도 모두 허용
const toArray = d => Array.isArray(d) ? d : (d && Array.isArray(d.rows) ? d.rows : []);

// 차트
function ensureChart(labels, data) {
  const ctx = document.getElementById('progressChart').getContext('2d');
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: '진도율', data, pointRadius: 2, tension: 0.2 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: true, min: 0, max: 100 } }
    }
  });
}

// 방 코드 목록 datalist 채우기
function fillRooms() {
  const codes = [...new Set(progressData.map(r => r.opentalk_code).filter(Boolean))].sort();
  const dl = $("#roomList"); dl.innerHTML = '';
  codes.forEach(code => { const opt = document.createElement('option'); opt.value = code; dl.appendChild(opt); });
  fillNicknames($('#roomInput').value.trim());
}

// 선택된 방의 닉네임 datalist 채우기
function fillNicknames(opentalkCode) {
  const ndl = $("#nickList"); ndl.innerHTML = '';
  if (!opentalkCode) return;
  const nicks = [...new Set(
    progressData.filter(r => r.opentalk_code === opentalkCode)
                .map(r => r.nickname).filter(Boolean)
  )].sort();
  nicks.forEach(n => { const o = document.createElement('option'); o.value = n; ndl.appendChild(o); });
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

function fmtDateLabel(iso){
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const w = ['일','월','화','수','목','금','토'][d.getDay()];
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  return `${mm}/${dd}(${w})`;
}

// 차트 렌더
function renderChart(code, nick){
  if(!(code&&nick)){ ensureChart([],[]); return; }
  const rows = progressData
    .filter(r => r.opentalk_code===code && r.nickname===nick)
    .map(r => ({
      d: String(r.progress_date).slice(0,10),
      v: Number.parseFloat(r.progress) // 문자열→숫자
    }))
    .filter(x => x.d && Number.isFinite(x.v))
    .sort((a,b)=>a.d.localeCompare(b.d));

  const labels = rows.map(x => fmtDateLabel(x.d));
  const values = rows.map(x => x.v);
  ensureChart(labels, values);
}

// 표 렌더
function renderTable(code){
  const tb = $("#certTbody"); tb.innerHTML = '';
  $("#certCount").textContent = '';
  if(!code) return;

  const all = certData.filter(r => r.opentalk_code === code);
  const top = all
    .sort((a,b)=>(a.user_rank??9999)-(b.user_rank??9999))
    .slice(0,20);

  top.forEach(r=>{
    const rank = r.user_rank ?? '';
    const cls  = rank==1?'rank-1':rank==2?'rank-2':rank==3?'rank-3':'';
    const avg  = (r.average_week!=null && r.average_week!=='')
                   ? Number.parseFloat(r.average_week).toFixed(1) : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="${cls}">${rank}</td><td>${r.name??''}</td><td>${r.cert_days_count??''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });

  const label = roomLabelFromCode(code);
  $("#certCount").textContent = `[${label}] 총 ${all.length}명 중 상위 20명`;
}


// 초기 로드
async function load() {
  const [p, c] = await Promise.all([
    fetch(progressUrl, { cache: 'no-store' }),
    fetch(certUrl,     { cache: 'no-store' })
  ]);
  const pJson = await p.json();
  const cJson = await c.json();

  progressData = toArray(pJson);
  certData     = toArray(cJson);

  // 콘솔 확인용(원하면 지워도 됨)
  console.log('progress rows:', progressData.length, 'cert rows:', certData.length);

  fillRooms();
  ensureChart([], []);
}

// 이벤트
$('#roomInput').addEventListener('change', () => {
  const code = $('#roomInput').value.trim();
  fillNicknames(code);
  $('#nickInput').value = '';
});

$('#applyBtn').addEventListener('click', () => {
  const code = $('#roomInput').value.trim();
  const nick = $('#nickInput').value.trim();
  const label = roomLabelFromCode(code);

  // 상단 선택 라벨
  $('#picked').textContent = (code?`[${label}]`:'') + (nick?` ${nick}`:'');

  // 차트 제목 갱신
  const titleEl = document.getElementById('chartTitle');
  titleEl.textContent = (code && nick) ? `${label} ${nick}님의 진도율(%)` : '진도율(%)';

  renderChart(code, nick);
  renderTable(code);
});



load().catch(e => {
  console.error(e);
  document.body.insertAdjacentHTML('beforeend', '<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
