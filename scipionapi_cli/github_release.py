"""Publishing a ScipionWeb release on GitHub, next to the CNB download server.

The installer and `scipionapi update` look for a release on GitHub first (ScipionWeb's releases) and on the CNB
server when GitHub fails. A release is published as a test release (pre-release) unless asked otherwise, and the
same version can be published again: the earlier GitHub release with that tag is replaced, as on the CNB server.

The new release is made as a draft with all its files first; the earlier one is removed only then, and the new one
published at once, so there is hardly a moment without it (and the installer falls back to the CNB server then).
It needs a GitHub token with write access to the repository's contents, in GITHUB_TOKEN.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

DEFAULT_GITHUB_REPO = "fonsecareyna82/ScipionWeb"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TIMEOUT = 120.0
CONTENT_TYPES = {".zip": "application/zip", ".json": "application/json", ".sh": "text/x-shellscript"}


def githubToken() -> Optional[str]:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("SCIPIONWEB_GITHUB_TOKEN") or "").strip() or None


def headCommit(repoPath: Path) -> str:
    """The commit the release's tag points to: the current one of the ScipionWeb repository."""
    result = subprocess.run(["git", "-C", str(repoPath), "rev-parse", "HEAD"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Could not read the current commit of {repoPath}: {result.stderr.strip()}")
    return result.stdout.strip()


def request(method: str, url: str, token: str, body: Any = None, data: Optional[bytes] = None,
            contentType: str = "application/json") -> Tuple[int, Any]:
    """(status, JSON answer or None); 404 comes back as a status, other errors raise with GitHub's message."""
    payload = data if data is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "scipionapi-cli/release"}
    if payload is not None:
        headers["Content-Type"] = contentType
    try:
        with urlopen(Request(url, data=payload, headers=headers, method=method), timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8") or "null"
            return response.status, json.loads(text)
    except HTTPError as error:
        if error.code == 404:
            return 404, None
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub answered {error.code} to {method} {url}: {detail}") from error


def publishRelease(repo: str, tag: str, files: List[Path], token: str, commit: str, prerelease: bool = True,
                   replace: bool = False, call: Callable[..., Tuple[int, Any]] = request,
                   log: Callable[[str], None] = print) -> str:
    """Publishes `files` as GitHub release `tag` of `repo` and gives its address. An existing release with that
    tag is replaced only with replace=True."""
    status, existing = call("GET", f"{API}/repos/{repo}/releases/tags/{quote(tag)}", token)
    if status != 404 and existing and not replace:
        raise RuntimeError(f"GitHub release {tag} already exists in {repo}. Use --force only when intentionally "
                           "replacing it.")

    replacing = status != 404 and bool(existing)
    # A draft takes its tag when published: while the earlier release holds the tag, it has a provisional one
    log(f"Creating draft release {tag} on {repo}")
    _, draft = call("POST", f"{API}/repos/{repo}/releases", token, body={
        "tag_name": f"{tag}-replacement" if replacing else tag, "target_commitish": commit, "name": f"ScipionWeb {tag}", "draft": True,
        "prerelease": prerelease,
        "body": ("Test release: it is replaced when published again." if prerelease else f"ScipionWeb {tag}.")
        + "\n\nInstall with:\n\n```\ncurl -fsSL -o install.sh "
        f"https://github.com/{repo}/releases/download/{tag}/install.sh\nbash install.sh\n```"})
    for path in files:
        log(f"Uploading {path.name}")
        call("POST", f"{UPLOADS}/repos/{repo}/releases/{draft['id']}/assets?name={quote(path.name)}", token,
             data=path.read_bytes(), contentType=CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

    if replacing:
        log(f"Removing the earlier release {tag}")
        call("DELETE", f"{API}/repos/{repo}/releases/{existing['id']}", token)
        call("DELETE", f"{API}/repos/{repo}/git/refs/tags/{quote(tag)}", token)
    log(f"Publishing release {tag}")
    _, published = call("PATCH", f"{API}/repos/{repo}/releases/{draft['id']}", token,
                        body={"draft": False, "tag_name": tag, "target_commitish": commit,
                              "prerelease": prerelease})
    return str((published or {}).get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}")
