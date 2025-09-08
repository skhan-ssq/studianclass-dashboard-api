from fastapi import FastAPI, HTTPException, Query
import json, os, time

app = FastAPI()
BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")


def _load_rows():
    try:
        # BOM(utf-8-sig) 허용
        with open(DATA_PATH, encoding="utf-8-sig") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                # 에러 메시지에 위치 정보 포함
                raise HTTPException(
                    500,
                    detail={
                        "error": "progress.json is invalid JSON",
                        "msg": e.msg,
                        "lineno": e.lineno,
                        "colno": e.colno,
                    },
                )
    except FileNotFoundError:
        raise HTTPException(500, detail="progress.json not found")

    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return data["rows"]
    raise HTTPException(500, detail="Unexpected JSON format")


@app.get("/health")
def health():
    return {"status": "ok"}


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


@app.get("/progress/validate")
def progress_validate():
    try:
        with open(DATA_PATH, encoding="utf-8-sig") as f:
            json.load(f)
        return {"ok": True}
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "error": "progress.json is invalid JSON",
            "msg": e.msg,
            "lineno": e.lineno,
            "colno": e.colno,
        }
    except FileNotFoundError:
        return {"ok": False, "error": "progress.json not found"}


@app.get("/progress/test")
def progress_test(
    limit: int = Query(10, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    rows = _load_rows()
    sliced = rows[offset : offset + limit]
    return {
        "ok": True,
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "count": len(sliced),
        "rows": sliced,
        "source": "file",
    }
