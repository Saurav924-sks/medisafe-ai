import os
from pathlib import Path

from dotenv import load_dotenv

from app.core.config import Settings, discover_root_env_file


def _make_project_config_path(root: Path) -> Path:
    config_path = root / "frontend" / "backend" / "app" / "core" / "config.py"
    config_path.parent.mkdir(parents=True)
    (root / "frontend" / "backend" / "requirements.txt").parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    (root / "frontend" / "backend" / "requirements.txt").touch()
    (root / ".env.example").touch()
    return config_path


def test_discovers_local_project_root_env_file(tmp_path, monkeypatch):
    config_path = _make_project_config_path(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("SYNTHETIC_CONFIG_TEST=from-project-env\n", encoding="utf-8")
    monkeypatch.delenv("SYNTHETIC_CONFIG_TEST", raising=False)

    discovered = discover_root_env_file(config_path)

    assert discovered == env_file
    assert load_dotenv(discovered, override=False)
    assert os.environ["SYNTHETIC_CONFIG_TEST"] == "from-project-env"


def test_no_env_file_and_unrelated_env_ancestors_are_ignored(tmp_path, monkeypatch):
    config_path = _make_project_config_path(tmp_path / "project")
    docker_root = tmp_path / "docker-image"
    docker_config_path = docker_root / "app" / "core" / "config.py"
    docker_config_path.parent.mkdir(parents=True)
    unrelated_env = tmp_path / ".env"
    unrelated_env.write_text(
        "SYNTHETIC_CONFIG_TEST=must-not-load\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SYNTHETIC_CONFIG_TEST", raising=False)

    assert discover_root_env_file(config_path) is None
    assert "SYNTHETIC_CONFIG_TEST" not in os.environ
    assert discover_root_env_file(docker_config_path) is None


def test_host_environment_settings_are_honored_without_env_file(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "app" / "core" / "config.py"
    config_path.parent.mkdir(parents=True)
    monkeypatch.setenv("API_KEY", "synthetic-host-provided-key")
    monkeypatch.setenv("APP_ENV", "staging")

    assert discover_root_env_file(config_path) is None
    settings = Settings()

    assert settings.API_KEY == "synthetic-host-provided-key"
    assert settings.APP_ENV == "staging"
