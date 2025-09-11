// js/app.js (진단 전용)
const $=s=>document.querySelector(s);
const log=(m)=>{console.log(m); const p=document.createElement('p'); p.textContent=m; p.className='muted'; document.body.appendChild(p);};

let progressData=[], certData=[];
(async()=>{
  try{
    log('1) app.js 로드됨');

    // JSON 로드
    const [p,c]=await Promise.all([
      fetch('data/study_progress.json?v='+Date.now(),{cache:'no-store'}),
      fetch('data/study_cert.json?v='+Date.now(),{cache:'no-store'})
    ]);
    if(!p.ok) throw new Error('study_progress.json '+p.status);
    if(!c.ok) throw new Error('study_cert.json '+c.status);
    progressData=await p.json();
    certData=await c.json();
    log('2) JSON 로드 완료: progress '+progressData.length+' rows, cert '+certData.length+' rows');

    // 필수 키 1개라도 없으면 경고
    const sample=progressData[0]||{};
    ['opentalk_code','nickname','progress_date','progress'].forEach(k=>{
      if(!(k in sample)) log('⚠ progress 키 누락: '+k);
    });

    // 방 목록 채우기
    const codes=[...new Set(progressData.map(r=>r.opentalk_code).filter(Boolean))].sort();
    const dl=$("#roomList"); if(!dl){log('❌ #roomList 없음'); return;}
    dl.innerHTML='';
    codes.forEach(code=>{const opt=document.createElement('option'); opt.value=code; dl.appendChild(opt);});
    log('3) 방 목록 채움: '+codes.length+'개');

    // 닉네임 목록(첫 방 기준)
    const roomInput=$("#roomInput"); if(!roomInput){log('❌ #roomInput 없음');return;}
    if(!roomInput.value && codes[0]) roomInput.value=codes[0];
    const nicks=[...new Set(progressData.filter(r=>r.opentalk_code===roomInput.value).map(r=>r.nickname).filter(Boolean))].sort();
    const ndl=$("#nickList"); if(!ndl){log('❌ #nickList 없음');return;}
    ndl.innerHTML=''; nicks.forEach(n=>{const o=document.createElement('option'); o.value=n; ndl.appendChild(o);});
    log('4) 닉네임 목록 채움: '+nicks.length+'개');

    // 적용 버튼 동작만 연결(차트는 생략)
    const btn=$("#applyBtn"); if(!btn){log('❌ #applyBtn 없음');return;}
    btn.addEventListener('click',()=>{
      const code=$("#roomInput").value.trim();
      const nick=$("#nickInput").value.trim();
      log('적용 클릭 → code='+code+', nick='+nick);
      const rows=progressData.filter(r=>r.opentalk_code===code && r.nickname===nick);
      log('선택된 시계열 행 수: '+rows.length);
      const top=certData.filter(r=>r.opentalk_code===code).sort((a,b)=>(a.user_rank??9999)-(b.user_rank??9999)).slice(0,20);
      log('상위 표 행 수: '+top.length);
    });

  }catch(e){
    console.error(e);
    log('❌ 오류: '+e.message);
  }
})();
