"""Pull request okuma ve COMMENT incelemesi gönderme."""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .review import MARKER, inline_comments, render


class GitHubError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GitHub:
    def __init__(self, repo, pr):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or any(
            part in {".", ".."} for part in repo.split("/")
        ):
            raise GitHubError("Depo adı owner/name biçiminde olmalı.")
        self.token = os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise GitHubError("GitHub erişimi için GITHUB_TOKEN ortam değişkenini ayarlayın.")
        self.url = f"https://api.github.com/repos/{repo}/pulls/{pr}"

    def _request(self, suffix="", *, diff=False, payload=None):
        headers = {"Authorization": f"Bearer {self.token}",
                   "Accept": "application/vnd.github.diff" if diff else "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        request = Request(self.url + suffix, data=body, headers=headers)
        try:
            with urlopen(request, timeout=120) as response:
                return response.read().decode("utf-8", "replace") if diff else json.load(response)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise GitHubError(f"GitHub API isteği başarısız (HTTP {status}).", status) from None
        except (URLError, OSError, ValueError):
            raise GitHubError("GitHub API bağlantısı veya yanıtı geçersiz.") from None

    def info(self):
        data = self._request()
        if not isinstance(data, dict):
            raise GitHubError("GitHub PR bilgisi geçersiz.")
        head = data.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(sha, str) or not sha:
            raise GitHubError("GitHub PR commit kimliğini döndürmedi.")
        return data

    def diff(self):
        return self._request(diff=True)

    def already_reviewed(self, sha):
        page = 1
        while True:
            reviews = self._request(f"/reviews?per_page=100&page={page}")
            if not isinstance(reviews, list):
                raise GitHubError("GitHub inceleme listesi geçersiz.")
            if any(review.get("commit_id") == sha and review.get("state") == "COMMENTED"
                   and MARKER in (review.get("body") or "").splitlines() for review in reviews):
                return True
            if len(reviews) < 100:
                return False
            page += 1

    def post_review(self, sha, report, skipped):
        if self.info()["head"]["sha"] != sha:
            raise GitHubError("PR commit'i inceleme sırasında değişti. Güncel diff ile tekrar deneyin.")
        if self.already_reviewed(sha):
            return False
        comments = inline_comments(report)
        payload = {"commit_id": sha, "event": "COMMENT",
                   "body": render(report, skipped, include_inline=False, marker=True)}
        if comments:
            payload["comments"] = comments
        try:
            self._request("/reviews", payload=payload)
        except GitHubError as exc:
            if exc.status != 422 or not comments:
                raise
            if self.info()["head"]["sha"] != sha:
                raise GitHubError("PR commit'i inceleme sırasında değişti.") from None
            if self.already_reviewed(sha):
                return False
            del payload["comments"]
            payload["body"] = render(report, skipped, marker=True)
            self._request("/reviews", payload=payload)
        return True
