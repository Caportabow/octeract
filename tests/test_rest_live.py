import asyncio
from dataclasses import dataclass, field
from typing import Optional

from octeract import rest, RetryPolicy


@dataclass
class GitHubUser:
    login: str
    id: int
    public_repos: int = 0
    followers: int = 0


@rest("GET", "https://api.github.com/users/{username}", response_model=GitHubUser)
async def get_github_user(username: str) -> GitHubUser: ...


async def main():
    resilient_get_user = get_github_user.with_retry(RetryPolicy(max_attempts=3)).with_timeout(5.0)
    user = await resilient_get_user(username="octocat")
    print("Fetched:", user)
    assert isinstance(user, GitHubUser)
    assert user.login == "octocat"
    print("REST + typed coercion OK")

    # fallback path: nonexistent host -> should not raise, returns fallback
    @rest("GET", "https://this-host-does-not-exist.invalid/x", response_model=GitHubUser)
    async def broken() -> GitHubUser: ...

    safe = broken.with_timeout(2.0).with_fallback(lambda exc: None)
    result = await safe()
    assert result is None
    print("REST fallback-on-network-failure OK")


if __name__ == "__main__":
    asyncio.run(main())
