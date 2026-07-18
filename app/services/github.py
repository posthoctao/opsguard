from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.db.models import CodeRepairJob


class PullRequestPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullRequestResult:
    number: int
    url: str
    branch_name: str


class GitHubPullRequestPublisher:
    """通过 GitHub Git Data API 发布已批准的补丁。

    Token 仅由后端持有，不会发送给 Repair Worker，也不会暴露给 Claude。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def publish(
        self,
        job: CodeRepairJob,
        title: str | None = None,
        body: str | None = None,
    ) -> PullRequestResult:
        if not self.settings.github_pr_enabled:
            raise PullRequestPublishError("GitHub PR 发布功能当前已关闭。")
        if not self.settings.github_token or not self.settings.github_repository:
            raise PullRequestPublishError(
                "发布 PR 必须配置 GITHUB_TOKEN 和 GITHUB_REPOSITORY。"
            )
        if not job.file_changes:
            raise PullRequestPublishError("代码修复任务不包含任何文件变更。")

        repo = self.settings.github_repository
        base_branch = self.settings.github_base_branch
        branch_name = f"ai-repair/{job.id[:8]}"
        headers = {
            "Authorization": f"Bearer {self.settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        base_url = self.settings.github_api_url.rstrip("/")

        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60.0) as client:
            base_ref = await self._request(
                client, "GET", f"/repos/{repo}/git/ref/heads/{base_branch}"
            )
            base_sha = base_ref["object"]["sha"]
            base_commit = await self._request(
                client, "GET", f"/repos/{repo}/git/commits/{base_sha}"
            )
            base_tree_sha = base_commit["tree"]["sha"]

            tree_entries: list[dict[str, Any]] = []
            for change in job.file_changes:
                blob = await self._request(
                    client,
                    "POST",
                    f"/repos/{repo}/git/blobs",
                    json={"content": change["content"], "encoding": "utf-8"},
                )
                tree_entries.append(
                    {
                        "path": change["path"],
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob["sha"],
                    }
                )

            tree = await self._request(
                client,
                "POST",
                f"/repos/{repo}/git/trees",
                json={"base_tree": base_tree_sha, "tree": tree_entries},
            )
            commit = await self._request(
                client,
                "POST",
                f"/repos/{repo}/git/commits",
                json={
                    "message": title or f"修复 Incident {job.incident_id[:8]}",
                    "tree": tree["sha"],
                    "parents": [base_sha],
                },
            )
            await self._request(
                client,
                "POST",
                f"/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": commit["sha"]},
            )
            pull = await self._request(
                client,
                "POST",
                f"/repos/{repo}/pulls",
                json={
                    "title": title or f"Incident {job.incident_id[:8]} 的 AI 修复补丁",
                    "head": branch_name,
                    "base": base_branch,
                    "body": body
                    or (
                        f"这是针对 Incident `{job.incident_id}` 自动生成的候选修复补丁。\n\n"
                        "该补丁在隔离式 Worker 中生成，并已通过后端配置的测试。"
                        "合并前仍需人工审核。"
                    ),
                },
            )

        return PullRequestResult(
            number=int(pull["number"]),
            url=str(pull["html_url"]),
            branch_name=branch_name,
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await client.request(method, path, json=json)
        if response.status_code >= 400:
            raise PullRequestPublishError(
                f"GitHub API 请求失败：{method} {path}，状态码 {response.status_code}，响应 {response.text[:1000]}"
            )
        return dict(response.json())
