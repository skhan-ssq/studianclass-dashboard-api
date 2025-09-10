# 25.09.10
# main.py
# 기능 요약
# - /health: 헬스체크
# - /test: progress.json rows 페이징
# - /chart: 차트용 필드만 추출(date, rate, increased, total)
# - /dashboard: Chart.js 단일 페이지(HTML 문자열) 반환
# - 로컬에서 python main.py 실행 시 push만 수행(서버 미기동)
# - Render에선 uvicorn main:app ... 으로 서버 실행

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import json, os, subprocess
from collections import defaultdict
from typing import Optional
import argparse
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime, date
import threading


BASE_DIR = os.path.dirname(__file__)

# --- ★ 파일 경로(원하면 바꾸세요) ---
PROGRESS_JSON_PATH = os.path.join(BASE_DIR, "data", "study_progress.json")
CERT_JSON_PATH = os.path.join(BASE_DIR, "data", "study_cert.json")
BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")

def _env_bool(name: str, default: bool=False) -> bool:
    """
    환경변수 값이 true/yes/1/y 면 True, 그 외는 False 반환
    """
    return str(os.getenv(name, str(default))).strip().lower() in ("1","true","yes","y")


# -------------------- Git: push 한 번 --------------------
def _log(msg: str): print(msg, flush=True)

def _sh(cmd: str, check: bool = True):
    _log(f"$ {cmd}")
    cp = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if cp.stdout: _log(cp.stdout.strip())
    if check and cp.returncode != 0:
        raise RuntimeError((cp.stdout or "") + (cp.stderr or ""))
    return cp

def _push_once():
    _log("[push] start")
    # 리포/브랜치 보장
    _sh("git rev-parse --is-inside-work-tree")
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    if (cur.stdout or "").strip() != GIT_BRANCH:
        _sh(f"git checkout -B {GIT_BRANCH}")
    _sh("git config core.autocrlf false", check=False)
    _sh("git merge --abort", check=False)

    # main.py만 대상으로 커밋(변경 없으면 스킵)
    _sh("git restore --staged -q .", check=False)
    changed = subprocess.run("git diff --quiet -- main.py", shell=True).returncode == 1
    if changed:
        _sh("git add -- main.py", check=False)
        if subprocess.run("git diff --cached --quiet", shell=True).returncode == 1:
            _sh('git commit -m "chore: sync main.py on run"', check=False)
    else:
        _log("[push] no change in main.py; skip commit")

    # upstream 확인
    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first_push = (up.returncode != 0)

    # 1차: 일반 push
    cp = _sh(f"git push {'-u ' if first_push else ''}origin {GIT_BRANCH}", check=False)
    if cp.returncode == 0:
        _log("[push] done"); return

    _log("[push] normal push rejected, try rebase")
    # 2차: fetch + rebase 후 push
    _sh("git fetch origin", check=False)
    _sh(f"git rebase origin/{GIT_BRANCH}", check=False)
    cp2 = _sh(f"git push origin {GIT_BRANCH}", check=False)
    if cp2.returncode == 0:
        _log("[push] done"); return

    _log("[push] rebase push rejected, try force-with-lease (last resort)")
    # 3차: 안전 강제 푸시
    _sh(f"git push --force-with-lease origin {GIT_BRANCH}", check=False)
    _log("[push] done")



