import hashlib
import json
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from endstone_broadcaster.config import read_properties, sync_config

JAVA_VERSION = 21
MIN_BROADCASTER_BUILD = 160
UPDATE_INTERVAL = 43200
MONITOR_INTERVAL = 30
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
USER_AGENT = {"User-Agent": "endstone-broadcaster"}


class BroadcasterManager:
    def __init__(self, data_folder, logger, server_ip, server_port):
        self.data_folder = Path(data_folder).resolve()
        self.logger = logger
        self.ip = server_ip
        self.port = server_port
        self.github_jar_name = "MCXboxBroadcastStandalone.jar"
        self.local_jar_name = "endstone-broadcaster.jar"
        self.jar_path = self.data_folder / self.local_jar_name
        self.config_path = self.data_folder / "config.yml"
        self.version_file = self.data_folder / "jar_version.txt"
        self.java_bin = None
        self.proc = None
        self.running = False
        self.tail_thread = None
        self.worker_thread = None
        self.monitor_thread = None
        self.update_thread = None
        self._stopped = threading.Event()
        self._lock = threading.RLock()

    @staticmethod
    def _java_major(executable):
        try:
            result = subprocess.run(
                [str(executable), "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
                check=False,
                creationflags=NO_WINDOW,
            )
            match = re.search(r'version\s+"(?:1\.)?(\d+)', result.stdout)
            return int(match.group(1)) if result.returncode == 0 and match else 0
        except (OSError, subprocess.SubprocessError):
            return 0

    def get_java(self):
        system_java = shutil.which("java")
        if system_java:
            if self._java_major(system_java) >= JAVA_VERSION:
                return system_java
            self.logger.warning(
                "Java on PATH is older than 21 or cannot run; checking the portable runtime"
            )

        sys_os = platform.system().lower()
        os_name = {"windows": "windows", "linux": "linux", "darwin": "mac"}.get(sys_os)
        executable = "java.exe" if sys_os == "windows" else "java"
        relative_java = (
            Path("Contents/Home/bin/java")
            if sys_os == "darwin"
            else Path("bin") / executable
        )
        for directory in ("jre-21", "jre"):
            candidate = self.data_folder / directory / relative_java
            if candidate.exists() and self._java_major(candidate) >= JAVA_VERSION:
                return str(candidate)

        arch = {
            "amd64": "x64",
            "x86_64": "x64",
            "arm64": "aarch64",
            "aarch64": "aarch64",
        }.get(platform.machine().lower())
        if not os_name or not arch:
            self.logger.error(
                "Install Java 21 or newer on PATH for this operating system/architecture"
            )
            return None

        self.data_folder.mkdir(parents=True, exist_ok=True)
        extension = "zip" if sys_os == "windows" else "tar.gz"
        url = f"https://api.adoptium.net/v3/binary/latest/21/ga/{os_name}/{arch}/jre/hotspot/normal/eclipse?project=jdk"
        try:
            self.logger.info(f"Installing a Java 21 runtime for {os_name}-{arch}...")
            with tempfile.TemporaryDirectory(
                prefix="jre-install-", dir=self.data_folder
            ) as staging:
                staging = Path(staging)
                archive = staging / f"jre.{extension}"
                request = urllib.request.Request(url, headers=USER_AGENT)
                with (
                    urllib.request.urlopen(request, timeout=60) as response,
                    archive.open("wb") as output,
                ):
                    shutil.copyfileobj(response, output)
                if self._stopped.is_set():
                    return None
                unpacked = staging / "unpacked"
                unpacked.mkdir()
                if extension == "zip":
                    with zipfile.ZipFile(archive) as runtime:
                        runtime.extractall(unpacked)
                else:
                    with tarfile.open(archive, "r:gz") as runtime:
                        # Extraction filters are available in Python 3.11.8+.
                        if not hasattr(tarfile, "data_filter"):
                            raise RuntimeError(
                                "Use Python 3.11.8+ for automatic JRE extraction, or install Java 21 on PATH"
                            )
                        runtime.extractall(unpacked, filter="data")
                candidates = list(unpacked.glob(f"*/{relative_java.as_posix()}"))
                if len(candidates) != 1:
                    raise RuntimeError(
                        "Downloaded archive does not contain the expected Java runtime"
                    )
                source_java = candidates[0]
                if sys_os != "windows":
                    source_java.chmod(source_java.stat().st_mode | 0o111)
                if self._java_major(source_java) < JAVA_VERSION:
                    raise RuntimeError("Downloaded runtime does not provide Java 21")
                runtime_root = source_java.parents[len(relative_java.parts) - 1]
                destination = self.data_folder / "jre-21"
                shutil.copytree(
                    runtime_root, destination, dirs_exist_ok=True, symlinks=True
                )
            local_java = destination / relative_java
            if self._java_major(local_java) < JAVA_VERSION:
                raise RuntimeError("Installed Java runtime cannot run")
            self.logger.info("Java 21 runtime installed")
            return str(local_java)
        except Exception as error:
            self.logger.error(f"Java 21 installation failed: {error}")
            return None

    def _local_version(self):
        return (
            self.version_file.read_text(encoding="utf-8").strip()
            if self.version_file.exists()
            else ""
        )

    def _jar_is_supported(self):
        version = self._local_version()
        return (
            self.jar_path.is_file()
            and version.isdecimal()
            and int(version) >= MIN_BROADCASTER_BUILD
        )

    def check_for_updates(self):
        self.logger.info("Checking for broadcaster updates...")
        temporary = None
        try:
            request = urllib.request.Request(
                "https://api.github.com/repos/MCXboxBroadcast/Broadcaster/releases/latest",
                headers=USER_AGENT,
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                release = json.load(response)
            tag = release.get("tag_name", "")
            if not tag.isdecimal() or int(tag) < MIN_BROADCASTER_BUILD:
                raise RuntimeError(
                    "Minecraft 26.60 requires MCXboxBroadcast build 160 or newer"
                )
            asset = next(
                (
                    asset
                    for asset in release.get("assets", [])
                    if asset["name"] == self.github_jar_name
                ),
                None,
            )
            if not asset:
                raise RuntimeError("Standalone JAR is missing from the latest release")
            if self.jar_path.exists() and self._local_version() == tag:
                self.logger.info(f"Broadcaster is up to date (build {tag})")
                return
            self.data_folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.data_folder, suffix=".jar.tmp", delete=False
            ) as output:
                temporary = Path(output.name)
                request = urllib.request.Request(
                    asset["browser_download_url"], headers=USER_AGENT
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    shutil.copyfileobj(response, output)
            digest = asset.get("digest")
            if digest and digest.startswith("sha256:"):
                with temporary.open("rb") as source:
                    actual = hashlib.file_digest(source, "sha256").hexdigest()
                if actual != digest.split(":", 1)[1]:
                    raise RuntimeError(
                        "Standalone JAR checksum does not match the release"
                    )
            with zipfile.ZipFile(temporary) as jar:
                if (
                    "META-INF/MANIFEST.MF" not in jar.namelist()
                    or jar.testzip() is not None
                ):
                    raise RuntimeError("Downloaded Standalone JAR is invalid")
            with self._lock:
                if self._stopped.is_set():
                    return
                # Reject invalid configuration before interrupting a live helper.
                self.setup_config()
                was_running = self.proc is not None
                if was_running:
                    self._kill_process()
                try:
                    temporary.replace(self.jar_path)
                    version_tmp = self.version_file.with_suffix(".tmp")
                    version_tmp.write_text(tag, encoding="utf-8")
                    version_tmp.replace(self.version_file)
                    self.logger.info(f"Broadcaster updated to build {tag}")
                finally:
                    if was_running and not self._stopped.is_set():
                        self._spawn_process()
        except Exception as error:
            self.logger.error(f"Broadcaster update failed: {error}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def setup_config(self):
        self.data_folder.mkdir(parents=True, exist_ok=True)
        properties = read_properties(Path.cwd() / "server.properties")
        config = sync_config(self.config_path, properties, self.ip, self.port)
        if properties.get("transport", "nethernet").lower() != "nethernet":
            self.logger.error(
                "Minecraft 26.60 requires transport=nethernet in server.properties; update it and restart the server"
            )
        session = config["session"]
        self.logger.info(
            f"NetherNet relay backend: {session['remote-address']}:{session['remote-port']}"
        )

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            self._stopped.clear()
            self.worker_thread = threading.Thread(
                target=self._bootstrap, name="broadcaster-setup", daemon=True
            )
            self.worker_thread.start()

    def _bootstrap(self):
        try:
            self.data_folder.mkdir(parents=True, exist_ok=True)
            self.java_bin = self.get_java()
            if not self.java_bin or self._stopped.is_set():
                return
            self.check_for_updates()
            with self._lock:
                if self._stopped.is_set():
                    return
                if not self._jar_is_supported():
                    raise RuntimeError(
                        "Cannot start: download of MCXboxBroadcast build 160+ is required"
                    )
                self.setup_config()
                self._spawn_process()
                self.monitor_thread = threading.Thread(
                    target=self._monitor_loop, name="broadcaster-monitor", daemon=True
                )
                self.update_thread = threading.Thread(
                    target=self._update_loop, name="broadcaster-updates", daemon=True
                )
                self.monitor_thread.start()
                self.update_thread.start()
        except Exception as error:
            self.logger.error(f"Broadcaster startup failed: {error}")
        finally:
            if self.proc is None:
                self.running = False

    def _update_loop(self):
        while not self._stopped.wait(UPDATE_INTERVAL):
            self.check_for_updates()

    def _monitor_loop(self):
        # Upstream now rotates sessions and reconnects signaling itself. Keep a
        # healthy JVM alive, restarting only if it exits.
        while not self._stopped.wait(MONITOR_INTERVAL):
            with self._lock:
                if self._stopped.is_set():
                    return
                if self.proc is not None and self.proc.poll() is None:
                    continue
                self.logger.warning("Broadcaster exited; restarting the helper...")
                try:
                    self._kill_process()
                    self.setup_config()
                    self._spawn_process()
                except Exception as error:
                    self.logger.error(f"Broadcaster restart failed: {error}")

    def _spawn_process(self):
        if self._stopped.is_set():
            return
        self.logger.info("Starting MCXboxBroadcast with Java 21+...")
        self.proc = subprocess.Popen(
            [self.java_bin, "-jar", self.local_jar_name],
            cwd=str(self.data_folder),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=NO_WINDOW,
        )
        self.tail_thread = threading.Thread(
            target=self.tail, args=(self.proc,), name="broadcaster-output", daemon=True
        )
        self.tail_thread.start()

    def _kill_process(self):
        process = self.proc
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write("exit\n")
                    process.stdin.flush()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.proc = None
        if self.tail_thread and self.tail_thread is not threading.current_thread():
            self.tail_thread.join(timeout=2)
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()

    def tail(self, process):
        if process.stdout is None:
            return
        try:
            for line in process.stdout:
                clean = re.sub(r"^\[[^\]]+\](?: \[[^\]]+\])?:?\s*", "", line).strip()
                if not clean:
                    continue
                if "To sign in, use a web browser to open the page" in line:
                    self.logger.warning("--- XBOX AUTH REQUIRED ---")
                    self.logger.warning(clean)
                elif "Successfully authenticated as" in line:
                    self.logger.info(
                        f"Broadcaster logged in: {clean.split('Successfully authenticated as ', 1)[-1]}"
                    )
                else:
                    self.logger.info(f"[Java] {clean}")
        except (OSError, ValueError) as error:
            if not self._stopped.is_set():
                self.logger.error(f"Broadcaster output error: {error}")

    def stop(self):
        self._stopped.set()
        with self._lock:
            self.running = False
            self._kill_process()
