#!/usr/bin/env python3
"""Delete all assets on an existing GitHub Release before re-uploading installers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def api_request(method: str, path: str, token: str) -> bytes | None:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "picard-oss-release",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} -> {exc.code}: {body}") from exc


def paginated_assets(repo: str, release_id: int, token: str) -> list[dict]:
    assets: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": "100", "page": str(page)})
        raw = api_request(
            "GET",
            f"/repos/{repo}/releases/{release_id}/assets?{query}",
            token,
        )
        if raw is None:
            break
        batch = json.loads(raw)
        if not batch:
            break
        assets.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return assets


def main() -> int:
    tag = os.environ.get("GITHUB_REF_NAME", "").removeprefix("refs/tags/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not tag or not repo:
        print("GITHUB_REF_NAME and GITHUB_REPOSITORY are required", file=sys.stderr)
        return 2
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    encoded_tag = urllib.parse.quote(tag, safe="")
    release_raw = api_request("GET", f"/repos/{repo}/releases/tags/{encoded_tag}", token)
    if release_raw is None:
        print(f"No release for tag {tag}; nothing to prune")
        return 0

    release = json.loads(release_raw)
    release_id = release["id"]
    assets = paginated_assets(repo, release_id, token)
    if not assets:
        print(f"Release {tag} has no assets to prune")
        return 0

    deleted = 0
    for asset in assets:
        asset_id = asset["id"]
        name = asset.get("name", str(asset_id))
        api_request("DELETE", f"/repos/{repo}/releases/assets/{asset_id}", token)
        deleted += 1
        print(f"Deleted asset: {name}")

    print(f"Pruned {deleted} asset(s) from release {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
