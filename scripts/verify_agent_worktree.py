"""Verify the delegated-agent worktree isolation boundary.

Everything runs inside temporary Git repositories and a temporary runtime
database; the real workspace is never touched. Covered behaviour:

* deterministic identity and unsafe task ids are rejected
* worktree names come from the child agent's name, and old task-id names still resolve
* create/lookup/require, duplicate refusal, half-finished create rollback
* uncommitted main-workspace changes are not carried into a new tree
* a removed tree fails loudly instead of falling back to the shared workspace
* registry filtering (branch prefix plus worktrees root) excludes unrelated trees
* legacy sidecar recognition and one-shot consumption
* an already ignored worktrees root is not appended to ``.git/info/exclude``
* startup migration survives an unresolvable workspace and converges
* a worktree child gets its own process manager instead of a session-keyed one

Run with: .venv/bin/python scripts/verify_agent_worktree.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from combo.agent_worktree import (
    AGENT_BRANCH_PREFIX,
    AgentWorktreeManager,
    InvalidTaskId,
    WorktreeError,
    WorktreeExists,
    worktree_label,
)
from combo.dynamic_runtime.database import DynamicRuntimeDatabase, DynamicRuntimeMigrationRegistry
from combo.dynamic_runtime.delegation_store import DelegationStore
from combo.dynamic_runtime.runtime_infrastructure import SessionProcessResourcePool

LEGACY_SUFFIX = ".combo-agent-task.json"
NOW = "2026-01-01T00:00:00+00:00"
SHARED_TASK = "a1b2c3d4e5f60718"
LEGACY_TREE_TASK = "b2c3d4e5f6071829"
LABEL_TREE_TASK = "c3d4e5f607182930"
MISSING_TASK = "d4e5f60718293041"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="combo-worktree-verify-") as tmp:
        base = Path(tmp).resolve()
        _verify_identity(base / "identity")
        _verify_label_naming(base / "label")
        _verify_create_and_rollback(base / "create")
        _verify_missing_tree_is_loud(base / "missing")
        _verify_registry_filtering(base / "listing")
        _verify_legacy_sidecar(base / "legacy")
        _verify_ignore_handling(base / "ignored", base / "unignored")
        _verify_startup_migration(base / "migration")
        _verify_process_pool_roots(base / "pool-a", base / "pool-b")
    print("agent worktree verification passed")


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=str(repo), capture_output=True, text=True, check=False
    )


def _init_repo(path: Path, *, ignore_combo: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "verify@example.com")
    _git(path, "config", "user.name", "Verify")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    if ignore_combo:
        (path / ".gitignore").write_text(".combo/\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _branches(repo: Path) -> set[str]:
    listed = _git(repo, "branch", "--list", "--format=%(refname:short)").stdout
    return {line.strip() for line in listed.splitlines() if line.strip()}


def _write_sidecar(
    sidecar: Path,
    manager: AgentWorktreeManager,
    task_id: str,
    *,
    base_commit: str,
    label: str | None = None,
) -> None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "branch": manager.expected_branch(task_id, label=label),
                "path": str(manager.expected_path(task_id, label=label)),
                "base_commit": base_commit,
            }
        ),
        encoding="utf-8",
    )


def _verify_identity(root: Path) -> None:
    repo = _init_repo(root)
    manager = AgentWorktreeManager(repository=repo)
    assert manager.is_repository() is True
    assert manager.worktrees_root == repo / ".combo" / "worktrees"
    assert manager.expected_branch("task-a") == f"{AGENT_BRANCH_PREFIX}task-a"
    assert manager.expected_path("task-a") == repo / ".combo" / "worktrees" / "task-a"
    assert manager.expected_branch("task-a", label="researcher-abc123") == (
        f"{AGENT_BRANCH_PREFIX}researcher-abc123"
    )

    for unsafe in ("../escape", "a/b", "", "..", ".hidden", "-dash", "with space", "x" * 65):
        try:
            manager.expected_branch(unsafe)
        except InvalidTaskId:
            continue
        raise AssertionError(f"unsafe task id accepted: {unsafe!r}")

    plain = root / "not-a-repo"
    plain.mkdir()
    assert AgentWorktreeManager(repository=plain).is_repository() is False


def _verify_label_naming(root: Path) -> None:
    repo = _init_repo(root)
    manager = AgentWorktreeManager(repository=repo)
    task_id = uuid4().hex

    # The label is the child's own name plus a short slice of the task identity.
    assert worktree_label(task_id, "Researcher") == f"researcher-{task_id[:6]}"
    assert worktree_label(task_id, "Presentation Designer") == f"presentation-designer-{task_id[:6]}"
    assert worktree_label(task_id, "  研究员  ") == f"研究员-{task_id[:6]}"
    assert worktree_label(task_id, "research/v2: final!") == f"research-v2-final-{task_id[:6]}"
    assert worktree_label(task_id, None) == f"agent-{task_id[:6]}"
    assert worktree_label(task_id, "x" * 80) == f"{'x' * 24}-{task_id[:6]}"
    assert len(worktree_label(task_id, "Research Assistant For The Long Task")) < 40

    label = worktree_label(task_id, "Researcher")
    worktree = manager.create(task_id, label=label)
    assert worktree.label == label
    assert worktree.task_id == task_id
    assert worktree.branch == f"{AGENT_BRANCH_PREFIX}{label}"
    assert worktree.path.name == label
    assert worktree.path.is_dir()

    # A continuation resolves the same tree, and the registry scan reports labels.
    resumed = manager.require(task_id, label=label)
    assert (resumed.path, resumed.branch) == (worktree.path, worktree.branch)
    assert [item.label for item in manager.list_worktrees()] == [label]

    # Trees created before this naming are still found through the task id.
    legacy_task = uuid4().hex
    legacy = manager.create(legacy_task)
    assert legacy.label == legacy_task
    recovered = manager.require(legacy_task, label=worktree_label(legacy_task, "Researcher"))
    assert recovered.path == legacy.path
    assert recovered.label == legacy_task

    # Two children with the same name never share a tree identity.
    other_task = uuid4().hex
    assert worktree_label(other_task, "Researcher") != label
    manager.create(other_task, label=worktree_label(other_task, "Researcher"))

    for unsafe in ("../escape", "a/b", "/absolute", "a b", "a:b", ".."):
        try:
            manager.expected_branch(task_id, label=unsafe)
        except InvalidTaskId:
            continue
        raise AssertionError(f"unsafe worktree label accepted: {unsafe!r}")


def _verify_create_and_rollback(root: Path) -> None:
    repo = _init_repo(root)
    manager = AgentWorktreeManager(repository=repo)
    worktree = manager.create("t1")
    assert worktree.path.is_dir(), worktree
    assert worktree.path == manager.expected_path("t1").resolve()
    assert worktree.branch in _branches(repo)
    assert worktree.base_commit == _head(repo)
    assert (worktree.path / "f.txt").read_text(encoding="utf-8") == "base\n"

    for _ in range(2):
        try:
            manager.create("t1")
        except WorktreeExists:
            continue
        raise AssertionError("duplicate create did not raise WorktreeExists")

    # A pre-existing branch belongs to somebody else: refuse and never delete it.
    _git(repo, "branch", f"{AGENT_BRANCH_PREFIX}t2")
    try:
        manager.create("t2")
    except WorktreeExists:
        pass
    else:
        raise AssertionError("existing branch did not raise WorktreeExists")
    assert f"{AGENT_BRANCH_PREFIX}t2" in _branches(repo)
    assert not manager.expected_path("t2").exists()

    # Uncommitted main-workspace changes must not reach the child's starting point.
    (repo / "f.txt").write_text("uncommitted\n", encoding="utf-8")
    dirty_tree = manager.create("t3")
    assert (dirty_tree.path / "f.txt").read_text(encoding="utf-8") == "base\n"
    (repo / "f.txt").write_text("base\n", encoding="utf-8")

    manager.cleanup_create_failure(dirty_tree)
    assert not dirty_tree.path.exists()
    assert dirty_tree.branch not in _branches(repo)
    assert manager.lookup("t3") is None
    manager.cleanup_create_failure(worktree)
    assert not worktree.path.exists()
    assert worktree.branch not in _branches(repo)
    assert manager.list_worktrees() == ()


def _verify_missing_tree_is_loud(root: Path) -> None:
    repo = _init_repo(root)
    manager = AgentWorktreeManager(repository=repo)
    try:
        manager.require("absent")
    except WorktreeError:
        pass
    else:
        raise AssertionError("require() resolved an unregistered worktree")
    assert manager.lookup("absent") is None

    worktree = manager.create("t4")
    shutil.rmtree(worktree.path)
    try:
        manager.require("t4")
    except WorktreeError:
        pass
    else:
        raise AssertionError("require() silently accepted a removed worktree directory")

    _git(repo, "worktree", "prune")
    assert manager.lookup("t4") is None


def _verify_registry_filtering(root: Path) -> None:
    repo = _init_repo(root)
    manager = AgentWorktreeManager(repository=repo)
    kept = {manager.create("t5").label, manager.create("t6").label}
    stale = manager.create("t7")
    shutil.rmtree(stale.path)  # registration without a directory, as after a manual delete
    named = manager.create("t8", label="researcher-123456")

    outside = repo.parent / "outside-tree"
    feature = repo.parent / "feature-tree"
    _git(repo, "worktree", "add", "-q", "-b", f"{AGENT_BRANCH_PREFIX}outside", str(outside), "HEAD")
    _git(repo, "worktree", "add", "-q", "-b", "feature/other", str(feature), "HEAD")

    listed = {item.label for item in manager.list_worktrees()}
    # Combo-prefixed branches outside the worktrees root and unrelated branches stay out.
    assert listed == kept | {stale.label, named.label}, listed
    assert "researcher-123456" in listed
    assert outside not in {item.path for item in manager.list_worktrees()}
    assert feature not in {item.path for item in manager.list_worktrees()}
    assert "outside" not in listed and "other" not in listed


def _verify_legacy_sidecar(root: Path) -> None:
    repo = _init_repo(root)
    manager = AgentWorktreeManager(repository=repo)

    sidecar = manager.worktrees_root / f"legacy1{LEGACY_SUFFIX}"
    _write_sidecar(sidecar, manager, "legacy1", base_commit="0" * 40)
    consumed = manager.consume_legacy_worktree("legacy1")
    assert consumed is not None and consumed.path == manager.expected_path("legacy1").resolve()
    assert not sidecar.exists(), "a consumed sidecar must be removed"
    assert manager.consume_legacy_worktree("legacy1") is None, "a sidecar is consumed once"

    # A sidecar that describes something else grants nothing.
    stray = manager.worktrees_root / f"stray{LEGACY_SUFFIX}"
    stray.write_text(
        json.dumps(
            {
                "task_id": "stray",
                "branch": f"{AGENT_BRANCH_PREFIX}stray",
                "path": str(repo / "elsewhere"),
            }
        ),
        encoding="utf-8",
    )
    assert manager.consume_legacy_worktree("stray") is None
    assert not stray.exists()

    # A plain directory plus a stale sidecar is not a worktree.
    manager.expected_path("legacy3").mkdir(parents=True)
    _write_sidecar(
        manager.worktrees_root / f"legacy3{LEGACY_SUFFIX}", manager, "legacy3", base_commit=_head(repo)
    )
    assert manager.consume_legacy_worktree("legacy3") is None

    # A registered tree is recognised without trusting sidecar contents.
    worktree = manager.create("legacy2")
    _write_sidecar(
        manager.worktrees_root / f"legacy2{LEGACY_SUFFIX}", manager, "legacy2", base_commit=_head(repo)
    )
    registered = manager.consume_legacy_worktree("legacy2")
    assert registered is not None and registered.path == worktree.path


def _verify_ignore_handling(ignored_root: Path, unignored_root: Path) -> None:
    ignored = _init_repo(ignored_root, ignore_combo=True)
    exclude = ignored / ".git" / "info" / "exclude"
    before = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    AgentWorktreeManager(repository=ignored).create("t8")
    after = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    assert after == before, "an already ignored worktrees root was appended to .git/info/exclude"
    assert _git(ignored, "check-ignore", "-q", "--", ".combo/worktrees/t8").returncode == 0

    plain = _init_repo(unignored_root)
    manager = AgentWorktreeManager(repository=plain)
    manager.create("t9")
    exclude = plain / ".git" / "info" / "exclude"
    content = exclude.read_text(encoding="utf-8")
    assert "/.combo/worktrees/" in content.splitlines(), content
    manager.create("t10")
    assert exclude.read_text(encoding="utf-8") == content, "exclude entry must be written once"
    assert _git(plain, "check-ignore", "-q", "--", ".combo/worktrees/t9").returncode == 0


def _verify_startup_migration(root: Path) -> None:
    repo = _init_repo(root / "repo")
    database_path = root / "runtime.sqlite"
    database = DynamicRuntimeDatabase(database_path)
    DynamicRuntimeMigrationRegistry().migrate(database)

    manager = AgentWorktreeManager(repository=repo)
    agent_name = "Data Miner"
    # Legacy layout: the sidecar and tree are named after the bare task id.
    legacy_sidecar = manager.worktrees_root / f"{LEGACY_TREE_TASK}{LEGACY_SUFFIX}"
    _write_sidecar(legacy_sidecar, manager, LEGACY_TREE_TASK, base_commit=_head(repo))
    # New layout: the sidecar is named after the label built from the child name.
    label_sidecar = manager.worktrees_root / (
        f"{worktree_label(LABEL_TREE_TASK, agent_name)}{LEGACY_SUFFIX}"
    )
    _write_sidecar(
        label_sidecar,
        manager,
        LABEL_TREE_TASK,
        base_commit=_head(repo),
        label=worktree_label(LABEL_TREE_TASK, agent_name),
    )

    with sqlite3.connect(str(database_path)) as conn:
        for runtime_id in ("rt-shared", "rt-missing", "rt-legacy", "rt-label"):
            conn.execute(
                "insert into runtime_instances (runtime_instance_id, request_id, session_id, turn_id,"
                " capability_snapshot_id, status, payload_json, created_at, updated_at)"
                " values (?, ?, 's1', 'turn-1', 'snap-1', 'queued', ?, ?, ?)",
                (
                    runtime_id,
                    f"req-{runtime_id}",
                    json.dumps({"request": {"session_id": "s1", "principal_id": "p1"}}),
                    NOW,
                    NOW,
                ),
            )
        for task_id, child_id, workspace_id, grant_id, stored_name in (
            (SHARED_TASK, "rt-shared", "ws-ok", "grant-shared", agent_name),
            (MISSING_TASK, "rt-missing", "ws-missing", "grant-missing", agent_name),
            (LEGACY_TREE_TASK, "rt-legacy", "ws-ok", "grant-legacy", agent_name),
            (LABEL_TREE_TASK, "rt-label", "ws-ok", "grant-label", agent_name),
        ):
            conn.execute(
                "insert into delegated_task_revisions (task_id, task_revision, parent_task_revision,"
                " principal_id, parent_runtime_instance_id, child_runtime_instance_id,"
                " delegation_grant_id, capability_snapshot_id, workspace_id, status, payload_json,"
                " created_at, updated_at)"
                " values (?, 1, 1, 'p1', 'rt-parent', ?, ?, 'snap-1', ?, 'queued', ?, ?, ?)",
                (
                    task_id,
                    child_id,
                    grant_id,
                    workspace_id,
                    json.dumps({"task_id": task_id, "agent_name": stored_name}),
                    NOW,
                    NOW,
                ),
            )

    calls: list[str] = []

    def resolver(workspace_id: str, principal_id: str) -> str:
        calls.append(workspace_id)
        if workspace_id == "ws-missing":
            raise FileNotFoundError("workspace mount is unavailable")
        return str(repo)

    store = DelegationStore(database)
    assert store.migrate_legacy_workspace_modes(resolver) == 3
    assert calls.count("ws-ok") == 3, calls
    assert "ws-missing" in calls, calls

    task_modes = _stored_modes(database_path, "delegated_task_revisions")
    assert task_modes[SHARED_TASK] == "shared", task_modes
    assert task_modes[LEGACY_TREE_TASK] == "worktree", task_modes
    assert task_modes[LABEL_TREE_TASK] == "worktree", task_modes
    assert MISSING_TASK not in task_modes, task_modes
    assert not legacy_sidecar.exists(), "migration must consume legacy sidecars"
    assert not label_sidecar.exists(), "migration must consume label sidecars"

    request_modes = _stored_modes(database_path, "runtime_instances", nested="request")
    assert request_modes["rt-shared"] == "shared", request_modes
    assert request_modes["rt-legacy"] == "worktree", request_modes
    assert request_modes["rt-label"] == "worktree", request_modes
    assert "rt-missing" not in request_modes, request_modes

    # A workspace that cannot be resolved is retried, everything else converges.
    calls.clear()
    assert store.migrate_legacy_workspace_modes(resolver) == 0
    assert calls == ["ws-missing"], calls
    assert _stored_modes(database_path, "delegated_task_revisions") == task_modes


def _stored_modes(path: Path, table: str, *, nested: str | None = None) -> dict[str, str]:
    key_column = {"delegated_task_revisions": "task_id", "runtime_instances": "runtime_instance_id"}[
        table
    ]
    modes: dict[str, str] = {}
    with sqlite3.connect(str(path)) as conn:
        for key, payload_json in conn.execute(f"select {key_column}, payload_json from {table}"):
            payload = json.loads(payload_json)
            scope = payload.get(nested) if nested else payload
            if isinstance(scope, dict) and "workspace_mode" in scope:
                modes[str(key)] = str(scope["workspace_mode"])
    return modes


def _pool_instance(session_id: str, principal_id: str) -> SimpleNamespace:
    return SimpleNamespace(request=SimpleNamespace(session_id=session_id, principal_id=principal_id))


def _verify_process_pool_roots(first_root: Path, second_root: Path) -> None:
    first_root.mkdir(parents=True, exist_ok=True)
    second_root.mkdir(parents=True, exist_ok=True)
    pool = SessionProcessResourcePool(environment=dict(os.environ))
    instance = _pool_instance("session-1", "principal-1")
    shared_child = _pool_instance("session-1", "principal-1")
    try:
        parent = pool.acquire(instance, root=first_root)
        child = pool.acquire(shared_child, root=second_root)
        assert parent.value.manager is not child.value.manager
        assert parent.value.root == first_root.resolve()
        assert child.value.root == second_root.resolve()

        again = pool.acquire(instance, root=first_root)
        assert again.value is parent.value, "the same session and root must reuse one manager"

        try:
            pool.close_sessions(("session-1",))
        except RuntimeError:
            pass
        else:
            raise AssertionError("close_sessions() ignored leased process resources")

        for resource in (parent, child, again):
            resource.release_callback()
        pool.close_sessions(("session-1",))
    finally:
        pool.close()


if __name__ == "__main__":
    main()
