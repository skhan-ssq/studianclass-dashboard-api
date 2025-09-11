// js/app.js (rows 지원 + 숫자 파싱)
let progressData = [], certData = [], chart;
const $ = s => document.querySelector(s);

const progressUrl = 'data/study_progress.json?v=' + Date.now();
const certUrl = 'data/study_cert.json?v=' + Date.now();

const toArray = d => Array.isArray(d) ? d : (d && Array.isArray(d.rows) ? d.rows : []);

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

// 방 목록 datalist 채우기
function fillRooms() {
  const codes = [...new Set(progressData.map(r => r.opentalk_code).filter(Boolean))].sort();
  const dl = $("#roomList"); dl.innerHTML = '';
  codes.forEach(code => {
    const opt = document.createElement('option');
    opt.value = code; dl.appendChild(opt);
  });
  if (!$('#roomInput').value && codes[0]) $('#roomInput').value = codes[0];
  fillNicknames($('#roomInput').value.trim());
}

// 닉네임 목록 채우기
function fillNicknames(opentalkCode) {
  const ndl = $("#nickList"); ndl.innerHTML = '';
  if (!opentalkCode) return;
  const nicks = [...new Set(progressData
    .filter(r => r.opentalk_code === opentalkCode)
    .map(r => r.nickname).filter(Boolean))].sort();
  nicks.forEach(n => { const o = document.createElement('option'); o.value = n; ndl.appendChild(o); });
}

// 차트 렌더
function renderChart(code, nick) {
  if (!(code && nick)) { ensureChart([], []); return; }
  const rows = progressData
    .filter(r => r.opentalk_code === code && r.nickname === nick)
    .map(r => ({
      d: String(r.progress_date).slice(0, 10),
      v: Number.parseFloat(r.progress) // 문자열→숫자
    }))
    .filter(x => x.d && Number.isFinite(x.v))
    .sort((a, b) => a.d.localeCompare(b.d));

  ensureChart(rows.map(x => x.d), rows.map(x => x.v));
}

// 표 렌더
function renderTable(code) {
  const tb = $("#certTbody"); tb.innerHTML = '';
  $("#certCount").textContent = '';
  if (!code) return;

  const top = certData
    .filter(r => r.opentalk_code === code)
    .sort((a, b) => (a.user_rank ?? 9999) - (b.user_rank ?? 9999))
    .slice(0, 20);

  top.forEach(r => {
    const rank = r.user_rank ?? '';
    const cls = rank == 1 ? 'rank-1' : rank == 2 ? 'rank-2' : rank == 3 ? 'rank-3' : '';
    const avg = (r.average_week != null && r.average_week !== '')
      ? Number.parseFloat(r.average_week).toFixed(1) : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="${cls}">${rank}</td><td>${r.name ?? ''}</td><td>${r.cert_days_count ?? ''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });
  $("#certCount").textContent = `총 ${top.length}명 (상위 20명 표시)`;
}

// 초기 로드
async function load() {
  const [p, c] = await Promise.all([
    fetch(progressUrl, { cache: 'no-store' }),
    fetch(certUrl, { cache: 'no-store' })
  ]);
  const pJson = await p.json();
  const cJson = await c.json();

  // rows 추출
  progressData = toArray(pJson);
  certData = toArray(cJson);

  // 로깅(원하면 주석)
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
  $('#picked').textContent = (code ? `[${code}]` : '') + (nick ? ` ${nick}` : '');
  renderChart(code, nick);
  renderTable(code);
});

load().catch(e => {
  console.error(e);
  document.body.insertAdjacentHTML('beforeend', '<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
