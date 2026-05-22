import base64
import os

import httpx
import yaml
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.models import PRContext, RepoConfig


@activity.defn(name="activities.repo_config.fetch")
async def fetch(pr: PRContext) -> RepoConfig:
    config = await _fetch_from_github(pr.repo)

    # FORCE_AUTO_MERGE=true lets you test the merge path locally before
    # the GitHub App and per-repo config are fully wired up.
    if os.environ.get("FORCE_AUTO_MERGE", "false").lower() == "true":
        config = config.model_copy(update={"auto_merge_enabled": True})

    return config


async def _fetch_from_github(repo: str) -> RepoConfig:
    url = f"https://api.github.com/repos/{repo}/contents/.github/triage-agent.yml"
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code == 404:
        activity.logger.info(f"No .github/triage-agent.yml in {repo} — using defaults")
        return RepoConfig()

    if resp.status_code == 401:
        raise ApplicationError("GitHub auth failed fetching repo config", non_retryable=True)

    resp.raise_for_status()

    content_b64 = resp.json()["content"].replace("\n", "")
    raw = base64.b64decode(content_b64).decode("utf-8")
    data = yaml.safe_load(raw) or {}

    # Only pass fields that RepoConfig actually knows about
    known = {k: v for k, v in data.items() if k in RepoConfig.model_fields}
    config = RepoConfig(**known)
    activity.logger.info(f"Loaded .github/triage-agent.yml from {repo}: {config}")
    return config
