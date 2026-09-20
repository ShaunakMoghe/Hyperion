"""Scaffold smoke tests (H-002): imports, config defaults, secret hygiene."""

from pathlib import Path

from hyperion import config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_config_defaults(monkeypatch):
    # Hermetic against a developer .env: defaults hold when the vars that
    # override them are absent (the suite otherwise runs with keys set).
    for var in ("HYPERION_LLM_BUDGET_USD", "HYPERION_LLM_PROVIDER",
                "HYPERION_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    cfg = config.load()
    assert cfg.llm_budget_usd == 20.0
    assert cfg.llm_provider == ""
    assert cfg.llm_model == ""


def test_env_example_has_no_secrets():
    text = (REPO_ROOT / ".env.example").read_text()
    for token in ("sk_live_", "sk-", "AIza", "ghp_", "agentrollback123"):
        assert token not in text


def test_compose_is_postgres_only():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "postgres:16" in text
    assert "neo4j" not in text.lower()
