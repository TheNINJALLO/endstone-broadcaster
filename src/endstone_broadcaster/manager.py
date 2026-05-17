import os
import sys
import json
import shutil
import urllib.request
import subprocess
import threading
import platform
from pathlib import Path

RESTART_INTERVAL = 900  # 15 minutes

class BroadcasterManager:
    def __init__(self, data_folder, logger, server_ip, server_port):
        self.data_folder = data_folder
        self.logger = logger
        self.ip = server_ip
        self.port = server_port
        
        self.github_jar_name = "MCXboxBroadcastStandalone.jar"
        self.local_jar_name = "endstone-broadcaster.jar"
        self.jar_path = self.data_folder / self.local_jar_name
        self.config_path = self.data_folder / "config.yml"
        
        self.java_bin = None
        self.proc = None
        self.running = False
        self.tail_thread = None
        self.restart_thread = None

    def get_java(self):
        # check path first
        if shutil.which("java"):
            return "java"
            
        jre_dir = self.data_folder / "jre"
        
        sys_os = platform.system().lower()
        sys_arch = platform.machine().lower()
        
        if sys_os == "windows":
            os_name = "windows"
            ext = "zip"
            local_java = jre_dir / "bin" / "java.exe"
        elif sys_os == "darwin":
            os_name = "mac"
            ext = "tar.gz"
            local_java = jre_dir / "Contents" / "Home" / "bin" / "java"
        else:
            os_name = "linux"
            ext = "tar.gz"
            local_java = jre_dir / "bin" / "java"
            
        if sys_arch in ["amd64", "x86_64"]:
            arch = "x64"
        elif sys_arch in ["aarch64", "arm64"]:
            arch = "aarch64"
        else:
            arch = "x64"
            
        if local_java.exists():
            return str(local_java)
            
        self.logger.info(f"no java found. pulling {os_name}-{arch} jre...")
        jre_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            url = f"https://api.adoptium.net/v3/binary/latest/17/ga/{os_name}/{arch}/jre/hotspot/normal/eclipse?project=jdk"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            archive_path = self.data_folder / f"jre.{ext}"
            
            with urllib.request.urlopen(req) as resp, open(archive_path, 'wb') as out:
                shutil.copyfileobj(resp, out)
                
            self.logger.info("extracting jre...")
            
            if ext == "zip":
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(jre_dir)
            else:
                import tarfile
                with tarfile.open(archive_path, 'r:gz') as tf:
                    tf.extractall(jre_dir)
                    
            # move contents up
            subdirs = [d for d in jre_dir.iterdir() if d.is_dir()]
            if subdirs:
                main = subdirs[0]
                for item in main.iterdir():
                    shutil.move(str(item), str(jre_dir / item.name))
                main.rmdir()
                
            archive_path.unlink()
            
            if os_name in ["linux", "mac"]:
                os.chmod(local_java, 0o755)
                
            self.logger.info("jre installed")
            return str(local_java)
            
        except Exception as e:
            self.logger.error(f"jre install failed: {e}")
            return None

    def pull_jar(self):
        if self.jar_path.exists():
            return True
            
        self.logger.info("fetching standalone jar...")
        try:
            url = "https://api.github.com/repos/MCXboxBroadcast/Broadcaster/releases/latest"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read().decode())
                
            dl_url = None
            for asset in data.get("assets", []):
                if asset["name"] == self.github_jar_name:
                    dl_url = asset["browser_download_url"]
                    break
                    
            if not dl_url:
                self.logger.error("couldn't find jar in latest release")
                return False
                
            urllib.request.urlretrieve(dl_url, str(self.jar_path))
            return True
        except Exception as e:
            self.logger.error(f"failed to download jar: {e}")
            return False

    def setup_config(self):
        import re
        
        host_name = "Endstone Server"
        world_name = "World"
        server_port = self.port
        public_ip = "127.0.0.1"
        
        # auto-detect public ip
        try:
            req = urllib.request.Request("https://api.ipify.org?format=text", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as r:
                public_ip = r.read().decode('utf-8').strip()
        except Exception:
            self.logger.warning("couldn't auto-detect public ip, defaulting to 127.0.0.1")
            
        props = Path.cwd() / "server.properties"
        if props.exists():
            for line in props.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("server-name="):
                    host_name = line.split("=", 1)[1].strip()
                elif line.startswith("level-name="):
                    world_name = line.split("=", 1)[1].strip()
                elif line.startswith("server-port="):
                    try:
                        server_port = int(line.split("=", 1)[1].strip())
                    except ValueError:
                        pass
                        
        if self.config_path.exists():
            # dynamically patch the existing config
            cfg = self.config_path.read_text(encoding="utf-8")
            cfg = re.sub(r'host-name:\s*[^\n]+', f'host-name: "{host_name}"', cfg)
            cfg = re.sub(r'world-name:\s*[^\n]+', f'world-name: "{world_name}"', cfg)
            cfg = re.sub(r'ip:\s*[^\n]+', f'ip: "{public_ip}"', cfg)
            cfg = re.sub(r'port:\s*\d+', f'port: {server_port}', cfg)
            # ensure query-server stays disabled so the jar uses our values
            cfg = re.sub(r'query-server:\s*(true|false)', 'query-server: false', cfg)
            self.config_path.write_text(cfg, encoding="utf-8")
            self.logger.info(f"patched config (IP: {public_ip}:{server_port})")
            return
            
        cfg = f"""session:
  update-interval: 30
  query-server: false
  web-query-fallback: false
  config-fallback: false
  session-info:
    host-name: "{host_name}"
    world-name: "{world_name}"
    players: 0
    max-players: 20
    ip: "{public_ip}"
    port: {server_port}
friend-sync:
  update-interval: 60
  auto-follow: true
  auto-unfollow: true
  initial-invite: true
  expiry:
    enabled: true
    days: 15
    check: 1800
debug-mode: false
"""
        self.config_path.write_text(cfg, encoding="utf-8")
        self.logger.info("created default config")

    def start(self):
        self.java_bin = self.get_java()
        if not self.java_bin:
            self.logger.error("can't start broadcaster without java")
            return
            
        self.data_folder.mkdir(parents=True, exist_ok=True)
        
        if not self.pull_jar():
            return
            
        self.setup_config()
        self._spawn_process()

        # start the auto-restart cycle
        self.restart_thread = threading.Thread(target=self._restart_loop, daemon=True)
        self.restart_thread.start()

    def _spawn_process(self):
        """Launch the java process and tail its output."""
        self.logger.info("spinning up java process...")
        try:
            self.proc = subprocess.Popen(
                [self.java_bin, "-jar", self.local_jar_name],
                cwd=str(self.data_folder),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            self.running = True
            
            self.tail_thread = threading.Thread(target=self.tail, daemon=True)
            self.tail_thread.start()
        except Exception as e:
            self.logger.error(f"proc start failed: {e}")

    def _kill_process(self):
        """Kill the current java process without clearing self.running."""
        if self.proc:
            try:
                if self.proc.stdin:
                    self.proc.stdin.write("exit\n")
                    self.proc.stdin.flush()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
            except Exception:
                pass
            finally:
                self.proc = None

        if self.tail_thread and self.tail_thread.is_alive():
            self.tail_thread.join(timeout=2.0)

    def _restart_loop(self):
        """Automatically restart the java process every RESTART_INTERVAL seconds."""
        while self.running:
            # sleep in small increments so stop() can break out quickly
            for _ in range(RESTART_INTERVAL):
                if not self.running:
                    return
                import time
                time.sleep(1)

            if not self.running:
                return

            self.logger.info("auto-restarting broadcaster...")
            self._kill_process()
            self.setup_config()
            self._spawn_process()

    def tail(self):
        if not self.proc or not self.proc.stdout:
            return

        try:
            while self.running:
                line = self.proc.stdout.readline()
                if not line and self.proc.poll() is not None:
                    break

                line = line.strip()
                if not line:
                    continue

                # strip java log prefixes like "[14:58:24] [main/INFO]: "
                clean = line
                if ": " in clean:
                    clean = clean.split(": ", 1)[-1]

                if "To sign in, use a web browser to open the page" in line:
                    self.logger.warning("=======================================================")
                    self.logger.warning("--- XBOX AUTH REQUIRED ---")
                    self.logger.warning(clean)
                    self.logger.warning("=======================================================")
                elif "Successfully authenticated as" in line:
                    user_info = clean.split("Successfully authenticated as ")[-1]
                    self.logger.info("=======================================================")
                    self.logger.info(f"Broadcaster Logged In: {user_info}")
                    self.logger.info("=======================================================")
                elif "Started broadcasting" in line:
                    self.logger.info("broadcasting online")
                else:
                    self.logger.info(f"[Java] {clean}")
        except Exception as e:
            self.logger.error(f"tail thread error: {e}")
        finally:
            rc = self.proc.poll() if self.proc else None
            if rc is not None and rc != 0:
                self.logger.warning(f"java process exited with code {rc}")

    def stop(self):
        self.running = False
        self._kill_process()
