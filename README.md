# sing-box reF1nd updater

Check and install [reF1nd sing-box releases](https://github.com/reF1nd/sing-box-releases/releases) from GitHub Releases.

## Requirements

- Python 3.9+

No external dependencies — uses only the standard library and the GitHub API.

## Quick start

```bash
# First-time / one-shot setup
sudo ./sing-box-ref1nd-updater.py --install

# Update binary only
sudo ./sing-box-ref1nd-updater.py
```

### What `--install` creates

| Path | Description |
|---|---|
| `/usr/local/bin/sing-box-ref1nd` | Binary |
| `/usr/local/lib/cronet-go/libcronet.so` | Optional library (purego build only) |
| `/usr/local/etc/sing-box-ref1nd/config.json` | sing-box config (auto-generated) |
| `/var/lib/sing-box-ref1nd/` | State directory |
| `/etc/systemd/system/sing-box-ref1nd.service` | Systemd service |
| `/etc/systemd/system/sing-box-ref1nd@.service` | Systemd template |
| `~/.config/sing-box-ref1nd-updater/config.json` | Updater config |

Also creates `sing-box-ref1nd` system user (`/usr/sbin/nologin`).

On first run, settings are saved to `~/.config/sing-box-ref1nd-updater/config.json`. You can also create it manually to override defaults:

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
# or in config.json: "token": "ghp_..."
```

### Examples

```bash
# Preview what would be installed
./sing-box-ref1nd-updater.py --dry-run

# List available builds
./sing-box-ref1nd-updater.py --list

# Check testing track
./sing-box-ref1nd-updater.py --track testing --dry-run

# Install testing with custom arch
sudo ./sing-box-ref1nd-updater.py --track testing --arch amd64v3 --build musl
```

### Options

| Option | Default | Description |
|---|---|---|
| `--track` | `stable` | `stable` or `testing` |
| `--arch` | `auto` | `arm64`, `amd64v3`, `amd64` |
| `--build` | `musl` | `purego`, `musl`, `glibc` |
| `--config` | `~/.config/sing-box-ref1nd-updater/config.json` | Config file path |
| `--repo` | `reF1nd/sing-box-releases` | GitHub repository |
| `--install-path` | `/usr/local/bin/sing-box-ref1nd` | Target binary path |
| `--token` | — | GitHub personal access token (or `GITHUB_TOKEN` env var) |
| `--dry-run` | — | Check only, no download |
| `--list` | — | List matching assets and exit |
| `--force` | — | Install even if not newer |
| `--no-backup` | — | Skip saving `.bak` |
| `--skip-verify-binary` | — | Skip running downloaded binary before install |
| `--install` | — | Set up systemd service (user, dirs, config, units) |
| `--max-pages` | `3` | GitHub API result pages to scan |
