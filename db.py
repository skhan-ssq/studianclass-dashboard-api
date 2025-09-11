
# 2025.09.10
# -*- coding: utf-8 -*-
"""
db.py

역할:
1) MySQL에서 SELECT하여 스냅샷(JSON) 파일들(data/{name}.json) 생성
2) 생성된 JSON들과 db.py 자체를 git add/commit/push (충돌 시 data/*.json은 항상 ours 전략으로 자동 해결)

개선 포인트:
- data/*.json 전체를 merge=ours로 관리(여러 스냅샷 충돌 자동해결)
- DB 조회 재시도/타임아웃 추가로 안정성 강화
- 시간대 Asia/Seoul 고정(스냅샷 타임스탬프 일관성)
- SnapshotJob에 ORDER BY 지원(diff 안정성)
- 환경변수 필수값 검증
- allow_empty 커밋 옵션 실제 반영
"""

import os, json, subprocess, datetime, time
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
from mysql.connector import pooling, Error
import zoneinfo


load_dotenv()

# -----------------------------
# 상수/환경설정
# -----------------------------

# 시간대: 운영서버 TZ와 무관하게 고정
SEOUL_TZ = zoneinfo.ZoneInfo("Asia/Seoul")

# 스냅샷 디렉토리/패턴(여기 패턴을 .gitattributes와 충돌 자동해결에 사용)
SNAPSHOT_DIR = "data"
SNAPSHOT_GLOB = f"{SNAPSHOT_DIR}/*.json"

# 기본 브랜치(환경변수로 덮어쓰기 가능)
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")

# -----------------------------
# Snapshot Job 정의
# -----------------------------

@dataclass
class SnapshotJob:
    """
    스냅샷 1건을 정의하는 구조체
    - name: 생성 파일명(확장자 제외). 결과는 data/{name}.json
    - select: SELECT 절 문자열(예: "id, name, created_at")
    - from_: FROM 절 문자열(테이블/뷰 명)
    - where: WHERE 절 문자열(옵션)
    - order_by: ORDER BY 절 문자열(옵션; diff 안정성 위해 권장)
    - limit: LIMIT 개수(옵션; 대용량 방지 위해 권장)
    """
    name: str
    select: str
    from_: str
    where: str | None = None
    order_by: str | None = None
    limit: int | None = None

# ↓↓↓↓ 이 목록만 수정하면 됩니다. ↓↓↓↓
JOBS: list[SnapshotJob] = [
    SnapshotJob(
        name="study_progress",
        select="opentalk_code, nickname, study_group_title, progress_date, progress",
        from_="json_study_user_progress",
        order_by="opentalk_code, nickname, study_group_title, progress_date"
    ),
    SnapshotJob(
        name="study_cert",
        select="opentalk_code, name, user_rank, cert_days_count, average_week",
        from_="study_user_cert_wide",
        order_by="opentalk_code, name"
    ),
    # 예시:
    # SnapshotJob(
    #     name="credit_cards",
    #     select="id, user_id, amount, approved_at",
    #     from_="credit_card_raw",
    #     where="approved_at >= CURDATE() - INTERVAL 7 DAY",
    #     order_by="approved_at DESC",
    #     limit=50000
    # ),
]
# ↑↑↑↑ 목록 수정 시 data/{name}.json 파일 생성 ↑↑↑↑

# -----------------------------
# 유틸 함수
# -----------------------------

# --- [추가] 정보스키마에서 컬럼 목록 조회 ---
def _get_table_columns(schema: str, table: str) -> set[str]:
    """
    information_schema.columns에서 주어진 스키마/테이블의 실제 컬럼명을 집합으로 반환
    """
    sql = """
    SELECT COLUMN_NAME
    FROM information_schema.columns
    WHERE table_schema=%(schema)s AND table_name=%(table)s
    """
    rows = fetch_all(sql, {"schema": schema, "table": table})
    return {r["COLUMN_NAME"] for r in rows}

# --- [추가] select 문자열에서 원본 컬럼명만 추출(단순 파서) ---
def _parse_select_columns(select_expr: str) -> list[str]:
    """
    예: "id, `user_id`, amount as amt"
    - 백틱 제거, AS 별칭 제거, 공백 구분자 제거
    - 함수/표현식은 미지원(단순 컬럼 나열 가정)
    """
    cols = []
    for raw in select_expr.split(","):
        token = raw.strip().replace("`", "")
        token = token.split(" as ", 1)[0].split(" AS ", 1)[0]
        token = token.split()[0] if " " in token else token
        if token:
            cols.append(token)
    return cols

