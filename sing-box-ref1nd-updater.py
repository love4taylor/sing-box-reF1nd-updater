#!/usr/bin/env python3
"""Update sing-box reF1nd builds from GitHub Releases."""

from __future__ import annotations

import argparse
import functools
import json
import os
import platform
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO = "reF1nd/sing-box-releases"
INSTALL_PATH = "/usr/local/bin/sing-box-ref1nd"
CRONET_LIB_PATH = "/usr/local/lib/cronet-go/"
USER_AGENT = "sing-box-reF1nd-updater/2.0"
CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "sing-box-ref1nd-updater",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

SERVICE_USER = "sing-box-ref1nd"
SERVICE_SHELL = "/usr/sbin/nologin"
SERVICE_STATE_DIR = "/var/lib/sing-box-ref1nd"
SERVICE_CONFIG_DIR = "/usr/local/etc/sing-box-ref1nd"
SERVICE_UNIT = "/etc/systemd/system/sing-box-ref1nd.service"
SERVICE_TEMPLATE = "/etc/systemd/system/sing-box-ref1nd@.service"

DEFAULT_SINGBOX_CONFIG = {
    "log": {"level": "info"},
    "dns": {
        "servers": [{"type": "tls", "tag": "google", "server": "8.8.8.8"}]
    },
    "inbounds": [
        {
            "type": "snell",
            "listen": "::",
            "listen_port": 0,
            "psk": "",
            "version": 5,
        }
    ],
    "outbounds": [{"type": "direct"}],
    "route": {"rules": [{"port": 53, "action": "hijack-dns"}]},
}

