from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, Iterable
from urllib.parse import quote

import httpx

from combo_service.config import Settings


LOGGER = logging.getLogger("combo_service.github_releases")


class GitHubReleaseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StagedGitHubAsset:
    asset_id: int
    temporary_name: str
    final_name: str
    size: int


class GitHubReleaseClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.github_release_configured:
            raise GitHubReleaseError("GitHub application release publishing is not configured")
        self.owner = settings.github_release_owner
        self.repo = settings.github_release_repo
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_release_token}",
            "User-Agent": "Combo Service-release-worker",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        timeout = httpx.Timeout(connect=30.0, read=1800.0, write=1800.0, pool=30.0)
        self.api = httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=True,
        )
        self.uploads = httpx.Client(
            base_url="https://uploads.github.com",
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=True,
        )

    def close(self) -> None:
        self.api.close()
        self.uploads.close()

    def ensure_release(
        self,
        *,
        management_id: str,
        tag_name: str,
        title: str,
        notes_markdown: str,
        prerelease: bool,
    ) -> dict[str, Any]:
        body = _managed_release_body(management_id, notes_markdown)
        response = self.api.get(
            f"/repos/{self.owner}/{self.repo}/releases/tags/{quote(tag_name, safe='')}"
        )
        if response.status_code == 404:
            return self._json(
                self.api.post(
                    f"/repos/{self.owner}/{self.repo}/releases",
                    json={
                        "tag_name": tag_name,
                        "name": title,
                        "body": body,
                        "draft": True,
                        "prerelease": prerelease,
                    },
                )
            )
        release = self._json(response)
        if _management_marker(management_id) not in str(release.get("body") or ""):
            raise GitHubReleaseError(
                f"GitHub release tag {tag_name} already exists and is not managed "
                "by this application release"
            )
        return self._json(
            self.api.patch(
                f"/repos/{self.owner}/{self.repo}/releases/{int(release['id'])}",
                json={"name": title, "body": body, "prerelease": prerelease},
            )
        )

    def update_release_metadata(
        self,
        *,
        management_id: str,
        github_release_id: int,
        title: str,
        notes_markdown: str,
    ) -> dict[str, Any]:
        return self._json(
            self.api.patch(
                f"/repos/{self.owner}/{self.repo}/releases/{github_release_id}",
                json={
                    "name": title,
                    "body": _managed_release_body(management_id, notes_markdown),
                },
            )
        )

    def publish_release(
        self,
        *,
        management_id: str,
        github_release_id: int,
        title: str,
        notes_markdown: str,
        prerelease: bool,
    ) -> dict[str, Any]:
        return self._json(
            self.api.patch(
                f"/repos/{self.owner}/{self.repo}/releases/{github_release_id}",
                json={
                    "name": title,
                    "body": _managed_release_body(management_id, notes_markdown),
                    "draft": False,
                    "prerelease": prerelease,
                },
            )
        )

    def stage_asset(
        self,
        *,
        github_release_id: int,
        final_name: str,
        marker: str,
        content_type: str,
        size_bytes: int,
        content: Iterable[bytes],
        progress: Callable[[int], None],
    ) -> StagedGitHubAsset:
        temporary_prefix = f"{final_name}.upload-{marker}-"
        for asset in self.list_assets(github_release_id):
            name = str(asset.get("name") or "")
            if name.startswith(temporary_prefix):
                self.delete_asset(int(asset["id"]))
        temporary_name = f"{temporary_prefix}staged"

        sent = 0

        def counted_content() -> Iterable[bytes]:
            nonlocal sent
            for chunk in content:
                sent += len(chunk)
                progress(sent)
                yield chunk

        response = self.uploads.post(
            f"/repos/{self.owner}/{self.repo}/releases/{github_release_id}/assets",
            params={"name": temporary_name},
            headers={
                "Content-Type": content_type,
                "Content-Length": str(size_bytes),
            },
            content=counted_content(),
        )
        asset = self._json(response)
        if str(asset.get("state") or "") != "uploaded" or int(asset.get("size") or 0) != size_bytes:
            raise GitHubReleaseError(
                f"GitHub asset verification failed for {final_name}: "
                f"state={asset.get('state')} size={asset.get('size')}"
            )
        return StagedGitHubAsset(
            asset_id=int(asset["id"]),
            temporary_name=temporary_name,
            final_name=final_name,
            size=size_bytes,
        )

    def commit_staged_assets(
        self,
        *,
        github_release_id: int,
        staged_assets: list[StagedGitHubAsset],
    ) -> dict[str, dict[str, Any]]:
        self._delete_stale_asset_backups(github_release_id)
        assets = self.list_assets(github_release_id)
        staged_ids = {asset.asset_id for asset in staged_assets}
        current_by_name = {
            str(asset.get("name") or ""): asset
            for asset in assets
            if int(asset.get("id") or 0) not in staged_ids
        }
        committed: dict[str, dict[str, Any]] = {}
        backups: list[tuple[int, str, str]] = []
        promoted: list[StagedGitHubAsset] = []
        try:
            for staged in staged_assets:
                current = current_by_name.get(staged.final_name)
                if current is None:
                    continue
                current_id = int(current["id"])
                backup_name = f"{staged.final_name}.combo-service-backup-{staged.asset_id}"
                renamed_backup = self._json(
                    self.api.patch(
                        f"/repos/{self.owner}/{self.repo}/releases/assets/{current_id}",
                        json={"name": backup_name},
                    )
                )
                if str(renamed_backup.get("name") or "") != backup_name:
                    raise GitHubReleaseError(
                        f"GitHub asset backup failed for {staged.final_name}"
                    )
                backups.append((current_id, staged.final_name, backup_name))

            for staged in staged_assets:
                renamed = self._json(
                    self.api.patch(
                        f"/repos/{self.owner}/{self.repo}/releases/assets/{staged.asset_id}",
                        json={"name": staged.final_name},
                    )
                )
                if (
                    str(renamed.get("name") or "") != staged.final_name
                    or str(renamed.get("state") or "") != "uploaded"
                    or int(renamed.get("size") or 0) != staged.size
                ):
                    raise GitHubReleaseError(
                        f"GitHub asset commit verification failed for {staged.final_name}"
                    )
                promoted.append(staged)
                committed[staged.final_name] = renamed
        except Exception:
            self._rollback_asset_commit(promoted=promoted, backups=backups)
            raise

        self._delete_stale_asset_backups(github_release_id)
        return committed

    def published_assets(
        self,
        *,
        github_release_id: int,
        expected_assets: list[StagedGitHubAsset],
    ) -> dict[str, dict[str, Any]]:
        assets_by_name = {
            str(asset.get("name") or ""): asset
            for asset in self.list_assets(github_release_id)
        }
        published: dict[str, dict[str, Any]] = {}
        for expected in expected_assets:
            asset = assets_by_name.get(expected.final_name)
            if asset is None:
                raise GitHubReleaseError(
                    f"published GitHub asset is missing: {expected.final_name}"
                )
            download_url = str(asset.get("browser_download_url") or "").strip()
            if (
                int(asset.get("id") or 0) != expected.asset_id
                or str(asset.get("state") or "") != "uploaded"
                or int(asset.get("size") or 0) != expected.size
                or not download_url
            ):
                raise GitHubReleaseError(
                    f"published GitHub asset verification failed for {expected.final_name}"
                )
            published[expected.final_name] = asset
        return published

    def _delete_stale_asset_backups(self, github_release_id: int) -> None:
        for asset in self.list_assets(github_release_id):
            if ".combo-service-backup-" not in str(asset.get("name") or ""):
                continue
            self.delete_asset(int(asset["id"]))

    def _rollback_asset_commit(
        self,
        *,
        promoted: list[StagedGitHubAsset],
        backups: list[tuple[int, str, str]],
    ) -> None:
        for staged in reversed(promoted):
            try:
                self.api.patch(
                    f"/repos/{self.owner}/{self.repo}/releases/assets/{staged.asset_id}",
                    json={"name": staged.temporary_name},
                ).raise_for_status()
            except httpx.HTTPError:
                LOGGER.exception(
                    "failed to roll back staged GitHub release asset",
                    extra={"asset_id": staged.asset_id, "asset_name": staged.final_name},
                )
        for asset_id, original_name, _ in reversed(backups):
            try:
                self.api.patch(
                    f"/repos/{self.owner}/{self.repo}/releases/assets/{asset_id}",
                    json={"name": original_name},
                ).raise_for_status()
            except httpx.HTTPError:
                LOGGER.exception(
                    "failed to restore replaced GitHub release asset",
                    extra={"asset_id": asset_id, "asset_name": original_name},
                )

    def list_assets(self, github_release_id: int) -> list[dict[str, Any]]:
        response = self.api.get(
            f"/repos/{self.owner}/{self.repo}/releases/{github_release_id}/assets",
            params={"per_page": 100},
        )
        value = self._json(response)
        if not isinstance(value, list):
            raise GitHubReleaseError("GitHub returned an invalid release asset list")
        return [dict(item) for item in value if isinstance(item, dict)]

    def delete_asset(self, asset_id: int) -> None:
        response = self.api.delete(
            f"/repos/{self.owner}/{self.repo}/releases/assets/{asset_id}"
        )
        if response.status_code != 204:
            self._raise(response)

    def _json(self, response: httpx.Response) -> Any:
        if response.is_error:
            self._raise(response)
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubReleaseError("GitHub returned a non-JSON response") from exc

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = (
            str(payload.get("message") or "").strip()
            if isinstance(payload, dict)
            else ""
        )
        raise GitHubReleaseError(
            f"GitHub API request failed ({response.status_code}): "
            f"{message or response.reason_phrase}"
        )


def _management_marker(management_id: str) -> str:
    return f"<!-- combo_service-app-release:{management_id} -->"


def _managed_release_body(management_id: str, notes_markdown: str) -> str:
    return f"{_management_marker(management_id)}\n\n{notes_markdown}"