# --- [추가] 없는 컬럼 발견 시 에러 발생시키는 셀렉트 검증 ---
def _make_safe_select(job: SnapshotJob) -> str:
    """
    job.select을 그대로 쓰되, 실제 컬럼 존재 여부를 사전 검증.
    하나라도 없으면 RuntimeError로 중단(오타 조기 발견 목적).
    """
    if job.select.strip() == "*":
        return "*"
    table_cols = _get_table_columns(os.getenv("DB_NAME"), job.from_)
    requested = _parse_select_columns(job.select)
    missing = [c for c in requested if c not in table_cols]
    if missing:
        raise RuntimeError(f"[ERROR] Missing columns in {job.from_}: {', '.join(missing)}")
    return job.select


def _now_iso() -> str:
    """현재 시각을 Asia/Seoul 기준 ISO8601 문자열로 반환"""
    return datetime.datetime.now(SEOUL_TZ).isoformat()

def _require_env(keys: list[str]):
    """
    필수 환경변수 존재 확인. 누락 시 명확히 실패시켜 초기 설정 문제를 빨리 발견.
    """
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

def _build_sql(job: SnapshotJob) -> str:
    """
    SnapshotJob → 실제 실행할 SELECT SQL 생성
    - select 컬럼 존재 여부 사전검증(없으면 예외)
    """
    safe_select = _make_safe_select(job)
    sql = f"SELECT {safe_select} FROM {job.from_}"
    if job.where:
        sql += f" WHERE {job.where}"
    if job.order_by:
        sql += f" ORDER BY {job.order_by}"
    if job.limit:
        sql += f" LIMIT {int(job.limit)}"
    return sql


# -----------------------------
# 환경변수(.env) 로드 및 검증
# -----------------------------

# .env 로드
load_dotenv()

# 필수 항목 확인(없으면 바로 에러)
_require_env(["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"])

# DB 접속 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": True,
    # 안정성: 타임아웃 설정(초). 환경에 맞게 조정 가능.
    "connection_timeout": int(os.getenv("DB_CONN_TIMEOUT", "10")),
    "raise_on_warnings": False,
}

# 커넥션 풀 구성
POOL = pooling.MySQLConnectionPool(pool_name="main_pool", pool_size=5, **DB_CONFIG)

# -----------------------------
# DB I/O
# -----------------------------

def fetch_all(query: str, params: dict | None = None, retries: int = 2, delay: float = 1.5):
    """
    쿼리를 실행해 결과를 딕셔너리 리스트로 반환.
    실패 시 지수형 백오프로 재시도(retries회).
    - retries: 재시도 횟수
    - delay: 초기 대기(초). 시도할 때마다 배수로 증가(1x, 2x, 3x...)
    """
    for attempt in range(retries + 1):
        conn = cur = None
        try:
            conn = POOL.get_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute(query, params or {})
            return cur.fetchall()
        except Error as e:
            # 마지막 시도면 예외 전파
            if attempt >= retries:
                raise
            # 대기 후 재시도
            time.sleep(delay * (attempt + 1))
        finally:
            # 자원 정리(예외 여부와 무관)
            try:
                if cur: cur.close()
                if conn: conn.close()
            except:
                pass

def export_to_json(query: str, out_path: str, params: dict | None = None):
    """
    쿼리 실행 결과를 JSON으로 저장(원자적 교체).
    - out_path: 저장 경로(data/{name}.json)
    JSON 구조:
    {
      "generated_at": "...",
      "row_count": N,
      "source": {"type": "sql", "query": "..."},
      "rows": [...]
    }
    """
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

    # 임시파일에 먼저 기록(부분쓰기/프로세스 중단 등으로 인한 깨짐 방지)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, default=str)

    # JSON 검증(역직렬화에 실패하면 교체하지 않음)
    with open(tmp_path, encoding="utf-8") as f:
        json.load(f)

    # 원자적 교체
    os.replace(tmp_path, out_path)
    print(f"[OK] {snapshot['row_count']} rows → {out_path}")

def export_job(job: SnapshotJob) -> str:
    """
    JOB 한 건을 실행하여 data/{name}.json 생성 후 최종 경로 반환
    """
    out_path = f"{SNAPSHOT_DIR}/{job.name}.json"
    export_to_json(_build_sql(job), out_path=out_path)
    return out_path