ASSET_RE = re.compile(
    r"^sing-box-(?P<version>.+?)-reF1nd(?P<rebuild>\.[0-9]+)?-linux-"
    r"(?P<arch>arm64|amd64v3|amd64)-(?P<build>purego|musl|glibc)\.tar\.gz$"
)
CURRENT_VERSION_RE = re.compile(r"sing-box\s+version\s+(?P<version>\S+)")
SEMVER_RE = re.compile(
    r"^(?P<major>\d+)"
    r"(?:\.(?P<minor>\d+))?"
    r"(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)
TESTING_RE = re.compile(r"\b(alpha|beta|rc)\b")


@dataclass(frozen=True)
class Asset:
    filename: str
    version: str
    arch: str
    build: str
    rebuild: int = 0
    download_url: str = ""
    release_url: str = ""

    def display_version(self) -> str:
        if self.rebuild:
            return f"{self.version}-reF1nd.{self.rebuild}"
        return self.version


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str, exit_code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def request_json(url: str, token: str | None = None) -> Any:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        if exc.code == 403 and "rate limit" in body.lower():
            fail(
                "GitHub API rate limit exceeded.\n"
                "  Provide a token via --token, $GITHUB_TOKEN, or the config file."
            )
        if exc.code == 401:
            fail("GitHub API authentication failed. Check your token.")
        fail(f"GitHub API error {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        fail(f"failed to fetch {url}: {exc}")


def normalize_repo(repo: str) -> str:
    repo = repo.strip()
    if repo.startswith("https://github.com/"):
        repo = repo.removeprefix("https://github.com/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        fail(f"invalid GitHub repository: {repo}")
    return repo


V3_FLAGS = {"avx2", "bmi1", "bmi2", "f16c", "fma", "lzcnt", "movbe", "osxsave"}


def detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        try:
            with open("/proc/cpuinfo") as fh:
                flags_line = ""
                for line in fh:
                    if line.startswith("flags"):
                        flags_line = line
                        break
                flags = set(flags_line.partition(":")[2].strip().lower().split())
        except (OSError, IOError):
            flags = set()
        if V3_FLAGS <= flags:
            return "amd64v3"
        return "amd64"
    fail(f"cannot auto-detect supported architecture from {machine!r}")


def discover_assets(repo: str, max_pages: int, token: str | None = None) -> list[Asset]:
    seen: dict[tuple[str, int, str, str], Asset] = {}
    per_page = 100
    for page in range(1, max_pages + 1):
        url = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}&page={page}"
        releases = request_json(url, token)
        if not releases:
            break
        for release in releases:
            if release.get("draft"):
                continue
            release_url = release.get("html_url", "")
            for asset_data in release.get("assets", []):
                filename = asset_data["name"]
                match = ASSET_RE.match(filename)
                if not match:
                    continue
                full_version = match.group("version")
                rebuild_str = match.group("rebuild")
                rebuild = int(rebuild_str.lstrip(".")) if rebuild_str else 0
                key = (
                    full_version,
                    rebuild,
                    match.group("arch"),
                    match.group("build"),
                )
                if key not in seen:
                    seen[key] = Asset(
                        filename=filename,
                        version=full_version,
                        arch=match.group("arch"),
                        build=match.group("build"),
                        rebuild=rebuild,
                        download_url=asset_data["browser_download_url"],
                        release_url=release_url,
                    )
    return list(seen.values())


def download_asset(asset: Asset, destination: Path, token: str | None = None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(asset.download_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            with destination.open("wb") as dst:
                shutil.copyfileobj(resp, dst)
    except urllib.error.URLError as exc:
        fail(f"failed to download {asset.filename}: {exc}")
    return destination


def semver_key(version: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = SEMVER_RE.match(version)
    if not match:
        nums = tuple(int(x) for x in re.findall(r"\d+", version)[:3])
        nums = nums + (0,) * (3 - len(nums))
        return (nums[:3], tuple(version.split("-", 1)[1:]) or None)
    main = (
        int(match.group("major")),
        int(match.group("minor") or 0),
        int(match.group("patch") or 0),
    )
    pre = match.group("pre")
    return main, tuple(pre.split(".")) if pre else None


def compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    for l_item, r_item in zip(left, right):
        l_num = l_item.isdigit()
        r_num = r_item.isdigit()
        if l_num and r_num:
            diff = int(l_item) - int(r_item)
            if diff:
                return 1 if diff > 0 else -1
        elif l_num != r_num:
            return -1 if l_num else 1
        elif l_item != r_item:
            return 1 if l_item > r_item else -1
    if len(left) == len(right):
        return 0
    return 1 if len(left) > len(right) else -1


def compare_versions(left: str, right: str) -> int:
    left_main, left_pre = semver_key(left)
    right_main, right_pre = semver_key(right)
    if left_main != right_main:
        return 1 if left_main > right_main else -1
    if left_pre is None and right_pre is None:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1
    return compare_prerelease(left_pre, right_pre)


def latest_asset(assets: Iterable[Asset], track: str, arch: str, build: str) -> Asset | None:
    filtered = [a for a in assets if a.arch == arch and a.build == build]
    if track == "stable":
        filtered = [a for a in filtered if not TESTING_RE.search(a.version)]
    else:
        filtered = [a for a in filtered if TESTING_RE.search(a.version)]
    if not filtered:
        return None
    return max(filtered, key=functools.cmp_to_key(
        lambda a, b: compare_asset_versions(a, b)
    ))


def compare_asset_versions(a: Asset, b: Asset) -> int:
    cmp = compare_versions(a.version, b.version)
    if cmp != 0:
        return cmp
    if a.rebuild != b.rebuild:
        return 1 if a.rebuild > b.rebuild else -1
    return 0


def current_version(binary: Path) -> str | None:
    if not binary.exists():
        return None
    command = [str(binary), "version"]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return None
    text = result.stdout + result.stderr
    match = CURRENT_VERSION_RE.search(text)
    if not match:
        return None
    version = match.group("version")
    return re.sub(r"-reF1nd(?:\.[0-9]+)?$", "", version)


def load_config(config_path: str | None = None) -> dict[str, Any]:
    path = Path(config_path or CONFIG_PATH)
    if not path.is_file():
        return {}
    try:
        with path.open() as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"failed to read config file {path}: {exc}")


def write_config(data: dict[str, Any], config_path: str | None = None) -> None:
    path = Path(config_path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w") as fh:
            json.dump(data, fh, indent=4)
            fh.write("\n")
    except OSError as exc:
        fail(f"failed to write config file {path}: {exc}")


def extract_binary(archive: Path, output: Path) -> tuple[Path, Path | None]:
    cronet_output: Path | None = None
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = [m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "sing-box"]
            if len(members) != 1:
                names = ", ".join(m.name for m in members) or "none"
                fail(f"expected exactly one sing-box binary in archive, found: {names}")
            source = tar.extractfile(members[0])
            if source is None:
                fail("failed to read sing-box binary from archive")
            with output.open("wb") as dst:
                shutil.copyfileobj(source, dst)
            cronet_members = [m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "libcronet.so"]
            if len(cronet_members) == 1:
                cronet_source = tar.extractfile(cronet_members[0])
                if cronet_source is not None:
                    cronet_output = output.parent / "libcronet.so"
                    with cronet_output.open("wb") as dst:
                        shutil.copyfileobj(cronet_source, dst)
                    cronet_output.chmod(0o644)
            elif len(cronet_members) > 1:
                fail("multiple libcronet.so found in archive")
    except tarfile.TarError as exc:
        fail(f"failed to unpack {archive}: {exc}")
    output.chmod(0o755)
    return output, cronet_output


def verify_binary(binary: Path, expected_version: str) -> None:
    try:
        result = subprocess.run(
            [str(binary), "version"], text=True, capture_output=True, timeout=10, check=False
        )
    except OSError as exc:
        fail(f"downloaded binary cannot run; wrong architecture/build? {exc}")
    output = result.stdout + result.stderr
    if result.returncode != 0:
        fail(f"downloaded binary version check failed: {output.strip()}")
    if expected_version not in output:
        fail(f"downloaded binary version mismatch; expected {expected_version}")


def install_binary(binary: Path, install_path: Path, backup: bool) -> None:
    install_dir = install_path.parent
    if not install_dir.exists():
        fail(f"install directory does not exist: {install_dir}")
    tmp_target = install_dir / f".{install_path.name}.new.{os.getpid()}"
    try:
        shutil.copy2(binary, tmp_target)
        tmp_target.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        if backup and install_path.exists():
            backup_path = install_dir / f"{install_path.name}.bak"
            shutil.copy2(install_path, backup_path)
        os.replace(tmp_target, install_path)
    except PermissionError:
        fail(f"permission denied installing to {install_path}; run with sudo/root")
    finally:
        try:
            tmp_target.unlink()
        except FileNotFoundError:
            pass


def install_library(library: Path, install_path: Path) -> None:
    install_dir = install_path.parent
    install_dir.mkdir(parents=True, exist_ok=True)
    tmp_target = install_dir / f".{install_path.name}.new.{os.getpid()}"
    try:
        shutil.copy2(library, tmp_target)
        tmp_target.chmod(0o644)
        os.replace(tmp_target, install_path)
    except PermissionError:
        fail(f"permission denied installing to {install_path}; run with sudo/root")
    finally:
        try:
            tmp_target.unlink()
        except FileNotFoundError:
            pass


def _used_ports() -> set[int]:
    ports: set[int] = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6", "/proc/net/udp", "/proc/net/udp6"):
        try:
            with open(name) as fh:
                next(fh)  # skip header
                for line in fh:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    local = parts[1]
                    hex_port = local.split(":", 1)[-1]
                    ports.add(int(hex_port, 16))
        except (OSError, ValueError):
            pass
    return ports


def _random_free_port() -> int:
    used = _used_ports()
    candidates = [p for p in range(10000, 60001) if p not in used]
    if not candidates:
        fail("no free port available in range 10000-60000")
    return secrets.choice(candidates)


def do_install(install_path: Path) -> None:
    if os.geteuid() != 0:
        fail("--install requires root privileges; run with sudo")

    try:
        pwd.getpwnam(SERVICE_USER)
        log(f"User {SERVICE_USER} already exists")
    except KeyError:
        subprocess.run(
            [
                "useradd", "-r", "-s", SERVICE_SHELL,
                "-d", "/", "-c", "sing-box reF1nd Service",
                SERVICE_USER,
            ],
            check=True,
        )
        log(f"Created user {SERVICE_USER}")

    for d in (SERVICE_STATE_DIR, SERVICE_CONFIG_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)
    shutil.chown(SERVICE_STATE_DIR, SERVICE_USER, SERVICE_USER)

    config_file = Path(SERVICE_CONFIG_DIR) / "config.json"
    if not config_file.is_file():
        psk = secrets.token_urlsafe(15)
        port = _random_free_port()
        cfg = dict(DEFAULT_SINGBOX_CONFIG)
        cfg["inbounds"][0]["psk"] = psk
        cfg["inbounds"][0]["listen_port"] = port
        with config_file.open("w") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        config_file.chmod(0o644)
        log(f"Created {config_file} with random PSK on port {port}")
    else:
        log(f"{config_file} already exists, skipping")

    unit_content = f"""[Unit]
Description=sing-box reF1nd service
Documentation=https://github.com/reF1nd/sing-box
After=network.target nss-lookup.target network-online.target

[Service]
User={SERVICE_USER}
StateDirectory=sing-box-ref1nd
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_PTRACE CAP_DAC_READ_SEARCH
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_PTRACE CAP_DAC_READ_SEARCH
ExecStart={install_path} -D {SERVICE_STATE_DIR} -C {SERVICE_CONFIG_DIR} run
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=10s
LimitNOFILE=infinity

[Install]
WantedBy=multi-user.target
"""

    template_content = f"""[Unit]
Description=sing-box reF1nd service
Documentation=https://github.com/reF1nd/sing-box
After=network.target nss-lookup.target network-online.target

[Service]
User={SERVICE_USER}
StateDirectory=sing-box-ref1nd-%i
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_PTRACE CAP_DAC_READ_SEARCH
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_PTRACE CAP_DAC_READ_SEARCH
ExecStart={install_path} -D {SERVICE_STATE_DIR}-%i -c {SERVICE_CONFIG_DIR}/%i.json run
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=10s
LimitNOFILE=infinity

[Install]
WantedBy=multi-user.target
"""

    for path, content in ((SERVICE_UNIT, unit_content), (SERVICE_TEMPLATE, template_content)):
        Path(path).write_text(content)
        Path(path).chmod(0o644)
        log(f"Created {path}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    log("systemd daemon-reload done")
    log(f"Run: systemctl enable --now sing-box-ref1nd")


def _first_nonempty(*values: Any) -> str | None:
    for v in values:
        if v:
            return str(v)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update sing-box reF1nd from GitHub Releases")
    parser.add_argument("--track", choices=("stable", "testing"), default=None)
    parser.add_argument("--arch", choices=("auto", "arm64", "amd64v3", "amd64"), default=None)
    parser.add_argument("--build", choices=("purego", "musl", "glibc"), default=None)
    parser.add_argument("--repo", default=None, help="GitHub repo (default: reF1nd/sing-box-releases)")
    parser.add_argument("--install-path", default=None)
    parser.add_argument("--max-pages", type=int, default=3, help="GitHub API result pages to scan")
    parser.add_argument("--token", help="GitHub personal access token; can also use GITHUB_TOKEN env var")
    parser.add_argument("--config", default=None, help=f"config file path (default: {CONFIG_PATH})")
    parser.add_argument("--force", action="store_true", help="download and install even when not newer")
    parser.add_argument("--dry-run", action="store_true", help="check only; do not download or install")
    parser.add_argument("--list", action="store_true", help="list matching assets and exit")
    parser.add_argument("--no-backup", action="store_true", help="do not save existing binary as .bak")
    parser.add_argument("--skip-verify-binary", action="store_true", help="skip running downloaded binary before install")
    parser.add_argument("--install", action="store_true", help="set up system service (user, dirs, config, systemd units)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    config_path = Path(args.config or CONFIG_PATH)

    repo = normalize_repo(_first_nonempty(args.repo, cfg.get("repo"), REPO))
    arch = _first_nonempty(args.arch, cfg.get("arch")) or "auto"
    arch = detect_arch() if arch == "auto" else arch
    build = _first_nonempty(args.build, cfg.get("build")) or "musl"
    track = _first_nonempty(args.track, cfg.get("track")) or "stable"
    install_path = Path(_first_nonempty(args.install_path, cfg.get("install_path")) or INSTALL_PATH)
    token = _first_nonempty(args.token, cfg.get("token"), os.environ.get("GITHUB_TOKEN"))

    resolved = {
        "track": track,
        "arch": arch,
        "build": build,
    }
    if token:
        resolved["token"] = token
    if repo != REPO:
        resolved["repo"] = repo
    if str(install_path) != INSTALL_PATH:
        resolved["install_path"] = str(install_path)

    should_save = (
        not config_path.is_file()
        or (not args.list and not args.dry_run)
    )
    config_changed = not config_path.is_file() or any(
        str(resolved.get(k)) != str(cfg.get(k)) for k in resolved
    )
    if should_save and config_changed:
        merged = {**cfg, **{k: v for k, v in resolved.items() if v}}
        write_config(merged, str(config_path))
        log(f"Config saved to {config_path}")

    if args.list:
        log(f"Discovering releases from {repo} for linux-{arch}-{build} ...")
        assets = discover_assets(repo, args.max_pages, token)
        matching = sorted(
            [a for a in assets if a.arch == arch and a.build == build],
            key=functools.cmp_to_key(
                lambda a, b: compare_asset_versions(a, b)
            ),
            reverse=True,
        )
        for asset in matching:
            print(f"{asset.display_version()}\t{asset.filename}\t{asset.release_url}")
        return 0

    log(f"Discovering releases from {repo} ({track}) for linux-{arch}-{build} ...")
    assets = discover_assets(repo, args.max_pages, token)

    asset = latest_asset(assets, track, arch, build)
    if not asset:
        fail(f"no matching {track} linux-{arch}-{build} asset found")

    installed = current_version(install_path)
    log(f"Latest:   {asset.display_version()} ({asset.filename})")
    log(f"Release:  {asset.release_url}")
    log(f"Current:  {installed or 'not installed / unknown'}")

    should_install = args.force or args.install or installed is None or compare_versions(asset.version, installed) > 0
    if not should_install:
        if compare_versions(asset.version, installed) == 0:
            log("Already up to date.")
        else:
            log("Installed version is newer than selected channel asset. Use --force to install anyway.")
        return 0
    if args.dry_run:
        log(f"Would install {asset.display_version()} to {install_path}")
        if args.install:
            log("Would set up systemd service (user, dirs, config, units)")
        return 0

    if installed is None or compare_versions(asset.version, installed) > 0 or args.force:
        with tempfile.TemporaryDirectory(prefix="sing-box-ref1nd-") as tmp:
            tmpdir = Path(tmp)
            archive_path = tmpdir / asset.filename
            log(f"Downloading {asset.download_url}")
            download_asset(asset, archive_path, token)
            binary_path = tmpdir / "sing-box"
            _, libcronet_path = extract_binary(archive_path, binary_path)
            if not args.skip_verify_binary:
                verify_binary(binary_path, asset.version)
            install_binary(binary_path, install_path, backup=not args.no_backup)
            if libcronet_path is not None:
                install_library(libcronet_path, Path(CRONET_LIB_PATH) / "libcronet.so")
                log(f"Installed libcronet.so to {CRONET_LIB_PATH}")
        log(f"Installed {asset.display_version()} to {install_path}")
    elif args.install:
        log("Binary already up to date, skipping download")

    if args.install:
        do_install(install_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
