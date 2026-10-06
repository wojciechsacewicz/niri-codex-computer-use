#!/usr/bin/env python3
"""Report upstream changes without modifying a working installation."""

import argparse
import http.client
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request


COMPONENTS = ("upstream_patches", "niri", "codex_desktop_linux")
DEFAULT_LOCK = Path(__file__).resolve().parent.parent / "sources.lock.json"
TIMEOUT = 15
REPOSITORY = re.compile(
    r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/"
    r"([A-Za-z0-9_.-]{1,100})"
)
REVISION = re.compile(r"[0-9a-fA-F]{40}")
FETCH_ERRORS = (OSError, ValueError, urllib.error.URLError, http.client.HTTPException)


def fetch_json(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "niri-codex-computer-use-update-check",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def repository_path(item):
    if not isinstance(item, dict):
        raise ValueError("component must be an object")
    repository = item.get("repository")
    match = REPOSITORY.fullmatch(repository) if isinstance(repository, str) else None
    if not match or match[2] in (".", "..") or match[2].endswith(".git"):
        raise ValueError("repository must be https://github.com/OWNER/REPO")
    revision = item.get("revision")
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError("revision must be a pinned 40-character hexadecimal commit")
    return "/".join(match.groups())


def commit_result(data, pinned):
    if not isinstance(data, dict):
        raise ValueError("GitHub commit response must be an object")
    revision = data.get("sha")
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError("GitHub commit response has no valid commit SHA")
    return {"revision": revision,
            "update_available": revision.lower() != pinned.lower()}


def stable_result(base, pinned, fetch):
    release = fetch(base + "/releases/latest")
    if (not isinstance(release, dict) or release.get("draft") is not False
            or release.get("prerelease") is not False):
        raise ValueError("GitHub latest release must be stable and published")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("GitHub latest release has no tag")
    # Resolve annotated tags to their commit, not the tag-object SHA.
    result = commit_result(fetch(base + "/commits/" +
                                 urllib.parse.quote(tag, safe="")), pinned)
    return {"tag": tag, **result}


def check_updates(lock_path, fetch=fetch_json):
    report = {"components": [], "errors": []}

    def error(component, channel, message):
        report["errors"].append({"component": component, "channel": channel,
                                 "message": str(message)})

    try:
        lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
        if not isinstance(lock, dict) or type(lock.get("schema")) is not int or lock["schema"] != 1:
            raise ValueError("lock must be an object with schema 1")
    except (OSError, ValueError) as exc:
        error("lock", "validation", exc)
        return report

    for name in COMPONENTS:
        try:
            item = lock.get(name)
            repo = repository_path(item)
        except ValueError as exc:
            error(name, "validation", exc)
            continue
        component = {"component": name, "repository": item["repository"],
                     "pinned": item["revision"]}
        report["components"].append(component)
        base = "https://api.github.com/repos/" + repo
        channels = ("stable", "development") if name == "niri" else ("default_head",)
        for channel in channels:
            try:
                if channel == "stable":
                    result = stable_result(base, item["revision"], fetch)
                else:
                    ref = "main" if channel == "development" else "HEAD"
                    result = commit_result(fetch(base + "/commits/" + ref), item["revision"])
                    result["ref"] = ref
                component[channel] = result
            except FETCH_ERRORS as exc:
                error(name, channel, exc)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK,
                        help="source lock file (default: repository sources.lock.json)")
    parser.add_argument("--json", action="store_true", help="emit one JSON report, including errors")
    args = parser.parse_args(argv)
    report = check_updates(args.lock)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for component in report["components"]:
            print(f"{component['component']}: pinned {component['pinned']}")
            for channel in ("stable", "development", "default_head"):
                if channel in component:
                    result = component[channel]
                    status = "update available" if result["update_available"] else "matches pin"
                    ref = result.get("tag", result.get("ref"))
                    print(f"  {channel} ({ref}): {result['revision']} [{status}]")
        for error in report["errors"]:
            print(f"ERROR {error['component']} ({error['channel']}): {error['message']}")
        print("Source updates require patch checks and native verification before installation.")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