# -----------------------------
# Git 유틸
# -----------------------------

def _run(cmd: str, check: bool = True, echo: bool = True):
    """
    셸 명령 실행 래퍼
    - check=True: 0이 아니면 RuntimeError
    - echo=True: 실행 커맨드 출력
    """
    if echo:
        print(f"$ {cmd}")
    cp = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and cp.returncode != 0:
        raise RuntimeError(f"[CMD FAIL] {cmd}\n{(cp.stdout or '')}{(cp.stderr or '')}".strip())
    if cp.stdout:
        print(cp.stdout.strip())
    return cp

def _ensure_branch(branch: str):
    """
    현재 브랜치를 지정 브랜치로 강제(없으면 생성/리셋)
    """
    cur = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, text=True, capture_output=True)
    current = (cur.stdout or "").strip()
    if current != branch:
        _run(f"git checkout -B {branch}")

def _ensure_gitattributes_for_snapshots():
    """
    data/*.json 파일은 항상 ours 머지 전략으로 설정
    - 다중 스냅샷 간 충돌 방지
    """
    line = f"{SNAPSHOT_GLOB} merge=ours\n"
    ga = Path(".gitattributes")
    existing = ga.read_text(encoding="utf-8") if ga.exists() else ""
    if line not in existing:
        ga.write_text(existing + line, encoding="utf-8")
        _run("git add .gitattributes", check=False)
        _run('git commit -m "chore: set merge=ours for data/*.json" --allow-empty', check=False)
        # ours 드라이버 설정(이미 설정돼 있어도 무해)
        _run('git config merge.ours.driver true', check=False)

def _auto_resolve_ours(paths: list[str]):
    """
    리베이스/머지 충돌 시 스냅샷 파일들을 ours로 자동 해결
    """
    for p in paths:
        _run(f"git checkout --ours {p}", check=False)
        _run(f"git add {p}", check=False)

def push_files(paths: list[str], branch: str | None = None, allow_empty: bool = True):
    """
    지정된 파일 목록을 git add/commit/push
    - paths: 커밋할 파일 리스트
    - allow_empty: 변경사항 없어도 빈 커밋을 생성할지 여부
    - 원격이 더 앞서 있으면 stash→pull --rebase→(충돌 시 data/*.json ours)→push→stash pop
    """
    branch = branch or GIT_BRANCH

    # git 리포지토리인지 확인
    _run("git rev-parse --is-inside-work-tree")
    _ensure_branch(branch)
    _ensure_gitattributes_for_snapshots()
    _run("git config core.autocrlf false", check=False)

    # 스냅샷 파일은 -f로 추가(무시 규칙에 걸려도 강제 추가)
    for p in paths:
        _run(f"git add -f {p}", check=False)

    msg = f'chore: update snapshot {_now_iso()}'
    commit_cmd = f'git commit -m "{msg}"'
    if allow_empty:
        commit_cmd += " --allow-empty"
    _run(commit_cmd, check=False)

    # upstream 존재여부 확인(최초 push면 -u 필요)
    up = subprocess.run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", shell=True, capture_output=True, text=True)
    first_push = (up.returncode != 0)

    def do_push(use_u: bool):
        _run(f"git push {'-u ' if use_u else ''}origin {branch}")

    try:
        do_push(first_push)
    except RuntimeError:
        # 원격이 더 앞서면 rebase 시도
        _run("git stash push -u -k -m autosync", check=False)
        try:
            _run(f"git pull --rebase origin {branch}")
        except RuntimeError:
            # 충돌나면 이번에 커밋하려던 파일들만 ours로 해결
            _auto_resolve_ours(paths)
            _run("git rebase --continue", check=False)
        do_push(False)
        _run("git stash pop", check=False)

    # push 결과 간단 검증
    local = subprocess.run("git rev-parse HEAD", shell=True, text=True, capture_output=True).stdout.strip()
    remote = subprocess.run(f"git ls-remote origin {branch}", shell=True, text=True, capture_output=True).stdout.split("\t")[0].strip()
    print(f"[OK] git push 완료. local={local[:7]} remote={remote[:7]}")

# -----------------------------
# 실행부
# -----------------------------

if __name__ == "__main__":
    # 1) 각 JOB 실행 → data/{name}.json 생성
    out_files = [export_job(job) for job in JOBS]

    # 2) 생성된 JSON들 + db.py 푸시
    push_files(paths=out_files + ["db.py"], branch=GIT_BRANCH, allow_empty=True)

