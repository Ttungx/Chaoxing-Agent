from chaoxing_agent import paths


def test_source_resource_root_contains_prompts():
    root = paths.resource_root()
    assert (root / "prompts" / "vision_prompt.txt").exists()
    assert (root / "config" / "config.json.example").exists()


def test_runtime_root_can_be_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOXING_AGENT_DATA_DIR", str(tmp_path))
    assert paths.runtime_root() == tmp_path
    assert paths.runtime_config_dir() == tmp_path / "config"
    assert paths.trace_dir() == tmp_path / "trace"
