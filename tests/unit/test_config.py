from __future__ import annotations

from pathlib import Path

from dmfw_places_spider.config.settings import load_settings


def test_load_settings_merges_yaml_and_env_with_env_precedence(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        """
app:
  env: development
  log_level: DEBUG
paths:
  sqlite_path: data/processed/from_yaml.db
proxy:
  enabled: false
  pool:
    - http://yaml-proxy.example:9000
geo:
  provider: mock
""".strip(),
        encoding="utf-8",
    )

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "GEONODE_LOG_LEVEL=WARNING",
                "GEONODE_SQLITE_PATH=data/processed/from_env.db",
                "GEONODE_PROXY_ENABLED=true",
                "GEONODE_PROXY_POOL=http://proxy-a.example:8080,http://proxy-b.example:8080",
                "GEONODE_GEO_PROVIDER=amap",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("GEONODE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("GEONODE_SQLITE_PATH", raising=False)
    monkeypatch.delenv("GEONODE_PROXY_ENABLED", raising=False)
    monkeypatch.delenv("GEONODE_PROXY_POOL", raising=False)
    monkeypatch.delenv("GEONODE_GEO_PROVIDER", raising=False)

    settings = load_settings(
        env_path=env_path,
        yaml_path=yaml_path,
        project_root=tmp_path,
    )

    assert settings.log_level == "WARNING"
    assert settings.sqlite_path == tmp_path / "data/processed/from_env.db"
    assert settings.proxy_enabled is True
    assert settings.proxy_pool == [
        "http://proxy-a.example:8080",
        "http://proxy-b.example:8080",
    ]
    assert settings.geo_provider == "amap"
