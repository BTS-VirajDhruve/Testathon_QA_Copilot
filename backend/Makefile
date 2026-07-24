# Backend developer commands (run from this directory: backend/)
.PHONY: sync dev test seed

sync:
	uv sync --extra dev

dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest -q

seed:
	uv run python -c "from seed.demo_seed import seed_signin_demo; print(seed_signin_demo(force=True))"