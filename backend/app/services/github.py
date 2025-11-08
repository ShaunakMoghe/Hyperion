import httpx
from urllib.parse import urlparse

from app.core.config import settings


def parse_github_issue_url(issue_url: str) -> tuple[str, str, int]:
    """Parses a GitHub issue URL to extract owner, repo, and issue number."""
    parsed_url = urlparse(issue_url)
    if parsed_url.hostname != "github.com":
        raise ValueError("URL must be a github.com URL")

    path_parts = parsed_url.path.strip("/").split("/")
    if len(path_parts) < 4 or path_parts[2] != "issues":
        raise ValueError("URL must be a valid GitHub issue URL")

    owner = path_parts[0]
    repo = path_parts[1]
    issue_number = int(path_parts[3])
    return owner, repo, issue_number


async def get_issue(issue_url: str, token: str | None = None) -> dict:
    """Fetches an issue from the GitHub API."""
    try:
        owner, repo, issue_number = parse_github_issue_url(issue_url)
    except ValueError as e:
        raise ValueError(f"Invalid GitHub issue URL: {e}")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Hyperion",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, headers=headers)
        response.raise_for_status()  # Raise an exception for bad status codes

    issue_data = response.json()
    etag = response.headers.get("ETag")

    return {
        "etag": etag,
        "updated_at": issue_data["updated_at"],
        "state": issue_data["state"],
        "labels": [label["name"] for label in issue_data["labels"]],
        "html_url": issue_data["html_url"],
        "title": issue_data["title"],
    }
