.PHONY: run build smoke

run:
\tuvicorn app.main:app --host 0.0.0.0 --port 8000

build:
\tdocker build -t sentinal-rag:latest .

smoke:
\tbash scripts/smoke.sh
