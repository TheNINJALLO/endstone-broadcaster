import hashlib
import io
import json
import subprocess
import threading
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from endstone_broadcaster.manager import BroadcasterManager


@pytest.fixture
def manager(tmp_path):
    return BroadcasterManager(tmp_path, Mock(), "127.0.0.1", 19132)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('openjdk version "21.0.9" 2025-10-21 LTS', 21),
        ('java version "17.0.17" 2025-10-21 LTS', 17),
        ('java version "1.8.0_452"', 8),
        ("unrecognised output", 0),
    ],
)
def test_java_version_detection(monkeypatch, output, expected):
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=output)),
    )
    assert BroadcasterManager._java_major("java") == expected


def test_old_path_java_uses_cached_21(manager, monkeypatch):
    java = manager.data_folder / "jre-21/bin/java.exe"
    java.parent.mkdir(parents=True)
    java.touch()
    monkeypatch.setattr(
        "endstone_broadcaster.manager.platform.system", lambda: "Windows"
    )
    monkeypatch.setattr(
        "endstone_broadcaster.manager.shutil.which", lambda _: "old-java"
    )
    monkeypatch.setattr(
        manager, "_java_major", lambda candidate: 17 if candidate == "old-java" else 21
    )
    assert manager.get_java() == str(java)


def test_downloads_java_21_instead_of_reusing_old_portable_runtime(
    manager, monkeypatch
):
    old_java = manager.data_folder / "jre/bin/java.exe"
    old_java.parent.mkdir(parents=True)
    old_java.touch()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as runtime:
        runtime.writestr("jdk-21-jre/bin/java.exe", b"runtime-fixture")
    monkeypatch.setattr(
        "endstone_broadcaster.manager.platform.system", lambda: "Windows"
    )
    monkeypatch.setattr(
        "endstone_broadcaster.manager.platform.machine", lambda: "AMD64"
    )
    monkeypatch.setattr("endstone_broadcaster.manager.shutil.which", lambda _: None)
    monkeypatch.setattr(
        manager, "_java_major", lambda candidate: 17 if candidate == old_java else 21
    )
    requests = []

    def download(request, timeout):
        requests.append(request.full_url)
        return io.BytesIO(archive.getvalue())

    monkeypatch.setattr("endstone_broadcaster.manager.urllib.request.urlopen", download)
    java = manager.get_java()
    assert java == str(manager.data_folder / "jre-21/bin/java.exe")
    assert "/latest/21/ga/windows/x64/jre/" in requests[0]
    assert old_java.exists()
    assert not list(manager.data_folder.glob("jre-install-*"))


def fake_release(monkeypatch, jar_bytes, digest=None, tag="160", on_download=None):
    release = {
        "tag_name": tag,
        "assets": [
            {
                "name": "MCXboxBroadcastStandalone.jar",
                "browser_download_url": "https://example.invalid/broadcaster.jar",
                "digest": digest or "sha256:" + hashlib.sha256(jar_bytes).hexdigest(),
            }
        ],
    }

    def urlopen(request, timeout):
        if request.full_url.endswith("releases/latest"):
            return io.BytesIO(json.dumps(release).encode())
        if on_download:
            on_download()
        return io.BytesIO(jar_bytes)

    monkeypatch.setattr("endstone_broadcaster.manager.urllib.request.urlopen", urlopen)


def jar_fixture():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as jar:
        jar.writestr("META-INF/MANIFEST.MF", "Main-Class: Example\n")
    return output.getvalue()


def test_update_migrates_config_before_restarting(manager, monkeypatch):
    manager.jar_path.write_bytes(b"old-jar")
    manager.version_file.write_text("159", encoding="utf-8")
    manager.config_path.write_text(
        "session:\n  session-info:\n    ip: 203.0.113.1\n    port: 19132\n",
        encoding="utf-8",
    )
    manager.proc = Mock()
    steps = []

    def kill():
        steps.append("kill")
        manager.proc = None

    def spawn():
        config = manager.config_path.read_text(encoding="utf-8")
        assert "config-version: 7" in config
        assert "remote-address: 127.0.0.1" in config
        assert manager._local_version() == "160"
        steps.append("spawn")

    monkeypatch.setattr(manager, "_kill_process", kill)
    monkeypatch.setattr(manager, "_spawn_process", spawn)
    monkeypatch.setattr("endstone_broadcaster.manager.read_properties", lambda _: {})
    jar = jar_fixture()
    fake_release(monkeypatch, jar)
    manager.check_for_updates()
    assert steps == ["kill", "spawn"]
    assert manager.jar_path.read_bytes() == jar
    assert manager.config_path.with_name("config.yml.pre-v7.bak").exists()
    assert not list(manager.data_folder.glob("*.tmp"))


@pytest.mark.parametrize(
    ("jar", "digest"), [(b"not-a-jar", None), (jar_fixture(), "sha256:bad")]
)
def test_invalid_download_keeps_installed_jar_and_running_process(
    manager, monkeypatch, jar, digest
):
    manager.jar_path.write_bytes(b"installed-jar")
    manager.version_file.write_text("160", encoding="utf-8")
    process = manager.proc = Mock()
    kill = Mock()
    monkeypatch.setattr(manager, "_kill_process", kill)
    fake_release(monkeypatch, jar, digest=digest, tag="161")
    manager.check_for_updates()
    assert manager.proc is process
    assert manager.jar_path.read_bytes() == b"installed-jar"
    assert manager._local_version() == "160"
    kill.assert_not_called()
    assert not list(manager.data_folder.glob("*.tmp"))


