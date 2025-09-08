# db.py
# 역할:
# 1. MySQL에서 데이터를 SELECT 해서 JSON 스냅샷(progress.json)으로 저장
# 2. 실행 시 스냅샷 파일과 db.py 자신을 git add/commit/push

import os, json, subprocess, datetime
from pathlib import Path
from dotenv import load_dotenv
from mysql.connector import pooling, Error

# 환경변수(.env) 로드
load_dotenv()

# DB 접속 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": True,
}

# Git 관련 기본값
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
SNAPSHOT_PATH = "data/progress.json"

# DB 연결 풀
POOL = pooling.MySQLConnectionPool(pool_name="main_pool", pool_size=5, **DB_CONFIG)

def fetch_all(query: str, params: dict | None = None):
    """쿼리를 실행해 결과를 딕셔너리 리스트로 반환"""
    conn = cur = None
    try:
        conn = POOL.get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params or {})
        return cur.fetchall()
    except Error:
        raise
    finally:
        try:
            if cur: cur.close()
            if conn: conn.close()
        except:
            pass

def _now_iso():
    """현재 시각 ISO8601 문자열 반환"""
    return datetime.datetime.now().astimezone().isoformat()

def export_to_json(query: str, out_path: str = SNAPSHOT_PATH, params: dict | None = None):
    """쿼리 실행 결과를 JSON 파일(progress.json)로 저장"""
    rows = fetch_all(query, params)
    snapshot = {
        "generated_at": _now_iso(),    # 생성 시각
        "row_count": len(rows),        # 행 개수
        "source": {"type": "sql", "query": query.strip()},
        "rows": rows,                  # 실제 데이터
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(p) + ".tmp"
    # 임시 파일에 저장
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, default=str)
    # JSON 검증
    with open(tmp_path, encoding="utf-8") as f:
        json.load(f)
    # 원자적 교체
    os.replace(tmp_path, out_path)
    print(f"[OK] {len(rows)} rows → {out_path}")

def _run(cmd: str, check: bool = True, echo: bool = True):
    """셸 명령 실행"""
    if echo: print(f"$ {cmd}")
    cp = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and cp.returncode != 0:
        raise RuntimeError(f"[CMD FAIL] {cmd}\n{(cp.stdout or '')}{(cp.stderr or '')}".strip())
    if cp.stdout: print(cp.stdout.strip())
    return cp

def _ensure_branch(branch: str):
    """현재 브랜치가 지정 브랜치인지 확인, 아니면 체크아웃"""
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    if (cur.stdout or "").strip() != branch:
        _run(f"git checkout -B {branch}")

def _ensure_gitattributes_for_snapshot(path: str):
    """progress.json 파일은 항상 ours 머지 전략으로 설정"""
    line = f"{path} merge=ours\n"
    ga = Path(".gitattributes")
    existing = ga.read_text(encoding="utf-8") if ga.exists() else ""
    if line not in existing:
        ga.write_text(existing + line, encoding="utf-8")
        _run("git add .gitattributes", check=False)
        _run('git commit -m "chore: set merge=ours for snapshot file" --allow-empty', check=False)
        _run('git config merge.ours.driver true', check=False)

def _auto_resolve_snapshot_ours(path: str):
    """충돌 발생 시 progress.json 파일은 ours 버전으로 자동 해결"""
    _run(f"git checkout --ours {path}", check=False)
    _run(f"git add {path}", check=False)

def push_files(paths: list[str], branch: str | None = None, allow_empty: bool = True):
    """지정된 파일 목록을 git add/commit/push"""
    branch = branch or GIT_BRANCH
    _run("git rev-parse --is-inside-work-tree")
    _ensure_branch(branch)
    _ensure_gitattributes_for_snapshot(SNAPSHOT_PATH)
    _run("git config core.autocrlf false", check=False)

    for p in paths:
        if p == SNAPSHOT_PATH:
            _run(f"git add -f {p}", check=False)
        _run(f"git add {p}", check=False)

    msg = f'chore: update snapshot {_now_iso()}'
    _run(f'git commit -m "{msg}"', check=False)

    # upstream 여부 확인
    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first_push = (up.returncode != 0)

    def do_push(use_u: bool):
        _run(f"git push {'-u ' if use_u else ''}origin {branch}")

    try:
        do_push(first_push)
    except RuntimeError:
        # 원격이 더 앞서 있으면 rebase 후 ours 적용
        _run("git stash push -u -k -m autosync", check=False)
        try:
            _run(f"git pull --rebase origin {branch}")
        except RuntimeError:
            _auto_resolve_snapshot_ours(SNAPSHOT_PATH)
            _run("git rebase --continue", check=False)
        do_push(False)
        _run("git stash pop", check=False)

    # push 결과 확인
    local = subprocess.run("git rev-parse HEAD", shell=True, text=True, capture_output=True).stdout.strip()
    remote = subprocess.run(f"git ls-remote origin {branch}", shell=True, text=True, capture_output=True).stdout.split("\t")[0].strip()
    print(f"[OK] git push 완료. local={local[:7]} remote={remote[:7]}")

if __name__ == "__main__":
    # DB에서 데이터 읽어 스냅샷 저장
    export_to_json("""
        SELECT *
        FROM metabase_chart_daily_progress
        limit 600
    """)
    # progress.json + db.py 푸시
    push_files(paths=[SNAPSHOT_PATH, "db.py"], branch=GIT_BRANCH, allow_empty=True)


# 25.09.08
