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
    _sh("git rev-parse --is-inside-work-tree")
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    if (cur.stdout or "").strip() != GIT_BRANCH:
        _sh(f"git checkout -B {GIT_BRANCH}")
    _sh("git config core.autocrlf false", check=False)
    _sh("git add main.py", check=False)
    _sh('git commit -m "chore: sync main.py on run" --allow-empty', check=False)
    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first = (up.returncode != 0)
    _sh(f"git push {'-u ' if first else ''}origin {GIT_BRANCH}", check=False)
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
            "rate": r.get("rate"),
            "increased": r.get("increased_users"),
            "total": r.get("total_users"),
            # 필요하면 아래에 추가 필드 더 넣기
        })
    # 문자열 날짜 기준 정렬(YYYY-MM-DD 가정)
    pts.sort(key=lambda x: x["date"])
    return {"ok": True, "points": pts}

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
    canvas{width:100%;max-height:360px}
    h1{margin:0 0 16px;}
    .muted{color:#6b7280;font-size:14px}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Progress Dashboard</h1>
  <div class="muted">/chart API 데이터를 사용합니다.</div>

  <div class="card">
    <h3>Rate by Date</h3>
    <canvas id="rateChart"></canvas>
  </div>

  <div class="card">
    <h3>Increased Users by Date</h3>
    <canvas id="incChart"></canvas>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
(async () => {
  const res = await fetch('/chart');
  const js = await res.json();
  if (!js.ok) { throw new Error('chart api failed'); }
  const pts = js.points || [];

  // -------- 조정 포인트(필드 매핑) --------
  // 필요 필드명 바꾸려면 여기 수정: p.date / p.rate / p.increased / p.total
  const labels = pts.map(p => p.date);
  const rate   = pts.map(p => p.rate ?? null);
  const inc    = pts.map(p => p.increased ?? null);

  // 라인 차트(진도율)
  new Chart(document.getElementById('rateChart'), {
    type: 'line',
    data: { labels, datasets: [{ label: 'Rate', data: rate, tension: 0.2 }] },
    options: { responsive: true, interaction:{mode:'index',intersect:false}, scales:{ y:{ beginAtZero:true } } }
  });

  // 막대 차트(증가 사용자)
  new Chart(document.getElementById('incChart'), {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Increased Users', data: inc }] },
    options: { responsive: true, interaction:{mode:'index',intersect:false}, scales:{ y:{ beginAtZero:true } } }
  });
})();
</script>
</body>
</html>
"""

# 로컬에서 python main.py 실행 시: push만 수행(서버는 안 띄움)
if __name__ == "__main__":
    _push_once()
