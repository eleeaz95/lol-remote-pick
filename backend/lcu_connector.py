"""League Client (LCU) discovery and credential management."""

import base64
import os
import re
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Set
import logging

try:
    import psutil
except ImportError:
    psutil = None

try:
    import winreg
except ImportError:
    winreg = None
logger = logging.getLogger(__name__)


@dataclass
class LCUCredentials:
    """Connection credentials and URLs for the League Client."""
    port: int
    password: str
    protocol: str = "https"
    pid: int = 0
    process_name: str = "LeagueClient"

    @property
    def base_url(self) -> str:
        """HTTP base URL for LCU REST API."""
        return f"{self.protocol}://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        """WebSocket URL for LCU event stream."""
        ws_proto = "wss" if self.protocol == "https" else "ws"
        return f"{ws_proto}://127.0.0.1:{self.port}/"

    @property
    def auth_header(self) -> str:
        """HTTP Authorization header value (Basic Auth)."""
        token = base64.b64encode(f"riot:{self.password}".encode("utf-8")).decode("utf-8")
        return f"Basic {token}"

    @property
    def auth_tuple(self) -> tuple[str, str]:
        """Basic Auth tuple (username, password)."""
        return ("riot", self.password)


class LCUConnector:
    """Discovers and parses League Client connection information."""

    COMMON_PATHS: List[str] = [
        # Windows default paths
        r"C:\Riot Games\League of Legends\lockfile",
        r"D:\Riot Games\League of Legends\lockfile",
        r"E:\Riot Games\League of Legends\lockfile",
        r"F:\Riot Games\League of Legends\lockfile",
        r"G:\Riot Games\League of Legends\lockfile",
        r"C:\Program Files\Riot Games\League of Legends\lockfile",
        r"C:\Program Files (x86)\Riot Games\League of Legends\lockfile",
        r"D:\Program Files\Riot Games\League of Legends\lockfile",
        r"D:\Program Files (x86)\Riot Games\League of Legends\lockfile",
        # macOS paths
        os.path.expanduser("~/Library/Application Support/Riot Games/League of Legends/lockfile"),
        "/Applications/League of Legends.app/Contents/LoL/lockfile",
        # Linux / Wine paths
        os.path.expanduser("~/.wine/drive_c/Riot Games/League of Legends/lockfile"),
        os.path.expanduser("~/.local/share/wineprefixes/league/drive_c/Riot Games/League of Legends/lockfile"),
    ]

    def __init__(self, custom_path: Optional[str] = None):
        self.custom_path = custom_path
        self._cached_credentials: Optional[LCUCredentials] = None
        self._cached_lockfile_path: Optional[Path] = None
        self._cached_lockfile_mtime: Optional[float] = None

    def is_alive(self) -> bool:
        """Fast microsecond check to verify if the cached client process or lockfile is still alive."""
        if self._cached_credentials is None:
            return False

        # 1. Microsecond PID existence check via psutil
        if self._cached_credentials.pid > 0 and psutil is not None:
            try:
                if psutil.pid_exists(self._cached_credentials.pid):
                    return True
            except Exception:
                pass

        # 2. Fast stat check on cached lockfile path
        if self._cached_lockfile_path is not None:
            try:
                if self._cached_lockfile_path.is_file():
                    return True
            except Exception:
                pass

        return False

    def _find_lockfile_from_riot_metadata(self) -> Optional[Path]:
        """Discover League install directory from Riot Client metadata files on Windows."""
        search_roots = []
        program_data = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE")
        if program_data:
            search_roots.append(Path(program_data) / "Riot Games")
        search_roots.append(Path(r"C:\ProgramData\Riot Games"))

        for root in search_roots:
            if not root.is_dir():
                continue

            # 1. Check Metadata folders (league_of_legends.live, league_of_legends.pbe, etc.)
            metadata_dir = root / "Metadata"
            if metadata_dir.is_dir():
                try:
                    for entry in metadata_dir.iterdir():
                        if entry.is_dir() and "league_of_legends" in entry.name.lower():
                            for yaml_file in entry.glob("*.yaml"):
                                try:
                                    text = yaml_file.read_text(encoding="utf-8", errors="ignore")
                                    match = re.search(
                                        r'product_install_full_path:\s*["\']?([^"\']+)["\']?',
                                        text,
                                    )
                                    if match:
                                        install_path = Path(match.group(1).strip())
                                        lock_file = install_path / "lockfile"
                                        if lock_file.is_file():
                                            return lock_file
                                        # Check subdirectory / parent
                                        if (install_path / "League of Legends" / "lockfile").is_file():
                                            return install_path / "League of Legends" / "lockfile"
                                except Exception:
                                    continue
                except Exception:
                    pass

            # 2. Check RiotClientInstalls.json
            installs_json = root / "RiotClientInstalls.json"
            if installs_json.is_file():
                try:
                    text = installs_json.read_text(encoding="utf-8", errors="ignore")
                    paths = re.findall(r'["\']([a-zA-Z]:\\[^"\']+)["\']', text)
                    for p_str in paths:
                        p = Path(p_str)
                        if "league" in p_str.lower():
                            if (p / "lockfile").is_file():
                                return p / "lockfile"
                            if (p.parent / "lockfile").is_file():
                                return p.parent / "lockfile"
                except Exception:
                    pass

        return None

    def _find_lockfile_from_windows_registry(self) -> Optional[Path]:
        """Discover League install directory from Windows Registry."""
        if not winreg or sys.platform != "win32":
            return None

        reg_queries = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Riot Games, Inc\League of Legends", "Location"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Riot Games, Inc\League of Legends", "Location"),
            (winreg.HKEY_CURRENT_USER, r"Software\Riot Games\League of Legends", "Location"),
            (winreg.HKEY_CURRENT_USER, r"Software\Riot Games\League of Legends", "Path"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game league_of_legends.live", "InstallLocation"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game league_of_legends.live", "InstallLocation"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game league_of_legends.live", "InstallLocation"),
        ]

        for hive, subkey, val_name in reg_queries:
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, val_name)
                    if val and isinstance(val, str):
                        p = Path(val)
                        if (p / "lockfile").is_file():
                            return p / "lockfile"
                        if p.is_file() and p.name == "lockfile":
                            return p
            except Exception:
                continue

        return None

    def _find_lockfile_from_all_drives(self) -> Optional[Path]:
        """Scan all available Windows drive letters for common League installation folders."""
        if sys.platform != "win32":
            return None

        candidate_subdirs = [
            r"Riot Games\League of Legends",
            r"Program Files\Riot Games\League of Legends",
            r"Program Files (x86)\Riot Games\League of Legends",
            r"Games\Riot Games\League of Legends",
            r"Games\League of Legends",
            r"League of Legends",
            r"LoL",
            r"Juegos\League of Legends",
            r"Jogos\League of Legends",
        ]

        # Scan common drive letters
        for letter in ["C", "D", "E", "F", "G", "H", "I", "J", "K", "X", "Y", "Z", "A", "B"]:
            drive_root = Path(f"{letter}:\\")
            if not drive_root.exists():
                continue
            for subdir in candidate_subdirs:
                lock_path = drive_root / subdir / "lockfile"
                if lock_path.is_file():
                    return lock_path

        return None

    def find_lockfile(self) -> Optional[Path]:
        """Search standard file paths, Riot metadata, registry, and process directory for the lockfile."""
        # 0. Check cached lockfile path first
        if self._cached_lockfile_path is not None and self._cached_lockfile_path.is_file():
            return self._cached_lockfile_path

        # 1. Custom path check
        if self.custom_path:
            p = Path(self.custom_path)
            if p.is_file() and p.name == "lockfile":
                self._cached_lockfile_path = p
                return p
            elif p.is_dir() and (p / "lockfile").is_file():
                lock_p = p / "lockfile"
                self._cached_lockfile_path = lock_p
                return lock_p

        # 2. Check standard paths list
        for path_str in self.COMMON_PATHS:
            p = Path(path_str)
            if p.is_file():
                self._cached_lockfile_path = p
                return p

        # 3. Check Riot Client Metadata (Windows universal)
        metadata_lockfile = self._find_lockfile_from_riot_metadata()
        if metadata_lockfile and metadata_lockfile.is_file():
            self._cached_lockfile_path = metadata_lockfile
            return metadata_lockfile

        # 4. Check Windows Registry
        reg_lockfile = self._find_lockfile_from_windows_registry()
        if reg_lockfile and reg_lockfile.is_file():
            self._cached_lockfile_path = reg_lockfile
            return reg_lockfile

        # 5. Check process directory via psutil if available
        if psutil:
            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if "leagueclient" in name:
                        exe_path = proc.info.get("exe")
                        if exe_path:
                            lockfile_path = Path(exe_path).parent / "lockfile"
                            if lockfile_path.is_file():
                                self._cached_lockfile_path = lockfile_path
                                return lockfile_path
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

        # 6. Scan all Windows drive letters
        drive_lockfile = self._find_lockfile_from_all_drives()
        if drive_lockfile and drive_lockfile.is_file():
            self._cached_lockfile_path = drive_lockfile
            return drive_lockfile

        return None

    def parse_lockfile_content(self, content: str) -> Optional[LCUCredentials]:
        """Parse standard lockfile content (process:pid:port:password:protocol)."""
        try:
            parts = content.strip().split(":")
            if len(parts) >= 5:
                process_name = parts[0]
                pid = int(parts[1])
                port = int(parts[2])
                password = parts[3]
                protocol = parts[4]
                return LCUCredentials(
                    port=port,
                    password=password,
                    protocol=protocol,
                    pid=pid,
                    process_name=process_name
                )
        except Exception as e:
            logger.debug(f"Failed to parse lockfile content: {e}")
        return None

    def get_credentials_from_lockfile(self, lockfile_path: Optional[Path] = None) -> Optional[LCUCredentials]:
        """Read lockfile and parse credentials with stat/mtime caching."""
        path = lockfile_path or self.find_lockfile()
        if not path or not path.is_file():
            if path == self._cached_lockfile_path:
                self._cached_lockfile_path = None
                self._cached_lockfile_mtime = None
            return None

        try:
            # Check cached mtime if path matches
            stat_result = path.stat()
            mtime = stat_result.st_mtime
            if (
                path == self._cached_lockfile_path
                and self._cached_credentials is not None
                and mtime == self._cached_lockfile_mtime
            ):
                return self._cached_credentials

            # Read safely (lockfile might be locked by LoL client)
            content = path.read_text(encoding="utf-8", errors="ignore").strip()
            if content:
                creds = self.parse_lockfile_content(content)
                if creds:
                    self._cached_credentials = creds
                    self._cached_lockfile_path = path
                    self._cached_lockfile_mtime = mtime
                    return creds
        except (OSError, IOError, PermissionError) as e:
            logger.debug(f"Could not read lockfile at {path}: {e}")
        return None

    def get_credentials_from_process(self) -> Optional[LCUCredentials]:
        """Extract port and auth token directly from running LeagueClientUx process command line."""
        # 1. Primary inspection via psutil
        if psutil:
            for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if "leagueclientux" in name or "leagueclient" in name:
                        cmdline = proc.info.get("cmdline") or []
                        cmdline_str = " ".join(cmdline)

                        port_match = re.search(r"--app-port=([0-9]+)", cmdline_str)
                        token_match = re.search(r"--remoting-auth-token=([\w\-_]+)", cmdline_str)

                        if port_match and token_match:
                            port = int(port_match.group(1))
                            password = token_match.group(1)
                            pid = proc.info.get("pid", 0)
                            creds = LCUCredentials(
                                port=port,
                                password=password,
                                protocol="https",
                                pid=pid,
                                process_name="LeagueClientUx",
                            )
                            self._cached_credentials = creds
                            return creds

                        # If cmdline didn't contain tokens, check if install-directory or exe has lockfile
                        dir_match = re.search(r'--install-directory=([^"\s]+|"[^"]+")', cmdline_str)
                        if dir_match:
                            inst_dir = dir_match.group(1).strip('"')
                            lock_p = Path(inst_dir) / "lockfile"
                            if lock_p.is_file():
                                creds = self.get_credentials_from_lockfile(lock_p)
                                if creds:
                                    return creds

                        exe_path = proc.info.get("exe")
                        if exe_path:
                            lock_p = Path(exe_path).parent / "lockfile"
                            if lock_p.is_file():
                                creds = self.get_credentials_from_lockfile(lock_p)
                                if creds:
                                    return creds
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

        # 2. Windows fallback via WMIC or PowerShell command line query (useful when psutil has permission limits)
        if sys.platform == "win32":
            creds = self._get_credentials_from_wmi()
            if creds:
                self._cached_credentials = creds
                return creds

        return None

    def _get_credentials_from_wmi(self) -> Optional[LCUCredentials]:
        """Windows fallback to query LeagueClientUx process command line using WMIC / PowerShell."""
        try:
            # Try WMIC first (fast command-line query on Windows)
            cmd = ["wmic", "process", "where", "name like 'LeagueClientUx%'", "get", "CommandLine,ProcessId", "/format:csv"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0 and result.stdout:
                output = result.stdout
                port_match = re.search(r"--app-port=([0-9]+)", output)
                token_match = re.search(r"--remoting-auth-token=([\w\-_]+)", output)
                if port_match and token_match:
                    port = int(port_match.group(1))
                    password = token_match.group(1)
                    pid_match = re.search(r",(\d+)\s*$", output, re.MULTILINE)
                    pid = int(pid_match.group(1)) if pid_match else 0
                    return LCUCredentials(
                        port=port,
                        password=password,
                        protocol="https",
                        pid=pid,
                        process_name="LeagueClientUx",
                    )
        except Exception as e:
            logger.debug(f"WMIC process lookup fallback failed: {e}")

        try:
            # Try PowerShell Get-CimInstance fallback
            ps_cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"name like 'LeagueClientUx%'\" | Select-Object -ExpandProperty CommandLine",
            ]
            result = subprocess.run(
                ps_cmd,
                capture_output=True,
                text=True,
                timeout=3.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0 and result.stdout:
                output = result.stdout
                port_match = re.search(r"--app-port=([0-9]+)", output)
                token_match = re.search(r"--remoting-auth-token=([\w\-_]+)", output)
                if port_match and token_match:
                    port = int(port_match.group(1))
                    password = token_match.group(1)
                    return LCUCredentials(
                        port=port,
                        password=password,
                        protocol="https",
                        pid=0,
                        process_name="LeagueClientUx",
                    )
        except Exception as e:
            logger.debug(f"PowerShell process lookup fallback failed: {e}")

        return None

    def get_credentials(self, force_refresh: bool = False) -> Optional[LCUCredentials]:
        """Get LCU credentials via fast alive check first, then lockfile, then process fallback."""
        if not force_refresh and self._cached_credentials is not None:
            if self.is_alive():
                return self._cached_credentials
            else:
                self._cached_credentials = None

        # 1. Lockfile check (extremely fast <1ms compared to process scanning)
        creds = self.get_credentials_from_lockfile()
        if creds:
            self._cached_credentials = creds
            return creds

        # 2. Process inspection fallback (only when lockfile is not found)
        creds = self.get_credentials_from_process()
        if creds:
            self._cached_credentials = creds
            return creds

        return None

    def is_running(self) -> bool:
        """Check if League Client process or valid lockfile is currently active."""
        return self.is_alive() or (self.get_credentials() is not None)
