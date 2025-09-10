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
    .row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
    .field{display:flex;flex-direction:column;gap:6px}
    .input{padding:6px 10px;border:1px solid #d1d5db;border-radius:8px;min-width:260px}
    .btn{padding:6px 10px;border:1px solid #d1d5db;border-radius:8px;background:#fff;cursor:pointer}
    .btn.primary{border-color:#2563eb;background:#2563eb;color:#fff}
    .chart-box{position:relative;height:300px}
    .chart-box canvas{position:absolute;inset:0;width:100% !important;height:100% !important}
    table{border-collapse:collapse;width:100%;table-layout:fixed;}
    th,td{border:1px solid #e5e7eb;padding:8px;text-align:center;font-size:14px}
    th{background:#f9fafb}
    /* 순위 배경+글씨색 */
    .rank-1{background:#fff7d6;color:#7a5c00;font-weight:700;}
    .rank-2{background:#f0f0f0;color:#555555;font-weight:700;}
    .rank-3{background:#ffe6d9;color:#7a3d00;font-weight:700;}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Study Progress & Certification</h1>
  <div class="muted">study_progress.json + study_cert.json 기반</div>

  <!-- ▼ 필터 -->
  <div class="card">
    <div class="row">
      <div class="field">
        <label class="muted">단톡방 이름</label>
        <input id="roomInput" class="input" list="roomList" placeholder="단톡방 조회(예: 25년 07월 영어회화 100)">
        <datalist id="roomList"></datalist>
      </div>
      <div class="field">
        <label class="muted">닉네임</label>
        <input id="nickInput" class="input" list="nickList" placeholder="닉네임 선택">
        <datalist id="nickList"></datalist>
      </div>
      <div class="field">
        <button id="applyBtn" class="btn primary">적용</button>
      </div>
      <div class="muted" id="picked" style="margin-left:auto"></div>
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

// ★ 방코드→표시명
function roomLabelFromCode(code){
  if(!code) return "";
  const m = String(code).match(/^(\d{2})(\d{2})(.+)$/); // YY MM KEY
  if(!m) return code;
  const yy=m[1], mm=m[2], key=m[3];
  const courseMap = {"영어":"영어회화 100","기초":"기초 영어회화 100","구동":"구동사 100"}; // ★ 수정지점
  const course = courseMap[key] || key;
  return `${yy}년 ${mm}월 ${course}`;
}
// ★ 표시명→방코드(입력값이 라벨일 때 코드 복원)
function roomCodeFromLabel(label){
  if(!label) return "";
  const m = String(label).match(/^(\d{2})년 (\d{2})월 (.+)$/);
  if(!m) return label; // 이미 코드일 수도 있음
  const yy=m[1], mm=m[2], course=m[3];
  const rev = {"영어회화 100":"영어","기초 영어회화 100":"기초","구동사 100":"구동"};
  const key = rev[course] || course;
  return yy+mm+key;
}

// 상태 & 차트
let currentRooms = [];
let chart;
const ctx=document.getElementById('progressChart');
function ensureChart(labels,data){
  if(chart) chart.destroy();
  const options={responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{y:{beginAtZero:true,min:0,max:100}}};
  chart=new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'진도율',data,pointRadius:2,tension:0.2}]},options});
}

// 요소 캐시
const roomInput=$("#roomInput");   // ★ 단톡방 입력
const nickInput=$("#nickInput");   // ★ 닉네임 입력

// API
async function getJSON(url){const r=await fetch(url);if(!r.ok)throw new Error(url+': '+r.status);return await r.json();}

// 옵션 채우기
async function fillRooms(){
  const j=await getJSON('/progress/options');
  currentRooms = j.opentalk_codes || [];
  const dl=$("#roomList"); dl.innerHTML='';
  currentRooms.forEach(code=>{
    const opt=document.createElement('option');
    opt.value = code;                    // 선택 시 코드가 입력됨
    opt.label = roomLabelFromCode(code); // 브라우저 자동완성 라벨
    dl.appendChild(opt);
  });
  // 닉네임 datalist 초기화
  $("#nickList").innerHTML='';
}

// ★ 단톡방 입력 변경 시 → 해당 방의 닉네임 목록 자동 갱신
roomInput.addEventListener('change', async ()=>{
  let val = roomInput.value.trim();
  // 입력이 라벨이면 코드로 환원
  if(val && !currentRooms.includes(val)){ val = roomCodeFromLabel(val); }
  // 닉네임 입력값 초기화
  nickInput.value = "";
  // 닉네임 목록 갱신(방 없으면 비움)
  await fillNicknames(val);
});

async function fillNicknames(opentalkCode){
  const ndl=$("#nickList"); ndl.innerHTML='';
  if(!opentalkCode) return;
  const j=await getJSON('/progress/options?opentalk='+encodeURIComponent(opentalkCode));
  (j.nicknames||[]).forEach(n=>{
    const opt=document.createElement('option'); opt.value=n; ndl.appendChild(opt);
  });
}

// 적용
$("#applyBtn").addEventListener('click', async ()=>{
  // 방 코드 해석
  let code = roomInput.value.trim();
  if(code && !currentRooms.includes(code)){ code = roomCodeFromLabel(code); }
  const name = nickInput.value.trim();

  // 선택 표시
  $("#picked").textContent = (code?`[${roomLabelFromCode(code)}]`:'') + (name?` ${name}`:'');

  // 차트
  if(code && name){
    const s=await getJSON(`/progress/series?opentalk=${encodeURIComponent(code)}&nickname=${encodeURIComponent(name)}`);
    ensureChart(s.labels, s.data);
  }else{
    ensureChart([],[]);
  }

  // 인증표(상위 20명)
  const tb=$("#certTbody"); tb.innerHTML='';
  $("#certCount").textContent='';
  if(code){
    const t=await getJSON(`/progress/cert_table?opentalk=${encodeURIComponent(code)}`);
    const top=t.rows.slice(0,20);
    top.forEach(r=>{
      const rank=(r.user_rank??'');
      const cls = rank==1?'rank-1':(rank==2?'rank-2':(rank==3?'rank-3':''));
      const avgRaw=r.average_week;
      const avg=(avgRaw!=null && avgRaw!=='')? (Number(avgRaw).toFixed(1)) : '';
      const tr=document.createElement('tr');
      tr.innerHTML=`<td class="${cls}">${rank}</td><td>${r.name??''}</td><td>${r.cert_days_count??''}</td><td>${avg}</td>`;
      tb.appendChild(tr);
    });
    $("#certCount").textContent=`총 ${Math.min(20, t.rows.length)}명 (상위 20명 표시)`;
  }
});

// 초기
(async()=>{
  try{
    await fillRooms();
    ensureChart([],[]);
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

