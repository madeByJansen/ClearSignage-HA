#!/usr/bin/env python3
"""Copy shared stable packaging to beta/dev; preserve each channel's manifest and pin."""
import argparse
from pathlib import Path
from channels import CHANNELS, channel_settings
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for channel in CHANNELS:
        if channel == "stable":
            continue
        settings = channel_settings(channel)
        for source in sorted((ROOT / "clearvenue").rglob("*")):
            relative = source.relative_to(ROOT / "clearvenue")
            if not source.is_file() or relative.parts[0] == "src" or relative.name in {"config.yaml", "release.yaml"}:
                continue
            destination = ROOT / settings["addon_dir"] / relative
            content = source.read_bytes()
            if relative.name in {"DOCS.md", "Dockerfile"}:
                content = content.replace(b'# ClearVenue\n', f'# {settings["name"]}\n'.encode())
                content = content.replace(b'io.hass.name="ClearVenue"', f'io.hass.name="{settings["name"]}"'.encode())
            mode = source.stat().st_mode & 0o777
            if not destination.exists() or destination.read_bytes() != content or destination.stat().st_mode & 0o777 != mode:
                stale.append(str(destination.relative_to(ROOT)))
                if not args.check:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                    destination.chmod(mode)
    if args.check and stale:
        parser.exit(1, "Run scripts/sync-channel-packaging.py; stale files: " + ", ".join(stale) + "\n")


if __name__ == "__main__":
    main()
