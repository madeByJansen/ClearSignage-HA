#!/usr/bin/env python3
"""Allow a channel's mapped branch, or an explicitly pinned exact-commit override."""
import argparse
import re
import sys
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent))
from channels import CHANNELS, channel_settings


def publish_refusal(*, push, channel, branch, override, built_revision, pinned_revision):
    settings = channel_settings(channel)
    if not push:
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", built_revision):
        return "Refusing to publish: the build must record a full upstream commit SHA."
    if branch != settings["branch"]:
        return f"Refusing to publish: {channel} must use {settings['branch']}, not {branch}."
    if not override:
        return None
    if override == built_revision == pinned_revision:
        return None
    return (f"Refusing to publish {channel} override {override!r}: built {built_revision}, "
            f"approved pin {pinned_revision!r}. Pin the exact SHA in "
            f"{settings['addon_dir']}/release.yaml first, or build with PUSH=false.")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", required=True, choices=["true", "false"])
    parser.add_argument("--channel", required=True, choices=CHANNELS)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--override", default="")
    parser.add_argument("--built-revision", required=True)
    parser.add_argument("--release-file", required=True, type=Path)
    args = parser.parse_args(argv)
    release = yaml.safe_load(args.release_file.read_text()) or {}
    refusal = publish_refusal(
        push=args.push == "true", channel=args.channel, branch=args.branch,
        override=args.override, built_revision=args.built_revision,
        pinned_revision=str(release.get("clearsignage_revision", "")),
    )
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
