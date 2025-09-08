# db.py
import os, json, subprocess, datetime
from pathlib import Path
from dotenv import load_dotenv
from mysql.connector import pooling, Error

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": True,
}

GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
SNAPSHOT_PATH = "data/progress.json"

POOL = pooling.MySQLConnectionPool(pool_name="main_pool", pool_size=5, **DB_CONFIG)

def fetch_all(query: str, params: dict | None = None):
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
    return datetime.datetime.now().astimezone().isoformat()

def export_to_json(query: str, out_path: str = SNAPSHOT_PATH, params: dict | None = None):
    rows = fetch_all(query, params)
    snapshot = {
        "generated_at": _now_iso(),
        "row_count": len(rows),
        "source": {"type": "sql", "query": query.strip()},
        "rows": rows,
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(p) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, default=str)
    with open(tmp_path, encoding="utf-8") as f:
        json.load(f)
    os.replace(tmp_path, out_path)
    print(f"[OK] {len(rows)} rows → {out_path}")

def _run(cmd: str, check: bool = True, echo: bool = True):
    if echo: print(f"$ {cmd}")
    cp = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and cp.returncode != 0:
        raise RuntimeError(f"[CMD FAIL] {cmd}\n{(cp.stdout or '')}{(cp.stderr or '')}".strip())
    if cp.stdout: print(cp.stdout.strip())
    return cp

def _git_state():
    gd = subprocess.run("git rev-parse --git-dir", shell=True, text=True, capture_output=True)
    git_dir = gd.stdout.strip() if gd.returncode == 0 else ".git"
    def ex(p): return Path(git_dir, p).exists()
    merging = Path(".git/MERGE_HEAD").exists()
    rebasing = ex("rebase-apply") or ex("rebase-merge")
    return {"merging": merging, "rebasing": rebasing}

def _ensure_branch(branch: str):
    st = _git_state()
    if st["merging"] or st["rebasing"]:
        return
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    if (cur.stdout or "").strip() != branch:
        _run(f"git checkout -B {branch}")

def _ensure_gitattributes_for_snapshot(path: str):
    line = f"{path} merge=ours\n"
    ga = Path(".gitattributes")
    existing = ga.read_text(encoding="utf-8") if ga.exists() else ""
    if line not in existing:
        ga.write_text(existing + line, encoding="utf-8")
        _run("git add .gitattributes", check=False)
        _run('git commit -m "chore: set merge=ours for snapshot file" --allow-empty', check=False)
        _run('git config merge.ours.driver true', check=False)

def _auto_resolve_snapshot_ours(path: str):
    _run(f"git checkout --ours {path}", check=False)
    _run(f"git add {path}", check=False)

def push_always(paths: list[str], branch: str | None = None):
    branch = branch or GIT_BRANCH
    _run("git rev-parse --is-inside-work-tree")
    _ensure_branch(branch)
    _ensure_gitattributes_for_snapshot(SNAPSHOT_PATH)
    _run("git config core.autocrlf false", check=False)

    for p in paths:
        if p == SNAPSHOT_PATH:
            _run(f"git add -f {p}", check=False)
        _run(f"git add {p}", check=False)

    _run(f'git commit -m "chore: update snapshot & sync code {_now_iso()}" --allow-empty')

    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first_push = (up.returncode != 0)

    def do_push(use_u: bool):
        _run(f"git push {'-u ' if use_u else ''}origin {branch}")

    try:
        do_push(first_push)
    except RuntimeError as e:
        print("[WARN] push 실패. rebase→ours(snapshot)→재푸시:", e)
        _run("git stash push -u -k -m autostash-for-rebase", check=False)
        try:
            _run(f"git pull --rebase origin {branch}")
        except RuntimeError:
            _auto_resolve_snapshot_ours(SNAPSHOT_PATH)
            _run("git rebase --continue", check=False)
        do_push(False)
        st = subprocess.run("git stash list", shell=True, text=True, capture_output=True)
        if "autostash-for-rebase" in st.stdout:
            _run("git stash pop", check=False)

    local = subprocess.run("git rev-parse HEAD", shell=True, text=True, capture_output=True).stdout.strip()
    remote = subprocess.run(f"git ls-remote origin {branch}", shell=True, text=True, capture_output=True).stdout.split("\t")[0].strip()
    print(f"[OK] git push 완료. local={local[:7]} remote={remote[:7]}")

if __name__ == "__main__":
    export_to_json("""
        SELECT *
        FROM metabase_chart_daily_progress
        LIMIT 50
    """)
    push_always(paths=[SNAPSHOT_PATH, "main.py"], branch=GIT_BRANCH)


## 2025 09 08
