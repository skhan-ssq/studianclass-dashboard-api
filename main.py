# main.py
from fastapi import FastAPI
from db import fetch_all

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/progress/sample")
def sample():
    rows = fetch_all("SELECT NOW() AS server_time")
    return rows
