"""Configuration for MCXboxBroadcast Standalone build 160 (schema 7)."""

import shutil
from copy import deepcopy
from pathlib import Path

import yaml

CONFIG_VERSION = 7


def read_properties(path):
    if not path.exists():
        return {}
    properties = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "!")) and "=" in line:
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
    return properties


def _section(parent, key):
    value = parent.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a YAML mapping")
    return value


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def build_config(existing, properties, server_ip, server_port):
    """Migrate old wrapper configs and preserve user settings in current configs."""
    if not isinstance(existing, dict):
        raise ValueError("config.yml must contain a YAML mapping")
    config = deepcopy(existing)
    version = _integer(
        config.get("config-version", 0), "config-version", 0, CONFIG_VERSION
    )
    migrating = version < CONFIG_VERSION
    session = _section(config, "session")
    info = _section(session, "session-info")
    friends = _section(config, "friend-sync")
    expiry = _section(friends, "expiry")

    # Older upstream root settings, including configs predating schema 2.
    for key in ("remote-address", "remote-port", "update-interval"):
        if key in config:
            session.setdefault(key, config.pop(key))
    for old, new in (
        ("debug-log", "debug-mode"),
        ("suppress-session-update-info", "suppress-session-update-message"),
        ("slack-webhook", "notifications"),
    ):
        if old in config:
            config.setdefault(new, config.pop(old))
    for old, new in (
        ("should-expire", "enabled"),
        ("expire-days", "days"),
        ("expire-check", "check"),
    ):
        if old in friends:
            expiry.setdefault(new, friends.pop(old))
    if "auto-follow" in friends:
        friends.setdefault("auto-friend", friends.pop("auto-follow"))
    friends.pop("auto-unfollow", None)
    session.pop("ice-port-range", None)
    info.pop("ip", None)
    info.pop("port", None)

    # The old wrapper advertised a public transfer address. Build 160 needs the
    # local backend's HTTP signaling address, avoiding public NAT hairpinning.
    address = properties.get("server-ip") or server_ip
    address = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(address, address)
    port = _integer(properties.get("server-port", server_port), "server-port", 1, 65535)
    if migrating:
        session["remote-address"] = address
        session["remote-port"] = str(port)
        session["query-server"] = True
        session["config-fallback"] = True
    else:
        session.setdefault("remote-address", address)
        session.setdefault("remote-port", str(port))
    if (
        not isinstance(session["remote-address"], str)
        or not session["remote-address"].strip()
    ):
        raise ValueError("session.remote-address must be a non-empty hostname or IP")
    if str(session["remote-port"]) != "auto":
        session["remote-port"] = str(
            _integer(session["remote-port"], "remote-port", 1, 65535)
        )

    session.setdefault("query-server", True)
    session.setdefault("config-fallback", True)
    session.setdefault("web-query-fallback", False)
    session.setdefault("hide-old-sessions", True)
    session["update-interval"] = _integer(
        session.get("update-interval", 30), "session.update-interval", 20, 2147483647
    )
    info["host-name"] = properties.get(
        "server-name", info.get("host-name", "Endstone Server")
    )
    info["world-name"] = properties.get("level-name", info.get("world-name", "World"))
    info.setdefault("game-mode", properties.get("gamemode", "survival").capitalize())
    info.setdefault("players", 0)
    info.setdefault(
        "max-players",
        _integer(properties.get("max-players", 20), "max-players", 1, 2147483647),
    )

    friends["update-interval"] = _integer(
        friends.get("update-interval", 60),
        "friend-sync.update-interval",
        20,
        2147483647,
    )
    friends.setdefault("auto-friend", True)
    friends.setdefault("initial-invite", True)
    expiry.setdefault("enabled", True)
    expiry.setdefault("days", 15)
    expiry.setdefault("check", 1800)
    _section(config, "notifications").setdefault("enabled", False)
    config.setdefault("debug-mode", False)
    config.setdefault("suppress-session-update-message", True)
    config["config-version"] = CONFIG_VERSION
    return config


def sync_config(path, properties, server_ip, server_port):
    """Back up legacy YAML once and atomically install the migrated configuration."""
    path = Path(path)
    original = path.read_text(encoding="utf-8-sig") if path.exists() else None
    existing = yaml.safe_load(original) if original is not None else {}
    if existing is None:
        existing = {}
    config = build_config(existing, properties, server_ip, server_port)
    rendered = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    if rendered != original:
        backup = path.with_name(path.name + ".pre-v7.bak")
        if (
            original is not None
            and existing.get("config-version", 0) != CONFIG_VERSION
            and not backup.exists()
        ):
            shutil.copy2(path, backup)
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(rendered, encoding="utf-8")
            if original is not None:
                shutil.copymode(path, temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return config
