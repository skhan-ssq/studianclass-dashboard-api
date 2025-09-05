# db.py
import os, json
from pathlib import Path
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import pooling, Error

# 🔄 .env 로드
load_dotenv()

# 🔒 DB 설정 (환경변수 그대로 사용)
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": True,
}

# 🔁 커넥션 풀
POOL = pooling.MySQLConnectionPool(pool_name="main_pool", pool_size=5, **DB_CONFIG)

def fetch_all(query: str, params: dict | None = None):
    """SELECT 전용 헬퍼: 결과를 dict 리스트로 반환"""
    conn = None
    cur = None
    try:
        conn = POOL.get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params or {})
        rows = cur.fetchall()
        return rows
    except Error as e:
        raise
    finally:
        try:
            if cur: cur.close()
            if conn: conn.close()
        except:
            pass

def export_to_json(query: str, out_path: str = "data/progress.json", params: dict | None = None):
    rows = fetch_all(query, params)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"[OK] {len(rows)} rows → {out_path}")

if __name__ == "__main__":
    # 실제 원하는 쿼리 실행 (예시: 최근 50개 데이터)
    export_to_json(
        """
        SELECT *
        FROM metabase_chart_daily_progress
        LIMIT 50
        """
    )
