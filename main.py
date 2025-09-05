# main.py
from fastapi import FastAPI, HTTPException
import json, os, time

app = FastAPI()

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")

def _load_rows():
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(500, detail="progress.json not found")
    except json.JSONDecodeError:
        raise HTTPException(500, detail="progress.json is invalid JSON")

    # 리스트 형태 또는 {"rows":[...]} 둘 다 지원
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "rows" in data and isinstance(data["rows"], list):
        return data["rows"]
    # 그 밖의 형태면 에러
    raise HTTPException(500, detail="Unexpected JSON format: expected list or {rows: list}")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/progress/test")
def progress_test():
    rows = _load_rows()
    return {"ok": True, "count": len(rows), "rows": rows, "source": "file"}

# 선택: 파일 상태 빠르게 확인하고 싶을 때
@app.get("/progress/inspect")
def progress_inspect():
    try:
        st = os.stat(DATA_PATH)
        return {
            "exists": True,
            "size_bytes": st.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "path": DATA_PATH,
        }
    except FileNotFoundError:
        return {"exists": False, "path": DATA_PATH}
