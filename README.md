# sing-box reF1nd updater

Check and install [reF1nd sing-box releases](https://t.me/sing_box_reF1nd) from Telegram channel.

## Requirements

- Python 3.9+
- [Telethon](https://docs.telethon.dev) — `pip install telethon` (Debian/Ubuntu: `apt install python3-telethon`)
- [Telegram API credentials](https://my.telegram.org/apps)

## Quick start

Create `~/.config/sing-box-ref1nd-updater/config.json`:

```json
{
    "api_id": 12345,
    "api_hash": "your_hash_here",
    "track": "stable",
    "arch": "amd64",
    "build": "glibc"
}
```

Then:

```bash
./sing-box-ref1nd-updater.py --dry-run
sudo ./sing-box-ref1nd-updater.py
```

Credentials can also be set via env vars (`TELEGRAM_API_ID` / `TELEGRAM_API_HASH`) or CLI flags (`--api-id` / `--api-hash`). First run will ask for phone number / verification code and save a session file.

### Examples

```bash
# List available stable builds
./sing-box-ref1nd-updater.py --list

# Check testing track
./sing-box-ref1nd-updater.py --track testing --dry-run

# Install testing, override arch
sudo ./sing-box-ref1nd-updater.py --track testing --arch amd64v3 --build musl
```

### Options

| Option | Default | Description |
|---|---|---|
| `--track` | `stable` | `stable` or `testing` |
| `--arch` | `auto` | `arm64`, `amd64v3`, `amd64` |
| `--build` | `glibc` | `purego`, `musl`, `glibc` |
| `--config` | `~/.config/sing-box-ref1nd-updater/config.json` | Config file path |
| `--channel` | `sing_box_reF1nd` | Telegram channel |
| `--install-path` | `/usr/bin/sing-box` | Target binary path |
| `--session` | `~/.config/sing-box-ref1nd-updater/session` | Telethon session file |
| `--dry-run` | — | Check only, no download |
| `--list` | — | List matching assets and exit |
| `--force` | — | Install even if not newer |
| `--no-backup` | — | Skip saving `sing-box.bak` |
| `--skip-verify-binary` | — | Skip running downloaded binary before install |
| `--max-pages` | `5` | Search result pages to scan |
