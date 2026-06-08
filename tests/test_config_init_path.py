"""config_init 路径定位的回归测试。

config.json.example / model_services.json.example / .env.example
在项目根的 config/ 目录；chaoxing_agent/core/config_init.py 位于
chaoxing_agent/core/，到项目根需向上 3 层。
"""

from pathlib import Path


def test_config_dir_points_to_project_root_config(tmp_path, monkeypatch):
    """当 main.py 直接 import 时，_config_dir() 应解析到项目根的 config/。"""
    # 模拟真实目录结构：
    #   tmp_path/
    #   ├── config/
    #   │   ├── config.json.example
    #   │   ├── model_services.json.example
    #   │   └── .env.example
    #   └── chaoxing_agent/
    #       └── core/
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json.example").write_text('{"k":"v"}', encoding="utf-8")
    (cfg_dir / "model_services.json.example").write_text('{"vision":{}}', encoding="utf-8")
    (cfg_dir / ".env.example").write_text("VISION_API_KEY=\n", encoding="utf-8")

    monkeypatch.setattr("chaoxing_agent.core.config_init._config_dir", lambda: cfg_dir)

    from chaoxing_agent.core.config_init import ensure_config_files
    out = ensure_config_files()
    names = {Path(d).name for _, d in out}
    assert names == {"config.json", "model_services.json", ".env"}


def test_resolves_to_real_project_layout():
    """_config_dir() 的真实实现必须能解析到本项目的 config/ 目录。"""
    from pathlib import Path
    from chaoxing_agent.core.config_init import _config_dir

    real_cfg = _config_dir()
    # 应有 *.example 文件
    assert (real_cfg / "config.json.example").exists(), (
        f"_config_dir()={real_cfg} 解析错位，找不到 config.json.example"
    )
    assert (real_cfg / "model_services.json.example").exists()
    assert (real_cfg / ".env.example").exists()


def test_force_init_does_not_overwrite_existing_env(tmp_path, monkeypatch):
    """force 初始化不应覆盖已有 config/.env，避免清空 API key。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json.example").write_text('{"k":"v2"}', encoding="utf-8")
    (cfg_dir / "model_services.json.example").write_text('{"vision":{}}', encoding="utf-8")
    (cfg_dir / ".env.example").write_text("VISION_API_KEY=\n", encoding="utf-8")

    (cfg_dir / "config.json").write_text('{"k":"old"}', encoding="utf-8")
    (cfg_dir / "model_services.json").write_text('{"old":true}', encoding="utf-8")
    (cfg_dir / ".env").write_text("VISION_API_KEY=SECRET\n", encoding="utf-8")

    monkeypatch.setattr("chaoxing_agent.core.config_init._config_dir", lambda: cfg_dir)

    from chaoxing_agent.core.config_init import init_config_files

    init_config_files(force=True)

    assert (cfg_dir / "config.json").read_text(encoding="utf-8") == '{"k":"v2"}'
    assert (cfg_dir / "model_services.json").read_text(encoding="utf-8") == '{"vision":{}}'
    assert (cfg_dir / ".env").read_text(encoding="utf-8") == "VISION_API_KEY=SECRET\n"


def test_force_init_creates_env_when_missing(tmp_path, monkeypatch):
    """force 初始化时如果 .env 缺失，仍应从模板创建。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json.example").write_text('{"k":"v"}', encoding="utf-8")
    (cfg_dir / "model_services.json.example").write_text('{"vision":{}}', encoding="utf-8")
    (cfg_dir / ".env.example").write_text("VISION_API_KEY=\n", encoding="utf-8")

    monkeypatch.setattr("chaoxing_agent.core.config_init._config_dir", lambda: cfg_dir)

    from chaoxing_agent.core.config_init import init_config_files

    init_config_files(force=True)

    assert (cfg_dir / ".env").exists()
    assert (cfg_dir / ".env").read_text(encoding="utf-8") == "VISION_API_KEY=\n"


def test_runtime_config_created_from_resource_templates(tmp_path, monkeypatch):
    resource = tmp_path / "resources"
    runtime = tmp_path / "runtime"
    cfg_resource = resource / "config"
    cfg_resource.mkdir(parents=True)
    (cfg_resource / "config.json.example").write_text(
        '{"runtime": {"max_steps": 1}}',
        encoding="utf-8",
    )
    (cfg_resource / "model_services.json.example").write_text(
        '{"vision": {}, "solver": {}}',
        encoding="utf-8",
    )
    (cfg_resource / ".env.example").write_text(
        "VISION_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CHAOXING_AGENT_RESOURCE_DIR", str(resource))
    monkeypatch.setenv("CHAOXING_AGENT_DATA_DIR", str(runtime))

    from chaoxing_agent.core.config_init import ensure_config_files

    ensure_config_files()

    assert (runtime / "config" / "config.json").exists()
    assert (runtime / "config" / "model_services.json").exists()
    assert (runtime / "config" / ".env").exists()
