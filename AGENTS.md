<!-- FOR AI AGENTS - Human readability is a side effect, not a goal -->
<!-- Managed by agent: keep sections and order; edit content, not structure -->
<!-- Last updated: 2026-06-21 | Last verified: 2026-06-21 -->

# AGENTS.md

**Precedence:** the **closest `AGENTS.md`** to the files you're changing wins.

## Commands (verified)
> Source: manual — no CI. All verified 2026-06-21. Requires Python 3.9+, zero deps.

| Task | Command | ~Time |
|------|---------|-------|
| Help | `python3 sing-box-ref1nd-updater.py --help` | <1s |
| Syntax check | `python3 -m py_compile sing-box-ref1nd-updater.py` | <1s |
| Dry-run | `python3 sing-box-ref1nd-updater.py --dry-run` | 2-10s |
| List assets | `python3 sing-box-ref1nd-updater.py --list` | 2-15s |
| Install | `sudo python3 sing-box-ref1nd-updater.py` | 30-120s |
| Full setup | `sudo python3 sing-box-ref1nd-updater.py --install` | 30-180s |

## File Map
```
sing-box-ref1nd-updater.py   — Single-file (693 lines): GitHub Release fetcher, binary installer, systemd setup
README.md / LICENSE          — Docs, MIT
```

## Golden Samples
| For | Reference | Key patterns |
|-----|-----------|--------------|
| CLI parsing | `parse_args` L544-560 | argparse, --flag style |
| GitHub API | `request_json` L97-120 | urllib.request, token, rate-limit |
| Semver | `semver_key`/`compare_versions` L218-261 | Tuple sort, prerelease ordering |
| Safe install | `install_binary` L379-397 | Atomic os.replace, .bak backup |

## Heuristics & Boundaries
- **Always**: syntax-check before commit; `--dry-run` before sudo; keep zero-dependency; read full file before editing. When adding CLI flags → use argparse in `parse_args()`; changing defaults → update L27-41 constants.
- **Ask first**: adding deps (stdlib-only by design); modifying systemd units; changing default paths.
- **Never**: commit credentials; use pip/pypi; touch `.codegraph/` or `__pycache__/`.

## Codebase State & Terminology
No CI/CD, no test suite. Single-file (693 lines), Python 3.9+ stdlib only, Linux-targeted (systemd). `track`=release channel, `arch`=CPU, `build`=C library variant.

## Scoped AGENTS.md
No subdirectories — this is the only AGENTS.md in the project.
