from copy import deepcopy

import pytest
import yaml

from endstone_broadcaster.config import build_config, read_properties, sync_config


def test_legacy_migration_uses_local_signaling_and_preserves_custom_settings(tmp_path):
    path = tmp_path / "config.yml"
    original = """session:
  query-server: false
  config-fallback: false
  remote-address: old-advertised.example
  remote-port: 25565
  ice-port-range: 40000-40100
  session-info:
    ip: 203.0.113.10
    port: 19132
    max-players: 50
friend-sync:
  auto-follow: false
  auto-unfollow: true
  expiry:
    days: 40
notifications:
  enabled: true
  webhook-url: https://example.invalid:8443/slack
debug-mode: true
"""
    path.write_text(original, encoding="utf-8")
    original_bytes = path.read_bytes()
    config = sync_config(path, {"server-port": "19140"}, "127.0.0.1", 19132)
    session = config["session"]
    assert config["config-version"] == 9
    assert session["remote-address"] == "127.0.0.1"
    assert session["remote-port"] == "19140"
    assert session["query-server"] is True
    assert session["config-fallback"] is True
    assert "ip" not in session["session-info"]
    assert "port" not in session["session-info"]
    assert "ice-port-range" not in session
    assert session["session-info"]["max-players"] == 50
    assert config["friend-sync"]["auto-friend"] is False
    assert "auto-follow" not in config["friend-sync"]
    assert "auto-unfollow" not in config["friend-sync"]
    assert config["friend-sync"]["expiry"]["days"] == 40
    assert (
        config["notifications"]["webhook-url"] == "https://example.invalid:8443/slack"
    )
    assert config["debug-mode"] is True
    assert path.with_name("config.yml.pre-v9.bak").read_bytes() == original_bytes
    first_bytes = path.read_bytes()
    first_mtime = path.stat().st_mtime_ns
    assert sync_config(path, {"server-port": "19140"}, "127.0.0.1", 19132) == config
    assert path.read_bytes() == first_bytes
    assert path.stat().st_mtime_ns == first_mtime
    assert path.with_name("config.yml.pre-v9.bak").read_bytes() == original_bytes


def test_v7_custom_endpoint_and_query_choices_survive():
    original = {
        "config-version": 7,
        "session": {
            "remote-address": "backend.internal",
            "remote-port": "20000",
            "query-server": False,
            "config-fallback": False,
            "hide-old-sessions": False,
        },
    }
    before = deepcopy(original)
    config = build_config(original, {"server-port": "19140"}, "127.0.0.1", 19132)
    assert original == before
    assert config["session"]["remote-address"] == "backend.internal"
    assert config["session"]["remote-port"] == "20000"
    for field in ("query-server", "config-fallback", "hide-old-sessions"):
        assert config["session"][field] is False


@pytest.mark.parametrize(
    ("address", "expected"),
    [("0.0.0.0", "127.0.0.1"), ("::", "::1"), ("10.0.0.5", "10.0.0.5")],
)
def test_bind_address_and_safe_yaml_names(tmp_path, address, expected):
    path = tmp_path / "config.yml"
    properties = {
        "server-ip": address,
        "server-name": 'A "quoted": # realm \\1',
        "level-name": "Off",
        "gamemode": "creative",
        "max-players": "100",
    }
    config = sync_config(path, properties, "127.0.0.1", 19132)
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed == config
    assert parsed["session"]["remote-address"] == expected
    assert parsed["session"]["session-info"]["host-name"] == properties["server-name"]
    assert parsed["session"]["session-info"]["world-name"] == "Off"
    assert parsed["session"]["session-info"]["game-mode"] == "Creative"
    assert parsed["session"]["session-info"]["max-players"] == 100


