# main.py
from fastapi import FastAPI
from db import fetch_all

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/progress/test")
def progress_test():
    rows = fetch_all("SELECT 1 AS ok")
    return {"ok": True, "rows": rows}
