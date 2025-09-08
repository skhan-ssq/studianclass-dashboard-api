# main.py
# 역할:
# - /health, /test API 제공
# - 서버 시작(lifespan) 시 1회 main.py push 수행
# - 로컬에서 python main.py 실행하면 push만 실행하고 서버는 실행하지 않음

from fastapi import FastAPI, HTTPException, Query
from contextlib import asynccontextmanager
import json, os, subprocess

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")

# -------- Git 푸시 --------
def log(msg: str):
    print(msg, flush=True)

def _sh(cmd: str, check: bool = True):
    log(f"$ {cmd}")
    cp = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if cp.stdout:
        log(cp.stdout.strip())
    if cp.stderr and not check:
        log(cp.stderr.strip())
    if check and cp.returncode != 0:
        raise RuntimeError((cp.stdout or "") + (cp.stderr or ""))
    return cp

def _push_once():
    log("[push] start")
    _sh("git rev-parse --is-inside-work-tree")
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    if (cur.stdout or "").strip() != GIT_BRANCH:
        log(f"[push] checkout -> {GIT_BRANCH}")
        _sh(f"git checkout -B {GIT_BRANCH}")

    _sh("git config core.autocrlf false", check=False)
    _sh("git add main.py", check=False)
    _sh('git commit -m "chore: sync main.py on run" --allow-empty', check=False)

    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first = (up.returncode != 0)
    _sh(f"git push {'-u ' if first else ''}origin {GIT_BRANCH}", check=False)

    log("[push] done")

# -------- 데이터 --------
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

# -------- lifespan: Render 실행 시 push --------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _push_once()
    except Exception as e:
        log(f"[push warn] {str(e).strip()}")
    yield

app = FastAPI(lifespan=lifespan)

# -------- Endpoints --------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/test")
def test(limit: int = Query(10, ge=1, le=1000), offset: int = Query(0, ge=0)):
    rows = _load_rows()
    sliced = rows[offset:offset+limit]
    return {"ok": True, "total": len(rows), "limit": limit, "offset": offset, "count": len(sliced), "rows": sliced}

# -------- 로컬에서 python main.py 실행 시 push만 --------
if __name__ == "__main__":
    _push_once()
