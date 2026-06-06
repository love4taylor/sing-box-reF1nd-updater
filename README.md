# sing-box reF1nd updater

Check and install [reF1nd sing-box releases](https://t.me/sing_box_reF1nd) from Telegram channel.

## Requirements

- Python 3.9+
- [Telethon](https://docs.telethon.dev) — `pip install telethon`
- [Telegram API credentials](https://my.telegram.org/apps)

## Usage

```bash
export TELEGRAM_API_ID=your_api_id
export TELEGRAM_API_HASH=your_api_hash
```

### Check for updates

```bash
./sing-box-ref1nd-updater.py --track stable --arch amd64 --build glibc --dry-run
./sing-box-ref1nd-updater.py --track testing --arch arm64 --build musl --dry-run
```

### List available versions

```bash
./sing-box-ref1nd-updater.py --track stable --arch amd64 --build glibc --list
```

### Install

```bash
sudo -E ./sing-box-ref1nd-updater.py --track stable --arch amd64 --build glibc
sudo -E ./sing-box-ref1nd-updater.py --track testing --arch amd64v3 --build musl
```

### Options

| Option | Default | Description |
|---|---|---|
| `--track` | `stable` | `stable` or `testing` |
| `--arch` | `auto` | `arm64`, `amd64v3`, `amd64` |
| `--build` | `glibc` | `purego`, `musl`, `glibc` |
| `--install-path` | `/usr/bin/sing-box` | Target binary path |
| `--dry-run` | — | Check only, no download |
| `--list` | — | List matching assets and exit |
| `--force` | — | Install even if not newer |
| `--no-backup` | — | Skip saving `sing-box.bak` |
| `--max-pages` | `5` | Search result pages to scan |
