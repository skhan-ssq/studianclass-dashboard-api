// js/app.js
let progressData=[],
certData=[],
chart;

const $=s=>document.querySelector(s);

const progressUrl='data/study_progress.json?v='+Date.now();
const certUrl='data/study_cert.json?v='+Date.now();

function ensureChart(labels,data){
  const ctx=document.getElementById('progressChart').getContext('2d');
  if(chart) chart.destroy();
  chart=new Chart(ctx,{
    type:'line',
    data:{labels,datasets:[{label:'진도율',data,pointRadius:2,tension:0.2}]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{y:{beginAtZero:true,min:0,max:100}}}
  });
}

function fillRooms(){
  const codes=[...new Set(progressData.map(r=>r.opentalk_code).filter(Boolean))].sort();
  const dl=$("#roomList"); dl.innerHTML='';
  codes.forEach(code=>{
    const opt=document.createElement('option');
    opt.value=code; // 입력값으로 쓰일 실제 코드
    dl.appendChild(opt);
  });
}

function fillNicknames(opentalkCode){
  const ndl=$("#nickList"); ndl.innerHTML='';
  if(!opentalkCode) return;
  const nicks=[...new Set(progressData.filter(r=>r.opentalk_code===opentalkCode).map(r=>r.nickname).filter(Boolean))].sort();
  nicks.forEach(n=>{
    const opt=document.createElement('option'); opt.value=n; ndl.appendChild(opt);
  });
}

function renderChart(code,nick){
  if(!(code&&nick)){ensureChart([],[]);return;}
  const rows=progressData.filter(r=>r.opentalk_code===code && r.nickname===nick)
                         .map(r=>({d:String(r.progress_date).slice(0,10),v:Number(r.progress)}))
                         .filter(x=>x.d && !Number.isNaN(x.v))
                         .sort((a,b)=>a.d.localeCompare(b.d));
  ensureChart(rows.map(x=>x.d), rows.map(x=>x.v));
}

function renderTable(code){
  const tb=$("#certTbody"); tb.innerHTML='';
  $("#certCount").textContent='';
  if(!code) return;
  const top=certData.filter(r=>r.opentalk_code===code)
                    .sort((a,b)=>(a.user_rank??9999)-(b.user_rank??9999))
                    .slice(0,20);
  top.forEach(r=>{
    const rank=r.user_rank??'';
    const cls=rank==1?'rank-1':rank==2?'rank-2':rank==3?'rank-3':'';
    const avg=(r.average_week!=null && r.average_week!=='')?Number(r.average_week).toFixed(1):'';
    const tr=document.createElement('tr');
    tr.innerHTML=`<td class="${cls}">${rank}</td><td>${r.name??''}</td><td>${r.cert_days_count??''}</td><td>${avg}</td>`;
    tb.appendChild(tr);
  });
  $("#certCount").textContent=`총 ${top.length}명 (상위 20명 표시)`;
}

async function load(){
  const [p,c]=await Promise.all([fetch(progressUrl,{cache:'no-store'}),fetch(certUrl,{cache:'no-store'})]);
  progressData=await p.json(); certData=await c.json();
  fillRooms(); fillNicknames($('#roomInput').value.trim());
  ensureChart([],[]);
}

$('#roomInput').addEventListener('change',()=>{
  fillNicknames($('#roomInput').value.trim());
  $('#nickInput').value='';
});

$('#applyBtn').addEventListener('click',()=>{
  const code=$('#roomInput').value.trim();
  const nick=$('#nickInput').value.trim();
  $('#picked').textContent=(code?`[${code}]`:'')+(nick?` ${nick}`:'');
  renderChart(code,nick);
  renderTable(code);
});

load().catch(e=>{
  console.error(e);
  document.body.insertAdjacentHTML('beforeend','<p class="muted">데이터를 불러오지 못했습니다.</p>');
});
