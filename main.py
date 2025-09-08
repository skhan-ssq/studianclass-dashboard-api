# main.py
# - /health, /test 제공
# - 서버 시작 시 1회: main.py 커밋/푸시(빈 커밋 허용)
# - 콘솔에 단계별 진행 로그 출력
# - 파일을 직접 실행하면 uvicorn을 자동으로 띄워서 로컬에서도 바로 확인 가능
#   (Render에선 Start Command로 uvicorn을 쓰면 lifespan에서 push만 실행되고 서버는 Render가 띄웁니다)

from fastapi import FastAPI, HTTPException, Query
from contextlib import asynccontextmanager
import json, os, subprocess

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
RENDER_DEPLOY_HOOK = os.getenv("RENDER_DEPLOY_HOOK", "").strip()  # 선택

# -------- 공용 유틸(로그 + 쉘 실행) --------
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

# -------- Git: 시작 시 1회 푸시 --------
def _push_once():
    log("[push] start")
    _sh("git rev-parse --is-inside-work-tree")  # 깃 저장소 확인
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    current = (cur.stdout or "").strip()
    if current != GIT_BRANCH:
        log(f"[push] checkout -> {GIT_BRANCH}")
        _sh(f"git checkout -B {GIT_BRANCH}")

    _sh("git config core.autocrlf false", check=False)

    # 변경 유무와 관계없이 한 번 커밋
    _sh("git add main.py", check=False)
    _sh('git commit -m "chore: sync main.py on server start" --allow-empty', check=False)

    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first = (up.returncode != 0)

    try:
        _sh(f"git push {'-u ' if first else ''}origin {GIT_BRANCH}")
    except RuntimeError as e:
        log("[push] non-fast-forward. try rebase")
        _sh("git stash push -u -k -m autosync-main", check=False)
        _sh(f"git pull --rebase origin {GIT_BRANCH}", check=False)
        _sh(f"git push origin {GIT_BRANCH}", check=True)
        _sh("git stash pop", check=False)

    # 원하면 Render Deploy Hook 호출(선택)
    if RENDER_DEPLOY_HOOK:
        try:
            _sh(f'python -c "import urllib.request;urllib.request.urlopen(\'{RENDER_DEPLOY_HOOK}\').read()"', check=False)
            log("[push] render deploy hook triggered")
        except Exception as e:
            log(f"[push] deploy hook warn: {e}")

    log("[push] done")

# -------- 데이터 로드 --------
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

# -------- lifespan: 서버 기동 시 1회 push --------
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

# -------- 로컬 실행(IDLE/더블클릭) 시 uvicorn 자동 실행 --------
if __name__ == "__main__":
    log("[main] launching uvicorn (dev)")
    try:
        import uvicorn
    except ImportError:
        log("[main] uvicorn not installed. install with: pip install uvicorn fastapi")
        raise
    # 로컬에서 바로 서버 뜨게 함. 콘솔에 로그가 보임.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
