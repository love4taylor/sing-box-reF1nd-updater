<div align="center">

# sing-box reF1nd Updater

*Keep your [reF1nd sing-box builds](https://github.com/reF1nd/sing-box-releases) up to date — automatically.*

</div>

A zero-dependency Python script that checks GitHub Releases for the latest [reF1nd sing-box](https://github.com/reF1nd/sing-box-releases) build and installs it. Supports automated updates via systemd and runs anywhere Python 3.9+ is available.

## Features

- **Zero dependencies** — uses only the Python standard library and the GitHub API
- **Multi-track** — choose between `stable` and `testing` release channels
- **Arch-aware** — auto-detects your CPU architecture (`arm64`, `amd64v3`, `amd64`) or lets you override it
- **Build variants** — supports `purego`, `musl`, and `glibc` builds
- **Systemd integration** — one-command setup creates a dedicated service user, state directories, default config, and systemd units
- **Safe upgrades** — backs up the existing binary before overwriting, verifies the downloaded binary, and skips unnecessary installs

## Requirements

- **Python 3.9+** — no pip packages, no virtualenv needed

## Quick start

```bash
# First-time setup (binary + systemd service)
sudo ./sing-box-ref1nd-updater.py --install

# Update the binary only
sudo ./sing-box-ref1nd-updater.py
```

After the initial `--install`, enable and start the service:

```bash
sudo systemctl enable --now sing-box-ref1nd
```

## Usage

```
usage: sing-box-ref1nd-updater.py [-h] [--track {stable,testing}]
                                  [--arch {auto,arm64,amd64v3,amd64}]
                                  [--build {purego,musl,glibc}] [--repo REPO]
                                  [--install-path INSTALL_PATH]
                                  [--max-pages MAX_PAGES] [--token TOKEN]
                                  [--config CONFIG] [--force] [--dry-run]
                                  [--list] [--no-backup] [--skip-verify-binary]
                                  [--install]
```

### Options

| Option | Default | Description |
|---|---|---|
| `--track` | `stable` | Release track: `stable` or `testing` |
| `--arch` | `auto` | Target architecture: `arm64`, `amd64v3`, `amd64` |
| `--build` | `musl` | Build variant: `purego`, `musl`, `glibc` |
| `--repo` | `reF1nd/sing-box-releases` | GitHub repository to query |
| `--install-path` | `/usr/local/bin/sing-box-ref1nd` | Where to place the binary |
| `--max-pages` | `3` | GitHub API result pages to scan |
| `--token` | — | GitHub personal access token (or `GITHUB_TOKEN` env var) |
| `--config` | `~/.config/sing-box-ref1nd-updater/config.json` | Config file path |
| `--force` | — | Install even if the remote version is not newer |
| `--dry-run` | — | Check for updates without downloading |
| `--list` | — | List matching release assets and exit |
| `--no-backup` | — | Skip saving the existing binary as `.bak` |
| `--skip-verify-binary` | — | Skip running the downloaded binary before installing |
| `--install` | — | Set up systemd service (user, dirs, config, units) |

### Examples

```bash
# Preview what would be installed
./sing-box-ref1nd-updater.py --dry-run

# List available builds
./sing-box-ref1nd-updater.py --list

# Check the testing track without installing
./sing-box-ref1nd-updater.py --track testing --dry-run

# Install from testing with a specific arch and build
sudo ./sing-box-ref1nd-updater.py --track testing --arch amd64v3 --build musl

# Force reinstall even if already up to date
sudo ./sing-box-ref1nd-updater.py --force
```

## Configuration

On first run, settings are saved to `~/.config/sing-box-ref1nd-updater/config.json`. You can create it manually to override defaults:

```json
{
    "track": "stable",
    "arch": "amd64",
    "build": "musl"
}
```

For higher GitHub API rate limits, set a [personal access token](https://github.com/settings/tokens):

```bash
export GITHUB_TOKEN="ghp_..."
```

The token can also be placed directly in the config:

```json
{
    "track": "stable",
    "token": "ghp_..."
}
```

## What `--install` creates

Running `--install` with root privileges performs a full systemd integration:

| Path | Description |
|---|---|
| `/usr/local/bin/sing-box-ref1nd` | The binary |
| `/usr/local/lib/cronet-go/libcronet.so` | Optional cronet library (purego build only) |
| `/usr/local/etc/sing-box-ref1nd/config.json` | Auto-generated sing-box config with random PSK |
| `/var/lib/sing-box-ref1nd/` | State directory (owned by the service user) |
| `/etc/systemd/system/sing-box-ref1nd.service` | Systemd service unit |
| `/etc/systemd/system/sing-box-ref1nd@.service` | Systemd template unit |

It also creates a dedicated system user `sing-box-ref1nd` (`/usr/sbin/nologin`) and runs `systemctl daemon-reload`.

> [!NOTE]
> The auto-generated sing-box config includes a Snell inbound with a randomly generated PSK and a free port. You can edit `/usr/local/etc/sing-box-ref1nd/config.json` after setup.
