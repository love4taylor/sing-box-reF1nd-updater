#!/usr/bin/env python3
"""Update sing-box reF1nd builds published in a Telegram channel.

Discovery uses Telegram's public web preview. Actual Telegram file download
requires a normal Telegram API session via Telethon because public preview pages
do not expose stable direct archive URLs.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import html
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CHANNEL = "sing_box_reF1nd"
INSTALL_PATH = "/usr/bin/sing-box"
USER_AGENT = "Mozilla/5.0 sing-box-reF1nd-updater/1.0"

ASSET_RE = re.compile(
    r"^sing-box-(?P<version>.+?)-reF1nd-linux-"
    r"(?P<arch>arm64|amd64v3|amd64)-(?P<build>purego|musl|glibc)\.tar\.gz$"
)
DOC_RE = re.compile(
    r'<a class="tgme_widget_message_document_wrap" href="(?P<href>[^"]+)">.*?'
    r'<div class="tgme_widget_message_document_title[^>]*>(?P<title>.*?)</div>',
    re.S,
)
MORE_RE = re.compile(r'data-before="(?P<before>\d+)"')
CURRENT_VERSION_RE = re.compile(r"sing-box\s+version\s+(?P<version>\S+)")
SEMVER_RE = re.compile(
    r"^(?P<major>\d+)"
    r"(?:\.(?P<minor>\d+))?"
    r"(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True)
class Asset:
    filename: str
    version: str
    arch: str
    build: str
    message_id: int
    message_url: str


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str, exit_code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def request_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        fail(f"failed to fetch {url}: {exc}")


def normalize_channel(channel: str) -> str:
    channel = channel.strip()
    if channel.startswith("https://t.me/"):
        channel = channel.removeprefix("https://t.me/").strip("/")
    if channel.startswith("@"):
        channel = channel[1:]
    if not re.fullmatch(r"[A-Za-z0-9_]+", channel):
        fail(f"invalid Telegram channel: {channel}")
    return channel


def detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        # amd64 is the safe default. Choose amd64v3 explicitly if desired.
        return "amd64"
    fail(f"cannot auto-detect supported architecture from {machine!r}")


def parse_asset(channel: str, title: str, href: str) -> Asset | None:
    filename = html.unescape(re.sub(r"<.*?>", "", title)).strip()
    match = ASSET_RE.match(filename)
    if not match:
        return None
    id_match = re.search(r"/(\d+)(?:\?|$)", html.unescape(href))
    if not id_match:
        return None
    message_id = int(id_match.group(1))
    return Asset(
        filename=filename,
        version=match.group("version"),
        arch=match.group("arch"),
        build=match.group("build"),
        message_id=message_id,
        message_url=f"https://t.me/{channel}/{message_id}",
    )


def discover_assets(channel: str, track: str, max_pages: int) -> list[Asset]:
    assets: dict[str, Asset] = {}
    before: str | None = None
    for _ in range(max_pages):
        query = urllib.parse.urlencode({"q": f"#{track}"})
        url = f"https://t.me/s/{channel}?{query}"
        if before:
            url += f"&before={urllib.parse.quote(before)}"
        page = request_text(url)
        for match in DOC_RE.finditer(page):
            asset = parse_asset(channel, match.group("title"), match.group("href"))
            if asset:
                assets[asset.filename] = asset
        more = MORE_RE.search(page)
        if not more:
            break
        next_before = more.group("before")
        if next_before == before:
            break
        before = next_before
    return list(assets.values())


def semver_key(version: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = SEMVER_RE.match(version)
    if not match:
        # Fallback keeps unknown versions comparable and deterministic.
        nums = tuple(int(x) for x in re.findall(r"\d+", version)[:3])
        nums = nums + (0,) * (3 - len(nums))
        return (nums[:3], tuple(version.split("-", 1)[1:]) or None)  # type: ignore[return-value]
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
        filtered = [a for a in filtered if "-" not in a.version]
    else:
        filtered = [a for a in filtered if "-" in a.version]
    if not filtered:
        return None
    return max(filtered, key=functools.cmp_to_key(lambda a, b: compare_versions(a.version, b.version)))


def current_version(binary: Path) -> str | None:
    command = [str(binary), "version"] if binary.exists() else ["sing-box", "version"]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return None
    text = result.stdout + result.stderr
    match = CURRENT_VERSION_RE.search(text)
    if not match:
        return None
    version = match.group("version")
    return version.removesuffix("-reF1nd")


async def download_with_telethon(
    channel: str,
    asset: Asset,
    destination: Path,
    api_id: str | None,
    api_hash: str | None,
    session: str,
) -> Path:
    if not api_id:
        api_id = os.environ.get("TELEGRAM_API_ID")
    if not api_hash:
        api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        fail(
            "download requires Telegram API credentials; set TELEGRAM_API_ID "
            "and TELEGRAM_API_HASH or pass --api-id/--api-hash"
        )
    try:
        from telethon import TelegramClient  # type: ignore
    except ImportError:
        fail(
            "Telethon is required for download.\n"
            "  pip:      python3 -m pip install telethon\n"
            "  Debian/Ubuntu: sudo apt install python3-telethon"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        session, int(api_id), api_hash,
        device_model="sing-box-ref1nd-updater",
        system_version="Linux",
        app_version="1.0",
    )
    await client.start()
    try:
        entity = await client.get_entity(channel)
        message = await client.get_messages(entity, ids=asset.message_id)
        if not message or not getattr(message, "file", None):
            fail(f"Telegram message {asset.message_id} has no downloadable file")
        remote_name = getattr(message.file, "name", None)
        if remote_name and remote_name != asset.filename:
            fail(f"message file mismatch: expected {asset.filename}, got {remote_name}")
        downloaded = await client.download_media(message, file=str(destination))
    finally:
        await client.disconnect()
    if not downloaded:
        fail("Telethon did not return a downloaded file path")
    return Path(downloaded)


def extract_binary(archive: Path, output: Path) -> None:
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
    except tarfile.TarError as exc:
        fail(f"failed to unpack {archive}: {exc}")
    output.chmod(0o755)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update sing-box reF1nd from Telegram releases")
    parser.add_argument("--track", choices=("stable", "testing"), default="stable")
    parser.add_argument("--arch", choices=("auto", "arm64", "amd64v3", "amd64"), default="auto")
    parser.add_argument("--build", choices=("purego", "musl", "glibc"), default="glibc")
    parser.add_argument("--channel", default=CHANNEL, help="Telegram channel name or https://t.me/... URL")
    parser.add_argument("--install-path", default=INSTALL_PATH)
    parser.add_argument("--max-pages", type=int, default=5, help="Telegram search result pages to scan")
    parser.add_argument("--api-id", help="Telegram API ID; can also use TELEGRAM_API_ID")
    parser.add_argument("--api-hash", help="Telegram API hash; can also use TELEGRAM_API_HASH")
    parser.add_argument("--session", default="sing_box_ref1nd.session", help="Telethon session file")
    parser.add_argument("--force", action="store_true", help="download and install even when not newer")
    parser.add_argument("--dry-run", action="store_true", help="check only; do not download or install")
    parser.add_argument("--list", action="store_true", help="list matching assets and exit")
    parser.add_argument("--no-backup", action="store_true", help="do not save existing binary as sing-box.bak")
    parser.add_argument("--skip-verify-binary", action="store_true", help="skip running downloaded binary before install")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    channel = normalize_channel(args.channel)
    arch = detect_arch() if args.arch == "auto" else args.arch
    install_path = Path(args.install_path)

    log(f"Scanning @{channel} #{args.track} for linux-{arch}-{args.build} ...")
    assets = discover_assets(channel, args.track, args.max_pages)
    matching = sorted(
        [a for a in assets if a.arch == arch and a.build == args.build],
        key=functools.cmp_to_key(lambda a, b: compare_versions(a.version, b.version)),
        reverse=True,
    )
    if args.list:
        for asset in matching:
            print(f"{asset.version}\t{asset.filename}\t{asset.message_url}")
        return 0

    asset = latest_asset(assets, args.track, arch, args.build)
    if not asset:
        fail(f"no matching {args.track} linux-{arch}-{args.build} asset found")

    installed = current_version(install_path)
    log(f"Latest:   {asset.version} ({asset.filename})")
    log(f"Current:  {installed or 'not installed / unknown'}")

    should_install = args.force or installed is None or compare_versions(asset.version, installed) > 0
    if not should_install:
        if compare_versions(asset.version, installed) == 0:
            log("Already up to date.")
        else:
            log("Installed version is newer than selected channel asset. Use --force to install anyway.")
        return 0
    if args.dry_run:
        log(f"Would install {asset.version} to {install_path}")
        return 0

    with tempfile.TemporaryDirectory(prefix="sing-box-ref1nd-") as tmp:
        tmpdir = Path(tmp)
        archive_path = tmpdir / asset.filename
        log(f"Downloading: {asset.message_url}")
        downloaded = asyncio.run(
            download_with_telethon(channel, asset, archive_path, args.api_id, args.api_hash, args.session)
        )
        binary_path = tmpdir / "sing-box"
        extract_binary(downloaded, binary_path)
        if not args.skip_verify_binary:
            verify_binary(binary_path, asset.version)
        install_binary(binary_path, install_path, backup=not args.no_backup)

    log(f"Installed {asset.version} to {install_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
