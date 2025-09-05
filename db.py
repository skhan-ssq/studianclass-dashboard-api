# db.py
import os, json, subprocess, datetime
from pathlib import Path
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import pooling, Error

# 🔄 .env 로드(로컬에서 DB 접속)
load_dotenv()

# 🔒 DB 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": True,
}

# 🔁 커넥션 풀(로컬에서만 사용)
POOL = pooling.MySQLConnectionPool(pool_name="main_pool", pool_size=5, **DB_CONFIG)

def fetch_all(query: str, params: dict | None = None):
    """SELECT → dict 리스트 반환"""
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

def export_to_json(query: str, out_path: str = "data/progress.json", params: dict | None = None):
    """쿼리 결과를 JSON 스냅샷으로 저장"""
    rows = fetch_all(query, params)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        # ✅ date/datetime 등 자동 문자열화
        json.dump(rows, f, ensure_ascii=False, default=str)
    print(f"[OK] {len(rows)} rows → {out_path}")

def _run(cmd: str):
    subprocess.check_call(cmd, shell=True)

def push_if_changed(path: str = "data/progress.json", branch: str = "main"):
    """파일 변경 있으면 git add/commit/push"""
    r = subprocess.run(f'git status --porcelain {path}', shell=True, capture_output=True, text=True)
    if not r.stdout.strip():
        print("[SKIP] 변경 없음. 푸시 생략."); return
    _run(f'git add {path}')
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _run(f'git commit -m "chore: update progress snapshot {ts}"')
    _run(f'git push origin {branch}')
    print("[OK] git push 완료")

if __name__ == "__main__":
    # 안전가드: 명시적으로 허용할 때만 push
    allow_push = os.getenv("ALLOW_GIT_PUSH", "false").lower() in ("1","true","yes")

    # ✅ 원하는 쿼리로 스냅샷 생성(예시)
    export_to_json("""
        SELECT *
        FROM metabase_chart_daily_progress
        LIMIT 50
    """)

    # 변경 있으면 커밋/푸시(옵션)
    if allow_push:
        push_if_changed("data/progress.json", branch="main")
    else:
        print("[INFO] ALLOW_GIT_PUSH=false → push 생략(스냅샷만 생성)")
