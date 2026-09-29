"""Read and write the app's GHCR package through GitHub's packages API.

Two scripts need the same access — one chooses the next version from what is already
published, the other deletes what is too old to keep — and two copies of an API contract
is how they stop agreeing. Kept as a module rather than a command because it is only ever
called by those.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import urllib.response

PAGE_SIZE = 100


def versions_url(owner: str, package: str) -> str:
    return "https://api.github.com/orgs/{}/packages/container/{}/versions".format(
        urllib.parse.quote(owner, safe=""), urllib.parse.quote(package, safe="")
    )


def request(url: str, token: str, method: str = "GET") -> urllib.response.addinfourl:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers, method=method))


def all_versions(owner: str, package: str, token: str, *, allow_missing=False) -> list[dict[str, object]]:
    """Return every version object in the package, following pagination."""
    base = versions_url(owner, package)
    versions: list[dict[str, object]] = []
    page = 1
    while True:
        try:
            with request(f"{base}?per_page={PAGE_SIZE}&page={page}", token) as response:
                batch = json.load(response)
        except urllib.error.HTTPError as error:
            # A new channel has no package yet. A 404 alone may also hide an auth
            # failure, so require a successful owner package listing before bootstrapping.
            if error.code != 404 or not allow_missing or page != 1:
                raise
            names = package_names(owner, token)
            if package in names:
                raise
            return []
        versions.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return versions


def package_names(owner: str, token: str) -> set[str]:
    names = set()
    page = 1
    owner = urllib.parse.quote(owner, safe="")
    while True:
        with request(f"https://api.github.com/orgs/{owner}/packages?package_type=container&per_page={PAGE_SIZE}&page={page}", token) as response:
            batch = json.load(response)
        names.update(item["name"] for item in batch)
        if len(batch) < PAGE_SIZE:
            return names
        page += 1


def tags_of(version: dict[str, object]) -> list[str]:
    """Return a version object's container tags, which an untagged manifest lacks."""
    metadata = version.get("metadata", {})
    container = metadata.get("container", {}) if isinstance(metadata, dict) else {}
    tags = container.get("tags", []) if isinstance(container, dict) else []
    return [str(tag) for tag in tags]
