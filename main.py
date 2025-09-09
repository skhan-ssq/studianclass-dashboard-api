# 25.09.09
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


BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")

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

# -------------------- FastAPI --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Render에서 uvicorn으로 실행될 때 서버 기동 시 1회 push
    try: _push_once()
    except Exception as e: _log(f"[push warn] {e}")
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


# 로컬에서 python main.py 실행 시: push 여부를 물어봄
if __name__ == "__main__":
    try:
        ans = input("👉 Git push 실행할까요? (y/n): ").strip().lower()
    except EOFError:
        ans = "n"
    if ans in ("y", "yes"):
        _push_once()
    else:
        print("[push] skipped")
