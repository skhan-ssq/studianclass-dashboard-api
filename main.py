from fastapi import FastAPI
import json, os

app = FastAPI()

BASE_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(BASE_DIR, "data", "progress.json")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/progress/test")
def progress_test():
    with open(DATA_PATH, encoding="utf-8") as f:
        rows = json.load(f)
    return {"ok": True, "rows": rows, "source": "file"}
