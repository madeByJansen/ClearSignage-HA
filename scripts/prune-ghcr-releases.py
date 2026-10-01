#!/usr/bin/env python3
"""Delete GHCR image versions older than the current and previous releases."""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from channels import CHANNELS, channel_settings
import ghcr_api  # noqa: E402  (the module sits beside this command, not on the path)


RELEASE_TAG = re.compile(r"^(\d+(?:\.\d+)+)(?:-(aarch64|amd64))?$")


def release_from_tags(tags: list[str]) -> str | None:
    """Return the release represented by a GHCR version's tags, if any."""
    releases = {match.group(1) for tag in tags if (match := RELEASE_TAG.fullmatch(tag))}
    if len(releases) > 1:
        raise ValueError(f"GHCR version unexpectedly contains several releases: {tags}")
    return next(iter(releases), None)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def versions_to_delete(versions: list[dict[str, object]], current: str) -> list[int]:
    """Select tagged release objects while preserving N and N-1.

    Untagged objects are intentionally ignored: they can be platform manifests referenced
    by one of the two retained multi-architecture indexes.
    """
    releases = {
        release
        for item in versions
        if (release := release_from_tags(item.get("metadata", {}).get("container", {}).get("tags", [])))
    }
    if current not in releases:
        raise ValueError(f"new release {current} was not found in GHCR; refusing to prune")

    current_key = version_key(current)
    older = sorted(
        (release for release in releases if version_key(release) < current_key),
        key=version_key,
    )
    retained = {current}
    if older:
        retained.add(older[-1])
    doomed_releases = set(older) - retained

    selected = []
    for item in versions:
        tags = item.get("metadata", {}).get("container", {}).get("tags", [])
        release = release_from_tags(tags)
        if release in doomed_releases:
            selected.append(int(item["id"]))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="madeByJansen")
    parser.add_argument("--channel", choices=CHANNELS, default=os.environ.get("CHANNEL", "stable"))
    parser.add_argument("--current", required=True)
    parser.add_argument("--apply", action="store_true", help="delete selected versions; otherwise dry-run")
    args = parser.parse_args()
    owner, package, current = args.owner, channel_settings(args.channel)["package"], args.current
    token = os.environ.get("GHCR_TOKEN")
    if not token:
        print("GHCR_TOKEN is required", file=sys.stderr)
        return 2

    owner_kind = "organization"
    base = ghcr_api.versions_url(owner, package, owner_kind)
    versions = ghcr_api.all_versions(owner, package, token, owner_kind=owner_kind)

    doomed = versions_to_delete(versions, current)
    for version_id in doomed:
        if args.apply:
            with ghcr_api.request(f"{base}/{version_id}", token, method="DELETE"):
                pass
        print(f"{'Deleted' if args.apply else 'Would delete'} {package} version {version_id}")
    print(f"Selected {len(doomed)} {package} versions; retained release {current} and its predecessor")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as error:
        print(f"GHCR pruning failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