def test_stop_during_download_does_not_install_or_spawn(manager, monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(manager, "_spawn_process", spawn)
    fake_release(monkeypatch, jar_fixture(), on_download=manager.stop)
    manager.check_for_updates()
    spawn.assert_not_called()
    assert not manager.jar_path.exists()
    assert not manager.config_path.exists()
    assert not list(manager.data_folder.glob("*.tmp"))


def test_initial_download_runs_off_the_server_thread(manager, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def java():
        entered.set()
        release.wait(timeout=2)
        return "java"

    monkeypatch.setattr(manager, "get_java", java)
    update = Mock()
    spawn = Mock()
    monkeypatch.setattr(manager, "check_for_updates", update)
    monkeypatch.setattr(manager, "_spawn_process", spawn)
    manager.start()
    assert entered.wait(timeout=2)
    assert manager.worker_thread.is_alive()
    manager.stop()
    release.set()
    manager.worker_thread.join(timeout=2)
    assert not manager.worker_thread.is_alive()
    update.assert_not_called()
    spawn.assert_not_called()


def test_monitor_leaves_healthy_jvm_running(manager, monkeypatch):
    process = manager.proc = Mock()
    process.poll.return_value = None
    event = Mock()
    event.wait.side_effect = [False, True]
    event.is_set.return_value = False
    manager._stopped = event
    kill, spawn = Mock(), Mock()
    monkeypatch.setattr(manager, "_kill_process", kill)
    monkeypatch.setattr(manager, "_spawn_process", spawn)
    manager._monitor_loop()
    kill.assert_not_called()
    spawn.assert_not_called()


def test_monitor_restarts_exited_jvm(manager, monkeypatch):
    manager.proc = Mock()
    manager.proc.poll.return_value = 1
    event = Mock()
    event.wait.side_effect = [False, True]
    event.is_set.return_value = False
    manager._stopped = event
    kill, setup, spawn = Mock(), Mock(), Mock()
    monkeypatch.setattr(manager, "_kill_process", kill)
    monkeypatch.setattr(manager, "setup_config", setup)
    monkeypatch.setattr(manager, "_spawn_process", spawn)
    manager._monitor_loop()
    kill.assert_called_once()
    setup.assert_called_once()
    spawn.assert_called_once()


def test_tail_preserves_auth_url_and_captures_its_own_process(manager):
    process = SimpleNamespace(
        stdout=io.StringIO(
            "[12:34:56 INFO] To sign in, use a web browser to open the page https://www.microsoft.com/link and enter the code TEST to authenticate.\n"
        )
    )
    manager.proc = None
    manager.tail(process)
    assert "https://www.microsoft.com/link" in manager.logger.warning.call_args.args[0]


def test_shutdown_waits_for_force_killed_process(manager):
    process = manager.proc = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired("java", 5),
        subprocess.TimeoutExpired("java", 5),
        0,
    ]
    manager.stop()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 3
    assert manager.proc is None


def test_invalid_config_during_update_does_not_interrupt_live_helper(
    manager, monkeypatch
):
    manager.jar_path.write_bytes(b"installed-jar")
    manager.version_file.write_text("160", encoding="utf-8")
    manager.config_path.write_text("session: [broken]", encoding="utf-8")
    process = manager.proc = Mock()
    kill = Mock()
    monkeypatch.setattr(manager, "_kill_process", kill)
    fake_release(monkeypatch, jar_fixture(), tag="161")
    manager.check_for_updates()
    kill.assert_not_called()
    assert manager.proc is process
    assert manager.jar_path.read_bytes() == b"installed-jar"
    assert manager.config_path.read_text(encoding="utf-8") == "session: [broken]"


def test_bootstrap_refuses_cached_pre_26_60_jar_when_update_is_unavailable(
    manager, monkeypatch
):
    manager.jar_path.write_bytes(b"old-jar")
    manager.version_file.write_text("159", encoding="utf-8")
    monkeypatch.setattr(manager, "get_java", lambda: "java21")
    monkeypatch.setattr(manager, "check_for_updates", Mock())
    spawn = Mock()
    monkeypatch.setattr(manager, "_spawn_process", spawn)
    manager._bootstrap()
    spawn.assert_not_called()
    assert manager.running is False
    assert "build 160+" in manager.logger.error.call_args.args[0]


def test_empty_existing_config_gets_backed_up_and_initialized(tmp_path):
    from endstone_broadcaster.config import sync_config

    path = tmp_path / "config.yml"
    path.write_text("# empty config\n", encoding="utf-8")
    original = path.read_bytes()
    config = sync_config(path, {}, "127.0.0.1", 19132)
    assert config["config-version"] == 7
    assert path.with_name("config.yml.pre-v7.bak").read_bytes() == original