def test_predating_schema_two_settings_migrate():
    config = build_config(
        {
            "debug-log": True,
            "suppress-session-update-info": False,
            "slack-webhook": {
                "enabled": True,
                "webhook-url": "https://example.invalid",
            },
            "update-interval": 45,
            "friend-sync": {
                "should-expire": False,
                "expire-days": 90,
                "expire-check": 2000,
            },
        },
        {},
        "127.0.0.1",
        19132,
    )
    assert config["debug-mode"] is True
    assert config["suppress-session-update-message"] is False
    assert config["notifications"]["enabled"] is True
    assert config["session"]["update-interval"] == 45
    assert config["friend-sync"]["expiry"] == {
        "enabled": False,
        "days": 90,
        "check": 2000,
    }


@pytest.mark.parametrize(
    "text",
    [
        "session: [broken]",
        "config-version: 10",
        "session:\n  update-interval: 1",
        "session:\n  remote-port: false\nconfig-version: 7",
        "- invalid-root",
        "session: [unclosed",
    ],
)
def test_invalid_or_future_config_is_not_overwritten(tmp_path, text):
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError)):
        sync_config(path, {}, "127.0.0.1", 19132)
    assert path.read_text(encoding="utf-8") == text
    assert not path.with_name("config.yml.pre-v9.bak").exists()


def test_read_properties_handles_comments_bom_and_embedded_equals(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text(
        "\ufeff# server-name=ignored\nserver-name=Name=Value\n!comment\n server-port = 19140 \n",
        encoding="utf-8",
    )
    assert read_properties(path) == {
        "server-name": "Name=Value",
        "server-port": "19140",
    }


@pytest.mark.parametrize("version", [7, 8, 9])
@pytest.mark.parametrize("ipv6", [False, True])
def test_schema9_preserves_migrated_preferences_and_is_idempotent(
    tmp_path, version, ipv6
):
    path = tmp_path / "config.yml"
    original = {
        "config-version": version,
        "session": {
            "remote-address": "custom.example",
            "remote-port": "auto",
            "query-server": False,
            "config-fallback": False,
            "allow-ipv6": ipv6,
            "web-query-fallback": True,
        },
        "custom-extension": {"keep": "yes"},
    }
    path.write_text(yaml.safe_dump(original), encoding="utf-8")
    before = path.read_bytes()
    config = sync_config(path, {}, "127.0.0.1", 19132)
    session = config["session"]
    assert config["config-version"] == 9
    assert session["remote-address"] == "custom.example"
    assert session["remote-port"] == "auto"
    assert session["query-server"] is False
    assert session["config-fallback"] is False
    assert session["allow-ipv6"] is ipv6
    assert "web-query-fallback" not in session
    assert config["custom-extension"] == {"keep": "yes"}
    if version < 9:
        assert path.with_name("config.yml.pre-v9.bak").read_bytes() == before
    timestamp = path.stat().st_mtime_ns
    assert sync_config(path, {}, "127.0.0.1", 19132) == config
    assert path.stat().st_mtime_ns == timestamp


@pytest.mark.parametrize("target", [7, 8, 9])
def test_build_targets_match_upstream_schema(target):
    config = build_config({}, {}, "127.0.0.1", 19132, target_version=target)
    assert config["config-version"] == target
    session = config["session"]
    assert ("allow-ipv6" in session) == (target >= 8)
    if target >= 8:
        assert session["allow-ipv6"] is False
    assert ("web-query-fallback" in session) == (target < 9)


@pytest.mark.parametrize("version,target", [(8, 7), (9, 7), (9, 8), (10, 9)])
def test_no_schema_downgrade_or_future_overwrite(tmp_path, version, target):
    path = tmp_path / "config.yml"
    original = f"# keep exact bytes\nconfig-version: {version}\n"
    path.write_text(original)
    with pytest.raises(ValueError):
        sync_config(path, {}, "127.0.0.1", 19132, target_version=target)
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]


def test_schema9_backup_does_not_replace_old_schema7_backup(tmp_path):
    path = tmp_path / "config.yml"
    old_backup = tmp_path / "config.yml.pre-v7.bak"
    old_backup.write_text("old backup")
    path.write_text("config-version: 7\n")
    sync_config(path, {}, "127.0.0.1", 19132)
    assert old_backup.read_text() == "old backup"
    assert (tmp_path / "config.yml.pre-v9.bak").read_text() == "config-version: 7\n"
