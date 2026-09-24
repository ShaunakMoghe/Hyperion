"""M9: gateway policy resolution (pure, no DB)."""

from pathlib import Path

from hyperion.mcp_gateway import proxy


def test_no_policy_configured_means_ungoverned(monkeypatch):
    monkeypatch.delenv("HYPERION_POLICY", raising=False)
    assert proxy.resolve_policy_path({"tools": {}}) is None
    assert proxy.load_configured_policy({"tools": {}}) == (
        None, None, None, None)


def test_env_override_wins_over_map(tmp_path, monkeypatch):
    map_policy = tmp_path / "map.yaml"
    map_policy.write_text("default: allow\n")
    env_policy = tmp_path / "env.yaml"
    env_policy.write_text("default: deny\n")
    monkeypatch.setenv("HYPERION_POLICY", str(env_policy))
    assert proxy.resolve_policy_path({"policy": str(map_policy)}) == env_policy


def test_empty_env_override_falls_back_to_map(tmp_path, monkeypatch):
    map_policy = tmp_path / "map.yaml"
    map_policy.write_text("default: allow\n")
    monkeypatch.setenv("HYPERION_POLICY", "")
    assert (proxy.resolve_policy_path({"policy": str(map_policy)})
            == map_policy)


def test_relative_map_path_resolves_against_repo_root(monkeypatch):
    monkeypatch.delenv("HYPERION_POLICY", raising=False)
    assert (proxy.resolve_policy_path({"policy": "gateway/policy.yaml"})
            == proxy.REPO_ROOT / "gateway" / "policy.yaml")


def test_relative_env_path_resolves_against_repo_root(monkeypatch):
    monkeypatch.setenv("HYPERION_POLICY", "gateway/policy.yaml")
    assert (proxy.resolve_policy_path({"tools": {}})
            == proxy.REPO_ROOT / "gateway" / "policy.yaml")


def test_absolute_path_passes_through(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERION_POLICY", raising=False)
    target = tmp_path / "p.yaml"
    assert proxy.resolve_policy_path({"policy": str(target)}) == target


def test_valid_policy_loads_with_stable_sha(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("default: allow\n")
    path, parsed, sha, error = proxy.load_configured_policy(
        {"policy": str(policy)})
    assert error is None
    assert path == policy
    assert parsed == {"default": "allow", "rules": []}
    assert len(sha) == 64
    assert proxy.load_configured_policy(
        {"policy": str(policy)})[2] == sha


def test_missing_policy_file_is_an_error(tmp_path):
    path, parsed, sha, error = proxy.load_configured_policy(
        {"policy": str(tmp_path / "nope.yaml")})
    assert (path, parsed, sha) == (None, None, None)
    assert "missing" in error


def test_unparsable_policy_is_an_error(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("default: [unclosed\n")
    _, _, _, error = proxy.load_configured_policy(
        {"policy": str(policy)})
    assert error is not None


def test_bad_rule_shape_is_an_error(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text("default: allow\nrules:\n  - match: {system: crm}\n")
    _, _, _, error = proxy.load_configured_policy(
        {"policy": str(policy)})
    assert "match.system" in error


def test_shipped_gateway_policy_is_valid():
    path = Path(proxy.REPO_ROOT) / "gateway" / "policy.yaml"
    loaded = proxy.load_configured_policy({"policy": str(path)})
    assert loaded[3] is None, loaded[3]
    assert loaded[0] == path
    assert loaded[1]["default"] == "allow"
