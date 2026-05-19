from fastapi import FastAPI
import os

app = FastAPI(title="Sentinal RAG", version="1.0.0")

@app.get("/")
def root():
    return {"status": "ok", "message": "Sentinal RAG is running"}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "sentinal-rag",
        "version": os.getenv("APP_VERSION", "dev"),
    }

@app.get("/ready")
def ready():
    return {
        "status": "ready",
        "service": "sentinal-rag",
        "version": os.getenv("APP_VERSION", "dev"),
    }
