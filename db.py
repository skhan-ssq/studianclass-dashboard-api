# db.py
import os
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

# 🔁 커넥션 풀(권장): 매 요청마다 새 연결 생성 비용↓
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
        # 개발 단계 디버그 용(배포 전에는 로그로 전환)
        raise
    finally:
        try:
            if cur: cur.close()
            if conn: conn.close()
        except:  # 연결 회수 보장
            pass
