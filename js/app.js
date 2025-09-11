// js/app.js
let progressData = [];
let certData = [];
let chart;

async function loadData() {
  // 1) JSON 두 개 읽어오기
  const [pRes, cRes] = await Promise.all([
    fetch('data/study_progress.json'),
    fetch('data/study_cert.json')
  ]);
  progressData = await pRes.json();
  certData = await cRes.json();

  // 2) 드롭다운 채우기
  initDropdowns();

  // 3) 초기 렌더
  render();
}

function initDropdowns() {
  const codes = [...new Set(progressData.map(r => r.opentalk_code))];
  const codeSel = document.getElementById('opentalkSelect');
  codeSel.innerHTML = codes.map(c => `<option value="${c}">${c}</option>`).join('');
  codeSel.addEventListener('change', refreshNicknames);

  document.getElementById('applyBtn').addEventListener('click', render);

  refreshNicknames();
}

function refreshNicknames() {
  const code = document.getElementById('opentalkSelect').value;
  const nicks = [...new Set(progressData.filter(r => r.opentalk_code === code).map(r => r.nickname))];
  const nickSel = document.getElementById('nickSelect');
  nickSel.innerHTML = nicks.map(n => `<option value="${n}">${n}</option>`).join('');
}

function render() {
  const code = document.getElementById('opentalkSelect').value;
  const nick = document.getElementById('nickSelect').value;

  // --- 차트용 데이터 ---
  const rows = progressData.filter(r => r.opentalk_code === code && r.nickname === nick);
  const labels = rows.map(r => r.progress_date);
  const values = rows.map(r => Number(r.progress));

  const ctx = document.getElementById('progressChart').getContext('2d');
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: '진도율', data: values }] },
    options: { responsive: true, animation: false }
  });

  // --- 표 렌더링 ---
  const tbody = document.querySelector('#certTable tbody');
  tbody.innerHTML = '';
  certData
    .filter(r => r.opentalk_code === code)
    .sort((a, b) => a.user_rank - b.user_rank)
    .slice(0, 20)
    .forEach((row, idx) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${idx+1}</td><td>${row.name}</td><td>${row.cert_days_count}</td><td>${row.average_week}</td>`;
      tbody.appendChild(tr);
    });
}

// 실행 시작
loadData();