# -------------------- 데이터 로드 --------------------
def _load_rows():
    try:
        with open(DATA_PATH, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(500, detail="progress.json not found")
    except json.JSONDecodeError as e:
        raise HTTPException(500, detail={"error":"invalid JSON","msg":e.msg,"lineno":e.lineno,"colno":e.colno})
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return data["rows"]
    raise HTTPException(500, detail="Unexpected JSON format")



# --- 파일 캐시: 파일 mtime이 같으면 메모리 재사용 ---
_cache_lock = threading.Lock()
_cache = {}  # key=path -> {"mtime": float, "rows": list}

def _load_rows_from(path: str):
    try:
        mtime = os.path.getmtime(path)
        with _cache_lock:
            hit = _cache.get(path)
            if hit and hit["mtime"] == mtime:
                return hit["rows"]
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else (data.get("rows") or [])
        if not isinstance(rows, list):
            raise HTTPException(500, detail=f"Unexpected JSON format: {os.path.basename(path)}")
        with _cache_lock:
            _cache[path] = {"mtime": mtime, "rows": rows}
        return rows
    except FileNotFoundError:
        raise HTTPException(500, detail=f"{os.path.basename(path)} not found")
    except json.JSONDecodeError as e:
        raise HTTPException(500, detail={"file": os.path.basename(path), "error": "invalid JSON","msg":e.msg,"lineno":e.lineno,"colno":e.colno})

def _to_date(s) -> date|None:
    if not s: return None
    s = str(s)[:10]
    try: return datetime.fromisoformat(s).date()
    except: return None

def _to_num(x):
    try:
        if x is None or x == "": return None
        return float(x)
    except:
        return None



# -------------------- FastAPI --------------------
PUSH_ON_START = os.getenv("PUSH_ON_START","false").lower()=="true"
@asynccontextmanager
async def lifespan(app: FastAPI):
    if PUSH_ON_START:
        try:_push_once()
        except Exception as e:_log(f"[push warn] {e}")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/test")
def test(limit: int = Query(10, ge=1, le=1000), offset: int = Query(0, ge=0)):
    rows = _load_rows()
    sliced = rows[offset: offset + limit]
    return {"ok": True, "total": len(rows), "limit": limit, "offset": offset, "count": len(sliced), "rows": sliced}

# 차트용 데이터만 추출(필요 필드만 가볍게)
@app.get("/chart")
def chart():
    rows = _load_rows()
    pts = []
    for r in rows:
        d = r.get("progress_date")
        if not d:  # 날짜 없는 행은 제외
            continue
        pts.append({
            "date": d,
            "group": r.get("study_group_title"),
            "increased": r.get("increased_users"),
            "total": r.get("total_users"),
            "rate": r.get("rate"),
            # 필요하면 아래에 추가 필드 더 넣기
        })
    # 문자열 날짜 기준 정렬(YYYY-MM-DD 가정)
    pts.sort(key=lambda x: x["date"])
    return {"ok": True, "points": pts}


@app.get("/chart_grouped")
def chart_grouped(group: Optional[str] = Query(default=None, description="설명서")):
    rows = _load_rows()
    want = {g.strip() for g in group.split(",")} if group else None

    grid = defaultdict(dict)
    dates = set()

    for r in rows:
        d = r.get("progress_date")
        g = r.get("study_group_title") or "전체"
        if not d: 
            continue
        if want and g not in want:
            continue
        dates.add(d)
        grid[g][d] = {
            "rate": r.get("rate"),
            "increased": r.get("increased_users"),
            "total": r.get("total_users"),
        }

    labels = sorted(dates)
    series = []
    for g, by_date in sorted(grid.items()):
        series.append({
            "group": g,
            "rate": [by_date.get(d, {}).get("rate") for d in labels],
            "increased": [by_date.get(d, {}).get("increased") for d in labels],
            "total": [by_date.get(d, {}).get("total") for d in labels],
        })
    return {"ok": True, "labels": labels, "series": series}



# --- opentalk_code / nickname 옵션 목록 ---


@app.get("/progress/options")
def progress_options(opentalk: str | None = Query(default=None, description="선택한 단톡방명(opentalk_code)")):
    rows = _load_rows_from(PROGRESS_JSON_PATH)
    codes = set()
    names = set()
    for r in rows:
        code = (r.get("opentalk_code") or "").strip()
        nick = (r.get("nickname") or "").strip()
        if not code or not nick: continue
        codes.add(code)
        if (opentalk is None) or (code == opentalk):
            names.add(nick)
    return {"ok": True, "opentalk_codes": sorted(codes), "nicknames": sorted(names)}




# --- 선택값으로 시계열(진도율) 반환 ---
@app.get("/progress/series")
def progress_series(opentalk: str = Query(..., description="단톡방명(opentalk_code)"), nickname: str = Query(..., description="고객명(nickname)")):
    rows = _load_rows_from(PROGRESS_JSON_PATH)
    pts = []
    for r in rows:
        if (r.get("opentalk_code") or "").strip() != opentalk: continue
        if (r.get("nickname") or "").strip() != nickname: continue
        d = _to_date(r.get("progress_date"))
        if not d: continue
        pts.append((d.isoformat(), _to_num(r.get("progress"))))
    pts.sort(key=lambda x: x[0])
    labels = [d for d, _ in pts]
    data = [v for _, v in pts]
    return {"ok": True, "labels": labels, "data": data, "count": len(data)}




# --- 인증 테이블: 선택된 opentalk_code 기준으로 필터 ---
@app.get("/progress/cert_table")
def cert_table(opentalk: str = Query(..., description="단톡방명(opentalk_code)")):
    rows = _load_rows_from(CERT_JSON_PATH)
    out = []
    for r in rows:
        if (r.get("opentalk_code") or "").strip() != opentalk: continue
        out.append({
            "name": r.get("name"),
            "user_rank": r.get("user_rank"),
            # --- 주의: 컬럼명은 'cert_days_count' 입니다(샘플 기준). ---
            "cert_days_count": r.get("cert_days_count"),
            "average_week": r.get("average_week"),
        })
    # 보기 좋게 정렬: 랭크 오름차순, 이름
    out.sort(key=lambda x: (x["user_rank"] if x["user_rank"] is not None else 9999, x["name"] or ""))
    return {"ok": True, "rows": out, "count": len(out)}







# 단일 HTML: 여기서 직접 수정하면 됨(별도 파일 없음)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Progress Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:system-ui,Segoe UI,Arial;margin:24px;}
    .wrap{max-width:1000px;margin:auto;}
    .card{padding:16px;border:1px solid #e5e7eb;border-radius:12px;margin-bottom:16px}
    h1{margin:0 0 16px;}
    .muted{color:#6b7280;font-size:14px}
    /* dropdown */
    .dropdown{position:relative;display:inline-block}
    .dropdown-menu{position:absolute;background:#fff;border:1px solid #ccc;padding:8px;border-radius:8px;margin-top:4px;box-shadow:0 2px 8px rgba(0,0,0,.1);z-index:100}
    .hidden{display:none}
    #toggleBtn{padding:6px 10px;border:1px solid #d1d5db;border-radius:8px;background:#fff;cursor:pointer}
    #applyBtn{margin-top:8px;padding:6px 10px;border:1px solid #2563eb;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer}
    /* chart size fix: 부모 박스로 높이 고정, 캔버스는 100% 채움 */
    .chart-box{position:relative;height:320px}
    .chart-box canvas{position:absolute;inset:0;width:100% !important;height:100% !important}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Progress Dashboard</h1>
  <div class="muted">/chart_grouped API 데이터를 사용합니다. 25.09.09</div>

  <!-- ▼ 드롭다운 카드 -->
  <div class="card">
    <label class="muted">과정 선택</label>
    <div class="dropdown">
      <button id="toggleBtn">과정 선택 ▼</button>
      <div id="dropdownMenu" class="dropdown-menu hidden">
        <select id="groupSel" multiple size="6" style="min-width:260px;"></select>
        <button id="applyBtn">적용</button>
      </div>
    </div>
  </div>
  <!-- ▲ 드롭다운 카드 -->

  <div class="card">
    <h3>Rate by Date</h3>
    <div class="chart-box"><canvas id="rateChart"></canvas></div>
  </div>

  <div class="card">
    <h3>Increased Users by Date</h3>
    <div class="chart-box"><canvas id="incChart"></canvas></div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
let rateChart, incChart;
const rateEl=document.getElementById('rateChart');
const incEl=document.getElementById('incChart');
const toggleBtn=document.getElementById('toggleBtn');
const dropdownMenu=document.getElementById('dropdownMenu');
const applyBtn=document.getElementById('applyBtn');

toggleBtn.addEventListener('click',()=>{ dropdownMenu.classList.toggle('hidden'); });

async function fetchGrouped(groups){
  const url=new URL('/chart_grouped', location.origin);
  if(groups && groups.length) url.searchParams.set('group', groups.join(','));
  const r=await fetch(url);
  if(!r.ok) throw new Error('/chart_grouped HTTP '+r.status);
  const j=await r.json();
  if(!j || j.ok!==true) throw new Error('invalid payload');
  return j;
}
function fillSelect(series){
  const sel=document.getElementById('groupSel'); sel.innerHTML='';
  [...new Set(series.map(s=>s.group||'전체'))].forEach(name=>{
    const o=document.createElement('option'); o.value=name; o.textContent=name; sel.appendChild(o);
  });
}
function render(labels,series){
  if(rateChart) rateChart.destroy();
  if(incChart) incChart.destroy();
  const common={responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{y:{beginAtZero:true}}};
  rateChart=new Chart(rateEl,{type:'line',data:{labels,datasets:series.map(s=>({label:s.group||'전체',data:s.rate,tension:0.2,pointRadius:2}))},options:common});
  incChart=new Chart(incEl,{type:'bar',data:{labels,datasets:series.map(s=>({label:s.group||'전체',data:s.increased}))},options:common});
}

(async()=>{
  try{
    const j=await fetchGrouped();
    fillSelect(j.series);
    render(j.labels,j.series);

    applyBtn.addEventListener('click', async ()=>{
      const sel=Array.from(document.getElementById('groupSel').selectedOptions).map(o=>o.value);
      const j2=await fetchGrouped(sel);
      render(j2.labels,j2.series);
      dropdownMenu.classList.add('hidden'); // 적용 후 닫기
    });

    // 드롭다운 외 영역 클릭 시 닫힘
    document.addEventListener('click',(e)=>{
      if(!dropdownMenu.contains(e.target) && !toggleBtn.contains(e.target)){
        dropdownMenu.classList.add('hidden');
      }
    });
  }catch(e){
    console.error(e);
    document.body.insertAdjacentHTML('beforeend','<p class="muted">차트를 불러오지 못했습니다.</p>');
  }
})();
</script>
</body>
</html>


"""



@app.get("/dashboard_progress", response_class=HTMLResponse)
def dashboard_progress():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Study Progress & Cert</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:system-ui,Segoe UI,Arial;margin:24px;}
    .wrap{max-width:1100px;margin:auto;}
    .card{padding:16px;border:1px solid #e5e7eb;border-radius:12px;margin-bottom:16px}
    h1{margin:0 0 16px;}
    .muted{color:#6b7280;font-size:14px}
    .row{display:flex;gap:12px;flex-wrap:wrap}
    .dropdown{position:relative;display:inline-block}
    .dropdown-menu{position:absolute;background:#fff;border:1px solid #ccc;padding:8px;border-radius:8px;margin-top:4px;box-shadow:0 2px 8px rgba(0,0,0,.1);z-index:100}
    .hidden{display:none}
    .btn{padding:6px 10px;border:1px solid #d1d5db;border-radius:8px;background:#fff;cursor:pointer}
    .btn.primary{border-color:#2563eb;background:#2563eb;color:#fff}
    select{min-width:260px;}
    .chart-box{position:relative;height:300px}
    .chart-box canvas{position:absolute;inset:0;width:100% !important;height:100% !important}
    table{border-collapse:collapse;width:100%;table-layout:fixed;} /* 균등 폭 */
    th,td{border:1px solid #e5e7eb;padding:8px;text-align:center;font-size:14px}
    th{background:#f9fafb}
    /* 순위 강조 색상 */
    .rank-1{color:#d4af37;font-weight:700;} /* gold */
    .rank-2{color:#a7a7a7;font-weight:700;} /* silver */
    .rank-3{color:#cd7f32;font-weight:700;} /* bronze */
  </style>
</head>
<body>
<div class="wrap">
  <h1>Study Progress & Certification</h1>
  <div class="muted">study_progress.json + study_cert.json 기반</div>

  <!-- ▼ 필터 영역 -->
  <div class="card">
    <div class="row">
      <!-- 단톡방 이름 드롭다운 -->
      <div class="dropdown">
        <button id="roomBtn" class="btn">단톡방 이름 선택 ▼</button>
        <div id="roomMenu" class="dropdown-menu hidden">
          <select id="roomSel" size="6"></select>
          <button id="roomApply" class="btn primary" style="margin-top:8px">적용</button>
        </div>
      </div>
      <!-- 닉네임 드롭다운 -->
      <div class="dropdown">
        <button id="nickBtn" class="btn">닉네임 선택 ▼</button>
        <div id="nickMenu" class="dropdown-menu hidden">
          <select id="nickSel" size="6"></select>
          <button id="nickApply" class="btn primary" style="margin-top:8px">적용</button>
        </div>
      </div>
      <div class="muted" id="picked" style="align-self:center"></div>
    </div>
  </div>

  <!-- ▼ 차트 -->
  <div class="card">
    <h3>진도율(%)</h3>
    <div class="chart-box"><canvas id="progressChart"></canvas></div>
  </div>

  <!-- ▼ 인증 표 -->
  <div class="card">
    <h3>인증 현황 (상위 20명)</h3>
    <div class="muted" id="certCount"></div>
    <table>
      <thead>
        <tr><th>순위</th><th>이름</th><th>인증일수</th><th>주간 평균</th></tr>
      </thead>
      <tbody id="certTbody"></tbody>
    </table>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
const $=sel=>document.querySelector(sel);

// ★ 방코드 → 표시명 규칙(필요시 아래 매핑 수정)
function roomLabelFromCode(code){
  if(!code) return "";
  const m = String(code).match(/^(\d{2})(\d{2})(.+)$/); // YY MM KEY
  if(!m) return code;
  const yy=m[1], mm=m[2], key=m[3];
  const courseMap = {"영어":"영어회화 100","기초":"기초 영어회화 100","구동":"구동사 100"}; // ★ 수정지점
  const course = courseMap[key] || key;
  return `${yy}년 ${mm}월 ${course}`;
}

const roomBtn=$("#roomBtn"), roomMenu=$("#roomMenu"), roomSel=$("#roomSel"), roomApply=$("#roomApply");
const nickBtn=$("#nickBtn"), nickMenu=$("#nickMenu"), nickSel=$("#nickSel"), nickApply=$("#nickApply");
const picked=$("#picked");

let chart;
const ctx=document.getElementById('progressChart');
function ensureChart(labels,data){
  if(chart) chart.destroy();
  const options={responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{y:{beginAtZero:true,min:0,max:100}}}; // 0~100 고정
  chart=new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'진도율',data,pointRadius:2,tension:0.2}]},options});
}

// 메뉴 토글
roomBtn.addEventListener('click',()=>roomMenu.classList.toggle('hidden'));
nickBtn.addEventListener('click',()=>nickMenu.classList.toggle('hidden'));
document.addEventListener('click',e=>{
  if(!roomMenu.contains(e.target)&&!roomBtn.contains(e.target)) roomMenu.classList.add('hidden');
  if(!nickMenu.contains(e.target)&&!nickBtn.contains(e.target)) nickMenu.classList.add('hidden');
});

async function getJSON(url){const r=await fetch(url);if(!r.ok)throw new Error(url+': '+r.status);return await r.json();}

// ▼ 옵션 채우기
async function fillRooms(){
  const j=await getJSON('/progress/options');
  roomSel.innerHTML='';
  // 기본 옵션: 단톡방 조회
  const def=document.createElement('option'); def.value=""; def.textContent="단톡방 조회"; roomSel.appendChild(def);
  j.opentalk_codes.forEach(code=>{
    const o=document.createElement('option');
    o.value=code; o.textContent=roomLabelFromCode(code);
    roomSel.appendChild(o);
  });
  // 닉네임 초기 상태: 아무 값도 없음 + 기본 옵션만
  nickSel.innerHTML='';
  const nickDef=document.createElement('option'); nickDef.value=""; nickDef.textContent="닉네임 선택"; nickSel.appendChild(nickDef);
}

async function fillNicknames(opentalk){
  // 방이 선택되지 않았다면 비워둠
  if(!opentalk){ nickSel.innerHTML=''; const nickDef=document.createElement('option'); nickDef.value=""; nickDef.textContent="닉네임 선택"; nickSel.appendChild(nickDef); return; }
  const j=await getJSON('/progress/options?opentalk='+encodeURIComponent(opentalk));
  nickSel.innerHTML='';
  const nickDef=document.createElement('option'); nickDef.value=""; nickDef.textContent="닉네임 선택"; nickSel.appendChild(nickDef);
  j.nicknames.forEach(n=>{
    const o=document.createElement('option'); o.value=n; o.textContent=n; nickSel.appendChild(o);
  });
}

roomApply.addEventListener('click', async ()=>{
  const code=roomSel.value;
  roomBtn.textContent='단톡방: '+(code?roomLabelFromCode(code):'단톡방 조회')+' ▼';
  roomMenu.classList.add('hidden');
  await fillNicknames(code);     // 방 바뀌면 닉네임 목록 갱신
  await refreshAll();            // 인증표 갱신(차트는 닉네임 선택 후)
});
nickApply.addEventListener('click', async ()=>{
  const name=nickSel.value;
  nickBtn.textContent='닉네임: '+(name||'닉네임 선택')+' ▼';
  nickMenu.classList.add('hidden');
  await refreshAll();
});

// 렌더링
async function refreshAll(){
  const code=roomSel.value, name=nickSel.value;
  picked.textContent=(code?`[${roomLabelFromCode(code)}]`:'')+(name?` ${name}`:'');
  // 차트: 방+닉네임 모두 있어야 조회
  if(code && name){
    const s=await getJSON(`/progress/series?opentalk=${encodeURIComponent(code)}&nickname=${encodeURIComponent(name)}`);
    ensureChart(s.labels,s.data);
  }else{
    // 선택 전엔 빈 차트로 유지
    ensureChart([],[]);
  }
  // 인증표: 방만 있으면 조회(상위 20명)
  const tb=$("#certTbody"); tb.innerHTML='';
  $("#certCount").textContent='';
  if(code){
    const t=await getJSON(`/progress/cert_table?opentalk=${encodeURIComponent(code)}`);
    const top=t.rows.slice(0,20); // 상위 20
    top.forEach(r=>{
      const rank=(r.user_rank??''); const name=r.name??''; const days=r.cert_days_count??''; 
      const avgRaw=r.average_week; const avg=(avgRaw!=null && avgRaw!=='')? (Number(avgRaw).toFixed(1)) : ''; // 소수 1자리
      const tr=document.createElement('tr');
      // 순위 강조 클래스
      const cls = rank==1?'rank-1':(rank==2?'rank-2':(rank==3?'rank-3':''));
      tr.innerHTML=`
        <td class="${cls}">${rank}</td>
        <td>${name}</td>
        <td>${days}</td>
        <td>${avg}</td>`;
      tb.appendChild(tr);
    });
    $("#certCount").textContent=`총 ${top.length}명 (상위 20명 표시)`;
  }
}

// 시작 시
(async()=>{
  try{
    await fillRooms();
    ensureChart([],[]); // 초기 빈 차트
  }catch(e){
    console.error(e);
    document.body.insertAdjacentHTML('beforeend','<p class="muted">데이터를 불러오지 못했습니다.</p>');
  }
})();
</script>
</body>
</html>
"""






# 로컬에서 python main.py 실행 시: push 여부를 물어봄
if __name__ == "__main__":
    print("=== 로컬 실행 옵션 선택 ===")
    do_serve = input("로컬 서버 실행할까요? (y/N): ").strip().lower() in ("y", "yes")
    do_push = input("GitHub push 실행할까요? (y/N): ").strip().lower() in ("y", "yes")

    if do_push:
        try:
            _push_once()
        except Exception as e:
            print(f"[push error] {e}")

    if do_serve:
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

    if not (do_push or do_serve):
        print("[main] 아무 작업도 선택하지 않았습니다. 종료합니다.")

