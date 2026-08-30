.DEFAULT_GOAL := help
.PHONY: help install env serve health chat-smoke-test agent-smoke-test conversation-smoke-test ui \
        langfuse-up langfuse-down langfuse-logs langfuse-smoke-test \
        up down restart logs \
        test test-unit test-integration \
        lint format format-check typecheck check \
        generate-data tools-smoke-test generate-eval-dataset evaluate eval-ci \
        seed-prompts prompts-smoke-test \
        sync-eval-dataset experiment-prompt-v1 experiment-prompt-v2 \
        clean

# ── Colours ───────────────────────────────────────────────────────────────────
CYAN  := \033[0;36m
RESET := \033[0m

help:  ## Show this help message
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-24s$(RESET) %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────

install:  ## Install all dependencies with uv
	uv sync --all-groups

env:  ## Copy .env.example → .env if .env does not exist
	@test -f .env && echo ".env already exists — skipping" || (cp .env.example .env && echo "Created .env from .env.example — fill in credentials before running.")

# ── API server ────────────────────────────────────────────────────────────────

serve:  ## Start the FastAPI development server (auto-reload)
	uv run uvicorn travel_ai_concierge.api.app:app \
	  --host $${API_HOST:-0.0.0.0} \
	  --port $${API_PORT:-8000} \
	  --reload

health:  ## Check /health endpoint (requires server running)
	curl -s http://localhost:$${API_PORT:-8000}/health | python3 -m json.tool

chat-smoke-test:  ## Call POST /chat over real HTTP and print the response (requires `make serve`)
	uv run python scripts/smoke_test_chat.py

agent-smoke-test:  ## Compare "simple chatbot" vs "tool-using agent" traces (no server needed)
	uv run python scripts/smoke_test_agent.py

conversation-smoke-test:  ## Run a real 3-turn conversation and inspect stored session state (requires `make serve`)
	uv run python scripts/smoke_test_conversation.py

ui:  ## Start the Streamlit chat UI (requires `make serve` running separately)
	uv run streamlit run ui/streamlit_app.py

# ── Langfuse (Milestone 1) ────────────────────────────────────────────────────

langfuse-up:  ## Start the local self-hosted Langfuse stack
	docker compose up -d

langfuse-down:  ## Stop the local Langfuse stack
	docker compose down

langfuse-logs:  ## Tail Langfuse logs
	docker compose logs -f

langfuse-smoke-test:  ## Create a real test trace and print its URL
	uv run python scripts/smoke_test_langfuse.py

# ── Full stack (Milestone 2+) ─────────────────────────────────────────────────

up:  ## Start the full stack (Langfuse + API)
	docker compose up -d

down:  ## Stop the full stack
	docker compose down

restart:  ## Restart the full stack
	docker compose restart

logs:  ## Tail all service logs
	docker compose logs -f

# ── Tests ─────────────────────────────────────────────────────────────────────

test:  ## Run all tests
	uv run pytest

test-unit:  ## Run unit tests only
	uv run pytest tests/unit

test-integration:  ## Run integration tests (requires live infrastructure)
	uv run pytest tests/integration -m integration

# ── Code quality ──────────────────────────────────────────────────────────────

lint:  ## Lint with Ruff
	uv run ruff check src/ tests/ ui/

format:  ## Auto-format with Ruff
	uv run ruff format src/ tests/ ui/

format-check:  ## Check formatting without modifying files
	uv run ruff format --check src/ tests/ ui/

typecheck:  ## Type-check with mypy
	uv run mypy src/ ui/

check: lint format-check typecheck  ## Run all quality checks

# ── Data and evaluation (Milestone 4+) ───────────────────────────────────────

generate-data:  ## Generate synthetic travel data (writes data/synthetic/*.json)
	uv run python scripts/generate_data.py

tools-smoke-test:  ## Call the travel tools directly and print real Langfuse tool traces
	uv run python scripts/smoke_test_tools.py

generate-eval-dataset:  ## (Re)write data/evaluation/cases.json (Milestone 9)
	uv run python scripts/generate_evaluation_dataset.py

evaluate:  ## Run the deterministic evaluation suite (human + machine-readable report)
	uv run python scripts/run_evaluation.py

eval-ci:  ## Run evaluation, exit non-zero if a case crashed (not yet a regression gate — see Milestone 17)
	uv run python scripts/run_evaluation.py --ci

# ── Prompt management (Milestone 8) ──────────────────────────────────────────

seed-prompts:  ## Create/update system prompt v1 (production) + v2 (staging) in Langfuse
	uv run python scripts/seed_prompts.py

prompts-smoke-test:  ## Compare prompt v1 vs v2 (no server needed; run `make seed-prompts` first)
	uv run python scripts/smoke_test_prompts.py

# ── Langfuse datasets and experiments (Milestone 10) ─────────────────────────

sync-eval-dataset:  ## Publish/update data/evaluation/cases.json as a Langfuse Dataset
	uv run python scripts/sync_eval_dataset.py

experiment-prompt-v1:  ## Run the eval dataset as a Langfuse experiment against prompt v1 (production)
	PROMPT_LABEL=production uv run python scripts/run_experiment.py --run-name prompt-v1 --description "System prompt v1 (production)"

experiment-prompt-v2:  ## Run the eval dataset as a Langfuse experiment against prompt v2 (staging)
	PROMPT_LABEL=staging uv run python scripts/run_experiment.py --run-name prompt-v2 --description "System prompt v2 (staging)"

# ── Housekeeping ──────────────────────────────────────────────────────────────

clean:  ## Remove cache and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	@echo "Cleaned."
