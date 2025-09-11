// js/app.js — datalist + 라벨 표시/역변환 + 날짜포맷
let progressData = [], certData = [], chart, roomCodes = [];
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
// 표시명 → 코드 (라벨로 입력했을 때 복원)
function roomCodeFromLabel(label){
  const m = String(label).match(/^(\d{2})년\s*(\d{2})월\s*(.+?)\s*단톡방$/);
  if(!m) return label; // 이미 코드일 수도 있음
  const [, yy, mm, courseText] = m;
  const rev = { '기초 영어회화 100':'기초', '영어회화 100':'영어', '구동사 100':'구동' };
  const key = rev[courseText] || courseText;
  return yy + mm + key;
}

// 날짜 포맷 mm/dd(요일)
function fmtDateLabel(iso){
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const w = ['일','월','화','수','목','금','토'][d.getDay()];
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  return `${mm}/${dd}(${w})`;
}

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

// 방 코드 목록 채우기 (datalist: 값=코드, 표시=라벨)
function fillRooms() {
  roomCodes = [...new Set(progressData.map(r => r.opentalk_code).filter(Boolean))].sort();
  const dl = $("#roomList"); dl.innerHTML = '';
  roomCodes.forEach(code => {
    const opt = document.createElement('option');
    opt.value = code;                   // 실제 값(코드)
    opt.label = roomLabelFromCode(code); // 사용자에게 보이는 라벨
    dl.appendChild(opt);
  });
  // 기본값 채우지 않음(placeholder 유지)
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

// 차트 렌더
function renderChart(code, nick) {
  if (!(code && nick)) { ensureChart([], []); return; }
  const rows = progressData
    .filter(r => r.opentalk_code === code && r.nickname === nick)
    .map(r => ({
      d: String(r.progress_date).slice(0, 10),
      v: Number.parseFloat(r.progress) // "64.00" -> 64
    }))
    .filter(x => x.d && Number.isFinite(x.v))
    .sort((a, b) => a.d.localeCompare(b.d));

  ensureChart(rows.map(x => fmtDateLabel(x.d)), rows.map(x => x.v));
}

// 표 렌더
function renderTable(code) {
  const tb = $("#certTbody"); tb.innerHTML = '';
  $("#certCount").textContent = '';
  if (!code) return;

  const all = certData.filter(r => r.opentalk_code === code);
  const top = all
    .sort((a, b) => (a.user_rank ?? 9999) - (b.user_rank ?? 9999))
    .slice(0, 20);

  top.forEach(r => {
    const rank = r.user_rank ?? '';
    const cls  = rank == 1 ? 'rank-1' : rank == 2 ? 'rank-2' : rank == 3 ? 'rank-3' : '';
    const avg  = (r.average_week != null && r.average_week !== '')
      ? Number.parseFloat(r.average_week).toFixed(1) : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="${cls}">${rank}</td><td>${r.name ?? ''}</td><td>${r.cert_days_count ?? ''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });

  const label = roomLabelFromCode(code);
  $("#certCount").textContent = `[${label}] 총 ${all.length}명 중 상위 20명`;
}

async function load() {
  const [p, c] = await Promise.all([
    fetch(progressUrl, { cache: 'no-store' }),
    fetch(certUrl,     { cache: 'no-store' })
  ]);
  const pJson = await p.json();
  const cJson = await c.json();

  progressData = toArray(pJson);
  certData     = toArray(cJson);

  fillRooms();
  ensureChart([], []);
}

// 입력 변경: 라벨로 입력한 경우 코드로 환원
$('#roomInput').addEventListener('change', () => {
  let val = $('#roomInput').value.trim();
  if (val && !roomCodes.includes(val)) {
    val = roomCodeFromLabel(val);       // 라벨 → 코드 변환
    $('#roomInput').value = val;
  }
  fillNicknames(val);
  $('#nickInput').value = '';
});

// 적용 클릭: 화면의 모든 라벨 텍스트 갱신
$('#applyBtn').addEventListener('click', () => {
  let code = $('#roomInput').value.trim();
  if (code && !roomCodes.includes(code)) code = roomCodeFromLabel(code);
  const nick = $('#nickInput').value.trim();
  const label = roomLabelFromCode(code);

  // 상단 선택 라벨
  $('#picked').textContent = (code ? `[${label}]` : '') + (nick ? ` ${nick}` : '');

  // 차트 제목
  const titleEl = document.getElementById('chartTitle');
  if (titleEl) titleEl.textContent = (code && nick) ? `${label} ${nick}님의 진도율(%)` : '진도율(%)';

  renderChart(code, nick);
  renderTable(code);
});

load().catch(e => {
  console.error(e);
  document.body.insertAdjacentHTML('beforeend', '<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
