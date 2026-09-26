use git2::{
    build::{CheckoutBuilder, RepoBuilder},
    Cred, CredentialType, Diff, DiffDelta, DiffOptions, FetchOptions, IndexAddOption, ObjectType,
    Patch, RemoteCallbacks, Repository, Signature, Status, StatusOptions,
};
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};
use tauri::Emitter;

use crate::github_account::github_access_token;

mod remote;
mod turn;
use remote::run_remote_operation;
use turn::{
    create_worktree_snapshot, filesystem_bytes, reference_key, reference_target,
    snapshot_reference, snapshot_tree, tree_file_bytes, turn_changes,
};

const MAX_DIFF_TEXT_BYTES: usize = 2 * 1024 * 1024;
const PULL_REQUIRES_CLEAN_WORKTREE: &str = "git_pull_requires_clean_worktree";
// Runtime attachment storage, defined by workspace_attachment_root in runtime_attachments.py.
const WORKSPACE_INPUT_DIRECTORY: &str = ".agent/input_files";

#[derive(Serialize)]
pub struct GitRepositoryStatus {
    repository_root: String,
    branch: Option<String>,
    detached: bool,
    has_head: bool,
    ahead: usize,
    behind: usize,
    remote_name: Option<String>,
    remote_url: Option<String>,
    has_upstream: bool,
    files: Vec<GitFileStatus>,
}

#[derive(Serialize)]
pub struct GitRepositoryIdentity {
    name: Option<String>,
    email: Option<String>,
    configured: bool,
}

#[derive(Serialize)]
pub struct GitRepositoryBranch {
    name: String,
    current: bool,
}

#[derive(Serialize)]
pub struct GitRemoteOperationResult {
    outcome: String,
    conflicting_files: Vec<String>,
    status: GitRepositoryStatus,
}

#[derive(Clone, Serialize)]
pub struct GitFileStatus {
    path: String,
    change_type: String,
    staged: bool,
    unstaged: bool,
    additions: usize,
    deletions: usize,
}

#[derive(Serialize)]
pub struct GitTurnChanges {
    request_id: String,
    repository_root: String,
    files: Vec<GitFileChange>,
    additions: usize,
    deletions: usize,
}

#[derive(Clone, Serialize)]
pub struct GitFileChange {
    old_path: Option<String>,
    path: String,
    change_type: String,
    additions: usize,
    deletions: usize,
    binary: bool,
}

#[derive(Serialize)]
pub struct GitFileDiff {
    old_path: Option<String>,
    path: String,
    old_content: String,
    new_content: String,
    binary: bool,
    truncated: bool,
}

#[derive(Serialize)]
pub struct GitTurnApplyResult {
    applied: bool,
    affected_files: Vec<String>,
    conflicting_files: Vec<String>,
}

#[derive(Clone, Serialize)]
pub struct GitCloneProgress {
    stage: String,
    received_objects: usize,
    total_objects: usize,
    indexed_objects: usize,
    received_bytes: usize,
}

#[derive(Serialize)]
pub struct GitCloneResult {
    repository_root: String,
    branch: Option<String>,
}

#[tauri::command]
pub async fn git_clone_repository(
    app: tauri::AppHandle,
    remote_url: String,
    destination_parent: String,
    directory_name: String,
    branch: Option<String>,
) -> Result<GitCloneResult, String> {
    let token = github_access_token().ok();
    tauri::async_runtime::spawn_blocking(move || {
        clone_repository(
            app,
            remote_url,
            destination_parent,
            directory_name,
            branch,
            token,
        )
    })
    .await
    .map_err(error_text)?
}

#[tauri::command]
pub fn git_repository_status(path: String) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    repository_status(&repo)
}

#[tauri::command]
pub fn git_repository_branches(path: String) -> Result<Vec<GitRepositoryBranch>, String> {
    let repo = discover_repository(&path)?;
    let current = repo.head().ok().and_then(|head| {
        head.is_branch()
            .then(|| head.shorthand().map(str::to_string))
            .flatten()
    });
    let mut branches = Vec::new();
    for candidate in repo
        .branches(Some(git2::BranchType::Local))
        .map_err(error_text)?
    {
        let (branch, _) = candidate.map_err(error_text)?;
        let Some(name) = branch.name().map_err(error_text)? else {
            continue;
        };
        branches.push(GitRepositoryBranch {
            name: name.to_string(),
            current: current.as_deref() == Some(name),
        });
    }
    branches.sort_by(|left, right| left.name.cmp(&right.name));
    Ok(branches)
}

#[tauri::command]
pub fn git_switch_branch(path: String, branch: String) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    let branch_name = required_value(&branch, "branch name")?;
    let local_branch = repo
        .find_branch(branch_name, git2::BranchType::Local)
        .map_err(|_| format!("local branch was not found: {branch_name}"))?;
    let target = local_branch
        .get()
        .peel(ObjectType::Commit)
        .map_err(error_text)?;
    let mut checkout = CheckoutBuilder::new();
    checkout.safe();
    repo.checkout_tree(&target, Some(&mut checkout))
        .map_err(error_text)?;
    repo.set_head(&format!("refs/heads/{branch_name}"))
        .map_err(error_text)?;
    repository_status(&repo)
}

#[tauri::command]
pub fn git_initialize_repository(path: String) -> Result<GitRepositoryStatus, String> {
    let candidate = workspace_directory(&path)?;
    let repo = match Repository::discover(&candidate) {
        Ok(existing) => existing,
        Err(_) => Repository::init(&candidate).map_err(error_text)?,
    };
    repository_status(&repo)
}

#[tauri::command]
pub fn git_add_remote(path: String, remote_url: String) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    let remote_url = required_value(&remote_url, "remote URL")?;
    if repo.find_remote("origin").is_ok() {
        return Err("origin remote already exists".to_string());
    }
    repo.remote("origin", remote_url).map_err(error_text)?;
    repository_status(&repo)
}

#[tauri::command]
pub fn git_repository_identity(path: String) -> Result<GitRepositoryIdentity, String> {
    let repo = discover_repository(&path)?;
    repository_identity(&repo)
}

#[tauri::command]
pub fn git_set_repository_identity(
    path: String,
    name: String,
    email: String,
) -> Result<GitRepositoryIdentity, String> {
    let repo = discover_repository(&path)?;
    let name = required_value(&name, "Git author name")?;
    let email = required_value(&email, "Git author email")?;
    let mut config = repo.config().map_err(error_text)?;
    config.set_str("user.name", name).map_err(error_text)?;
    config.set_str("user.email", email).map_err(error_text)?;
    repository_identity(&repo)
}

#[tauri::command]
pub fn git_stage_paths(
    path: String,
    file_paths: Vec<String>,
) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    let root = repository_root(&repo)?.to_path_buf();
    let relative_paths = validated_paths(file_paths)?;
    let mut index = repo.index().map_err(error_text)?;
    for relative in relative_paths {
        if root.join(&relative).is_file() {
            index.add_path(&relative).map_err(error_text)?;
        } else {
            index.remove_path(&relative).map_err(error_text)?;
        }
    }
    index.write().map_err(error_text)?;
    repository_status(&repo)
}

#[tauri::command]
pub fn git_stage_all(path: String) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    let mut index = repo.index().map_err(error_text)?;
    index
        .add_all(["*"], IndexAddOption::DEFAULT, None)
        .map_err(error_text)?;
    index.update_all(["*"], None).map_err(error_text)?;
    index.write().map_err(error_text)?;
    repository_status(&repo)
}

#[tauri::command]
pub fn git_unstage_paths(
    path: String,
    file_paths: Vec<String>,
) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    let paths = validated_paths(file_paths)?;
    let head = repo
        .head()
        .ok()
        .and_then(|reference| reference.peel(ObjectType::Commit).ok());
    repo.reset_default(
        head.as_ref(),
        paths
            .iter()
            .map(|value| value.to_string_lossy().into_owned()),
    )
    .map_err(error_text)?;
    repository_status(&repo)
}

#[tauri::command]
pub fn git_commit(path: String, message: String) -> Result<GitRepositoryStatus, String> {
    let repo = discover_repository(&path)?;
    commit_index(&repo, required_value(&message, "commit message")?)?;
    repository_status(&repo)
}

#[tauri::command]
pub async fn git_fetch_repository(path: String) -> Result<GitRemoteOperationResult, String> {
    run_remote_operation(path, RemoteOperation::Fetch).await
}

#[tauri::command]
pub async fn git_pull_repository(path: String) -> Result<GitRemoteOperationResult, String> {
    run_remote_operation(path, RemoteOperation::Pull).await
}

#[tauri::command]
pub async fn git_push_repository(path: String) -> Result<GitRemoteOperationResult, String> {
    run_remote_operation(path, RemoteOperation::Push).await
}

#[tauri::command]
pub async fn git_sync_repository(path: String) -> Result<GitRemoteOperationResult, String> {
    run_remote_operation(path, RemoteOperation::Sync).await
}

fn repository_status(repo: &Repository) -> Result<GitRepositoryStatus, String> {
    let root = repository_root(&repo)?;
    let (branch, detached, ahead, behind) = branch_state(&repo)?;
    let remote = branch
        .as_deref()
        .map(|branch_name| remote_tracking(repo, branch_name))
        .transpose()?
        .flatten();
    let line_counts = working_tree_line_counts(&repo)?;
    let mut status_options = StatusOptions::new();
    status_options
        .include_untracked(true)
        .recurse_untracked_dirs(true)
        .renames_head_to_index(true)
        .renames_index_to_workdir(true);
    let statuses = repo
        .statuses(Some(&mut status_options))
        .map_err(error_text)?;
    let mut files = Vec::new();
    for entry in statuses.iter() {
        let Some(relative) = entry.path() else {
            continue;
        };
        let state = entry.status();
        let (additions, deletions) = line_counts.get(relative).copied().unwrap_or_default();
        files.push(GitFileStatus {
            path: relative.to_string(),
            change_type: status_label(state).to_string(),
            staged: state.intersects(
                Status::INDEX_NEW
                    | Status::INDEX_MODIFIED
                    | Status::INDEX_DELETED
                    | Status::INDEX_RENAMED
                    | Status::INDEX_TYPECHANGE,
            ),
            unstaged: state.intersects(
                Status::WT_NEW
                    | Status::WT_MODIFIED
                    | Status::WT_DELETED
                    | Status::WT_RENAMED
                    | Status::WT_TYPECHANGE,
            ),
            additions,
            deletions,
        });
    }
    files.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(GitRepositoryStatus {
        repository_root: path_text(root),
        branch,
        detached,
        has_head: repo.head().ok().and_then(|head| head.target()).is_some(),
        ahead,
        behind,
        remote_name: remote.as_ref().map(|value| value.name.clone()),
        remote_url: remote.as_ref().and_then(|value| value.url.clone()),
        has_upstream: remote.as_ref().is_some_and(|value| value.has_upstream),
        files,
    })
}

#[tauri::command]
pub fn git_begin_turn_snapshot(
    path: String,
    request_id: String,
    phase: String,
) -> Result<GitTurnChanges, String> {
    if phase != "before" && phase != "after" {
        return Err("snapshot phase must be before or after".to_string());
    }
    let repo = discover_repository(&path)?;
    let request_key = reference_key(&request_id)?;
    let before_reference = snapshot_reference(&request_key, "before");
    let reference = snapshot_reference(&request_key, &phase);
    let parent = if phase == "after" {
        Some(reference_target(&repo, &before_reference)?)
    } else {
        repo.head().ok().and_then(|head| head.target())
    };
    create_worktree_snapshot(&repo, &reference, parent, &request_id, &phase)?;
    if phase == "before" {
        return Ok(GitTurnChanges {
            request_id,
            repository_root: path_text(repository_root(&repo)?),
            files: Vec::new(),
            additions: 0,
            deletions: 0,
        });
    }
    turn_changes(&repo, &request_id, &request_key)
}

#[tauri::command]
pub fn git_turn_changes(path: String, request_id: String) -> Result<GitTurnChanges, String> {
    let repo = discover_repository(&path)?;
    let request_key = reference_key(&request_id)?;
    turn_changes(&repo, &request_id, &request_key)
}

#[tauri::command]
pub fn git_repository_diff(
    path: String,
    request_id: String,
    file_path: String,
) -> Result<GitFileDiff, String> {
    let repo = discover_repository(&path)?;
    let request_key = reference_key(&request_id)?;
    let before = snapshot_tree(&repo, &snapshot_reference(&request_key, "before"))?;
    let after = snapshot_tree(&repo, &snapshot_reference(&request_key, "after"))?;
    let requested = safe_relative_path(&file_path)?;
    let diff = repo
        .diff_tree_to_tree(Some(&before), Some(&after), None)
        .map_err(error_text)?;
    let delta = diff
        .deltas()
        .find(|delta| {
            delta.new_file().path() == Some(requested.as_path())
                || delta.old_file().path() == Some(requested.as_path())
        })
        .ok_or_else(|| "file is not part of this turn".to_string())?;
    let old_path = delta.old_file().path().map(Path::to_path_buf);
    let new_path = delta.new_file().path().map(Path::to_path_buf);
    let old_content = old_path
        .as_deref()
        .map(|path| tree_file_bytes(&repo, &before, path))
        .transpose()?
        .flatten();
    let new_content = new_path
        .as_deref()
        .map(|path| tree_file_bytes(&repo, &after, path))
        .transpose()?
        .flatten();
    let binary = old_content
        .as_deref()
        .is_some_and(|value| value.contains(&0))
        || new_content
            .as_deref()
            .is_some_and(|value| value.contains(&0));
    let old_bytes = old_content.unwrap_or_default();
    let new_bytes = new_content.unwrap_or_default();
    let truncated = old_bytes.len() > MAX_DIFF_TEXT_BYTES || new_bytes.len() > MAX_DIFF_TEXT_BYTES;
    Ok(GitFileDiff {
        old_path: old_path.map(|path| path.to_string_lossy().replace('\\', "/")),
        path: new_path
            .unwrap_or(requested)
            .to_string_lossy()
            .replace('\\', "/"),
        old_content: visible_text(&old_bytes),
        new_content: visible_text(&new_bytes),
        binary,
        truncated,
    })
}

#[tauri::command]
pub fn git_revert_turn(path: String, request_id: String) -> Result<GitTurnApplyResult, String> {
    let repo = discover_repository(&path)?;
    let request_key = reference_key(&request_id)?;
    apply_turn_snapshot(&repo, &request_key, "after", "before")
}

#[tauri::command]
pub fn git_reapply_turn(path: String, request_id: String) -> Result<GitTurnApplyResult, String> {
    let repo = discover_repository(&path)?;
    let request_key = reference_key(&request_id)?;
    apply_turn_snapshot(&repo, &request_key, "before", "after")
}

fn apply_turn_snapshot(
    repo: &Repository,
    request_key: &str,
    expected_phase: &str,
    target_phase: &str,
) -> Result<GitTurnApplyResult, String> {
    let root = repository_root(repo)?.to_path_buf();
    let before = snapshot_tree(repo, &snapshot_reference(request_key, "before"))?;
    let after = snapshot_tree(repo, &snapshot_reference(request_key, "after"))?;
    let expected = snapshot_tree(repo, &snapshot_reference(request_key, expected_phase))?;
    let target = snapshot_tree(repo, &snapshot_reference(request_key, target_phase))?;
    let diff = repo
        .diff_tree_to_tree(Some(&before), Some(&after), None)
        .map_err(error_text)?;
    let mut restore_targets: BTreeMap<PathBuf, Option<Vec<u8>>> = BTreeMap::new();
    let mut conflicts = Vec::new();
    for delta in diff.deltas() {
        let paths = [delta.old_file().path(), delta.new_file().path()];
        for path in paths.into_iter().flatten() {
            let relative = safe_relative_path(&path.to_string_lossy())?;
            if restore_targets.contains_key(&relative) {
                continue;
            }
            let expected_content = tree_file_bytes(repo, &expected, &relative)?;
            let current = filesystem_bytes(&root.join(&relative))?;
            if current != expected_content {
                conflicts.push(relative.to_string_lossy().replace('\\', "/"));
            }
            restore_targets.insert(relative.clone(), tree_file_bytes(repo, &target, &relative)?);
        }
    }
    if !conflicts.is_empty() {
        return Ok(GitTurnApplyResult {
            applied: false,
            affected_files: Vec::new(),
            conflicting_files: conflicts,
        });
    }
    let mut affected = Vec::new();
    for (relative, original) in restore_targets {
        let target = root.join(&relative);
        match original {
            Some(content) => {
                if let Some(parent) = target.parent() {
                    fs::create_dir_all(parent).map_err(error_text)?;
                }
                fs::write(&target, content).map_err(error_text)?;
            }
            None if target.exists() => fs::remove_file(&target).map_err(error_text)?,
            None => {}
        }
        affected.push(relative.to_string_lossy().replace('\\', "/"));
    }
    Ok(GitTurnApplyResult {
        applied: true,
        affected_files: affected,
        conflicting_files: Vec::new(),
    })
}

#[derive(Clone, Copy)]
enum RemoteOperation {
    Fetch,
    Pull,
    Push,
    Sync,
}

struct RemoteTracking {
    name: String,
    url: Option<String>,
    tracking_reference: String,
    has_upstream: bool,
}

fn ensure_clean_worktree(repo: &Repository) -> Result<(), String> {
    let mut options = StatusOptions::new();
    options.include_untracked(true).recurse_untracked_dirs(true);
    if repo
        .statuses(Some(&mut options))
        .map_err(error_text)?
        .is_empty()
    {
        Ok(())
    } else {
        Err(PULL_REQUIRES_CLEAN_WORKTREE.to_string())
    }
}

fn conflict_paths(index: &mut git2::Index) -> Result<Vec<String>, String> {
    let mut paths = Vec::new();
    let conflicts = index.conflicts().map_err(error_text)?;
    for conflict in conflicts {
        let conflict = conflict.map_err(error_text)?;
        let path = conflict
            .our
            .or(conflict.their)
            .or(conflict.ancestor)
            .map(|entry| String::from_utf8_lossy(&entry.path).into_owned());
        if let Some(path) = path {
            paths.push(path);
        }
    }
    paths.sort();
    paths.dedup();
    Ok(paths)
}

fn commit_index(repo: &Repository, message: &str) -> Result<git2::Oid, String> {
    let signature = repository_signature(repo)?;
    let mut index = repo.index().map_err(error_text)?;
    let tree_oid = index.write_tree_to(repo).map_err(error_text)?;
    let tree = repo.find_tree(tree_oid).map_err(error_text)?;
    let parent = repo.head().ok().and_then(|head| head.peel_to_commit().ok());
    if parent
        .as_ref()
        .is_some_and(|commit| commit.tree_id() == tree_oid)
    {
        return Err("there are no staged changes to commit".to_string());
    }
    let parents: Vec<&git2::Commit<'_>> = parent.iter().collect();
    repo.commit(
        Some("HEAD"),
        &signature,
        &signature,
        message,
        &tree,
        &parents,
    )
    .map_err(error_text)
}

fn repository_signature(repo: &Repository) -> Result<Signature<'_>, String> {
    let identity = repository_identity(repo)?;
    let name = identity
        .name
        .ok_or_else(|| "git identity is not configured".to_string())?;
    let email = identity
        .email
        .ok_or_else(|| "git identity is not configured".to_string())?;
    Signature::now(&name, &email).map_err(error_text)
}

fn repository_identity(repo: &Repository) -> Result<GitRepositoryIdentity, String> {
    let config = repo.config().map_err(error_text)?;
    let name = config
        .get_string("user.name")
        .ok()
        .filter(|value| !value.trim().is_empty());
    let email = config
        .get_string("user.email")
        .ok()
        .filter(|value| !value.trim().is_empty());
    Ok(GitRepositoryIdentity {
        configured: name.is_some() && email.is_some(),
        name,
        email,
    })
}

fn validated_paths(values: Vec<String>) -> Result<Vec<PathBuf>, String> {
    if values.is_empty() {
        return Err("at least one file path is required".to_string());
    }
    values
        .into_iter()
        .map(|value| safe_relative_path(&value))
        .collect()
}

fn required_value<'a>(value: &'a str, field: &str) -> Result<&'a str, String> {
    let value = value.trim();
    if value.is_empty() {
        Err(format!("{field} is required"))
    } else {
        Ok(value)
    }
}

fn workspace_directory(path: &str) -> Result<PathBuf, String> {
    let candidate = PathBuf::from(path).expand_home()?;
    if !candidate.is_dir() {
        return Err("workspace path is not a directory".to_string());
    }
    candidate.canonicalize().map_err(error_text)
}

fn discover_repository(path: &str) -> Result<Repository, String> {
    let candidate = workspace_directory(path)?;
    Repository::discover(candidate).map_err(|_| "workspace is not a Git repository".to_string())
}

fn clone_repository(
    app: tauri::AppHandle,
    remote_url: String,
    destination_parent: String,
    directory_name: String,
    branch: Option<String>,
    access_token: Option<String>,
) -> Result<GitCloneResult, String> {
    let normalized_directory_name = directory_name.trim();
    if normalized_directory_name.is_empty()
        || normalized_directory_name == "."
        || normalized_directory_name == ".."
        || normalized_directory_name.contains('/')
        || normalized_directory_name.contains('\\')
    {
        return Err("clone directory name is invalid".to_string());
    }
    let destination_path = PathBuf::from(destination_parent)
        .expand_home()?
        .join(normalized_directory_name);
    if destination_path.exists() {
        let mut entries = fs::read_dir(&destination_path).map_err(error_text)?;
        if entries.next().is_some() {
            return Err("clone destination must be empty".to_string());
        }
    }
    let progress_app = app.clone();
    let mut callbacks = RemoteCallbacks::new();
    callbacks.transfer_progress(move |progress| {
        let _ = progress_app.emit(
            "git-clone-progress",
            GitCloneProgress {
                stage: "receiving".to_string(),
                received_objects: progress.received_objects(),
                total_objects: progress.total_objects(),
                indexed_objects: progress.indexed_objects(),
                received_bytes: progress.received_bytes(),
            },
        );
        true
    });
    callbacks.credentials(move |_url, username, allowed| {
        if allowed.contains(CredentialType::USER_PASS_PLAINTEXT) {
            if let Some(token) = access_token.as_deref() {
                return Cred::userpass_plaintext("x-access-token", token);
            }
        }
        if allowed.contains(CredentialType::SSH_KEY) {
            if let Some(username) = username {
                return Cred::ssh_key_from_agent(username);
            }
        }
        Cred::default()
    });
    let mut fetch = FetchOptions::new();
    fetch.remote_callbacks(callbacks);
    let mut builder = RepoBuilder::new();
    builder.fetch_options(fetch);
    if let Some(branch) = branch.as_deref().filter(|value| !value.trim().is_empty()) {
        builder.branch(branch.trim());
    }
    let _ = app.emit(
        "git-clone-progress",
        GitCloneProgress {
            stage: "connecting".to_string(),
            received_objects: 0,
            total_objects: 0,
            indexed_objects: 0,
            received_bytes: 0,
        },
    );
    let repo = builder
        .clone(&remote_url, &destination_path)
        .map_err(error_text)?;
    let (branch, _, _, _) = branch_state(&repo)?;
    let root = path_text(repository_root(&repo)?);
    let _ = app.emit(
        "git-clone-progress",
        GitCloneProgress {
            stage: "complete".to_string(),
            received_objects: 0,
            total_objects: 0,
            indexed_objects: 0,
            received_bytes: 0,
        },
    );
    Ok(GitCloneResult {
        repository_root: root,
        branch,
    })
}

fn repository_root(repo: &Repository) -> Result<&Path, String> {
    repo.workdir()
        .ok_or_else(|| "bare repositories cannot be used as workspaces".to_string())
}

fn current_branch_name(repo: &Repository) -> Result<String, String> {
    if repo.head_detached().map_err(error_text)? {
        return Err("detached HEAD cannot be synchronized".to_string());
    }
    if let Ok(head) = repo.head() {
        if let Some(name) = head.shorthand().filter(|value| !value.is_empty()) {
            return Ok(name.to_string());
        }
    }
    let head = repo.find_reference("HEAD").map_err(error_text)?;
    head.symbolic_target()
        .and_then(|value| value.strip_prefix("refs/heads/"))
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| "current branch is unavailable".to_string())
}

fn remote_tracking(repo: &Repository, branch: &str) -> Result<Option<RemoteTracking>, String> {
    let config = repo.config().map_err(error_text)?;
    let configured_remote = config.get_string(&format!("branch.{branch}.remote")).ok();
    let has_upstream = repo
        .find_branch(branch, git2::BranchType::Local)
        .ok()
        .and_then(|value| value.upstream().ok())
        .is_some();
    let name = configured_remote
        .filter(|value| value != "." && !value.trim().is_empty())
        .or_else(|| {
            repo.find_remote("origin")
                .ok()
                .map(|_| "origin".to_string())
        })
        .or_else(|| {
            repo.remotes()
                .ok()
                .and_then(|values| values.get(0).map(str::to_string))
        });
    let Some(name) = name else {
        return Ok(None);
    };
    let merge_reference = config
        .get_string(&format!("branch.{branch}.merge"))
        .unwrap_or_else(|_| format!("refs/heads/{branch}"));
    let remote_branch = merge_reference
        .strip_prefix("refs/heads/")
        .unwrap_or(branch);
    let remote = repo.find_remote(&name).map_err(error_text)?;
    Ok(Some(RemoteTracking {
        tracking_reference: format!("refs/remotes/{name}/{remote_branch}"),
        name,
        url: remote.url().map(str::to_string),
        has_upstream,
    }))
}

fn branch_state(repo: &Repository) -> Result<(Option<String>, bool, usize, usize), String> {
    let head = match repo.head() {
        Ok(head) => head,
        Err(error) if error.code() == git2::ErrorCode::UnbornBranch => {
            return Ok((Some(current_branch_name(repo)?), false, 0, 0));
        }
        Err(_) => return Ok((None, false, 0, 0)),
    };
    let detached = !head.is_branch();
    let branch = head.shorthand().map(str::to_string);
    let Some(local_oid) = head.target() else {
        return Ok((branch, detached, 0, 0));
    };
    let upstream_oid = if let Some(name) = head.shorthand() {
        repo.find_branch(name, git2::BranchType::Local)
            .ok()
            .and_then(|local| local.upstream().ok())
            .and_then(|upstream| upstream.get().target())
    } else {
        None
    };
    let (ahead, behind) = upstream_oid
        .map(|remote_oid| repo.graph_ahead_behind(local_oid, remote_oid))
        .transpose()
        .map_err(error_text)?
        .unwrap_or((0, 0));
    Ok((branch, detached, ahead, behind))
}

fn working_tree_line_counts(repo: &Repository) -> Result<BTreeMap<String, (usize, usize)>, String> {
    let mut options = DiffOptions::new();
    options
        .include_untracked(true)
        .recurse_untracked_dirs(true)
        .show_untracked_content(true);
    let head_tree = repo.head().ok().and_then(|head| head.peel_to_tree().ok());
    let diff = repo
        .diff_tree_to_workdir_with_index(head_tree.as_ref(), Some(&mut options))
        .map_err(error_text)?;
    diff_line_counts(&diff)
}

fn diff_line_counts(diff: &Diff<'_>) -> Result<BTreeMap<String, (usize, usize)>, String> {
    let mut counts = BTreeMap::new();
    for index in 0..diff.deltas().len() {
        let Some(patch) = Patch::from_diff(diff, index).map_err(error_text)? else {
            continue;
        };
        let (_, additions, deletions) = patch.line_stats().map_err(error_text)?;
        let delta = diff
            .get_delta(index)
            .ok_or_else(|| "Git diff delta is missing".to_string())?;
        let relative = delta_path(&delta)?.to_string_lossy().replace('\\', "/");
        counts.insert(relative, (additions, deletions));
    }
    Ok(counts)
}

fn safe_relative_path(value: &str) -> Result<PathBuf, String> {
    let path = Path::new(value);
    if path.is_absolute()
        || path.components().any(|part| {
            matches!(
                part,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err("file path must stay inside the repository".to_string());
    }
    Ok(path.to_path_buf())
}

fn delta_path(delta: &DiffDelta<'_>) -> Result<PathBuf, String> {
    let value = delta
        .new_file()
        .path()
        .or_else(|| delta.old_file().path())
        .ok_or_else(|| "Git change has no path".to_string())?;
    safe_relative_path(&value.to_string_lossy())
}

fn visible_text(value: &[u8]) -> String {
    let end = value.len().min(MAX_DIFF_TEXT_BYTES);
    String::from_utf8_lossy(&value[..end]).into_owned()
}

fn status_label(status: Status) -> &'static str {
    if status.intersects(Status::CONFLICTED) {
        "conflicted"
    } else if status.intersects(Status::WT_NEW | Status::INDEX_NEW) {
        "added"
    } else if status.intersects(Status::WT_DELETED | Status::INDEX_DELETED) {
        "deleted"
    } else if status.intersects(Status::WT_RENAMED | Status::INDEX_RENAMED) {
        "renamed"
    } else {
        "modified"
    }
}

fn delta_status(status: git2::Delta) -> &'static str {
    match status {
        git2::Delta::Added => "added",
        git2::Delta::Deleted => "deleted",
        git2::Delta::Renamed => "renamed",
        git2::Delta::Copied => "copied",
        git2::Delta::Typechange => "type_changed",
        git2::Delta::Conflicted => "conflicted",
        _ => "modified",
    }
}

fn path_text(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

fn error_text(error: impl std::fmt::Display) -> String {
    error.to_string()
}

trait ExpandHome {
    fn expand_home(self) -> Result<PathBuf, String>;
}

impl ExpandHome for PathBuf {
    fn expand_home(self) -> Result<PathBuf, String> {
        if !self.starts_with("~") {
            return Ok(self);
        }
        let home = std::env::var_os("HOME")
            .or_else(|| std::env::var_os("USERPROFILE"))
            .ok_or_else(|| "home directory is unavailable".to_string())?;
        let remainder = self.strip_prefix("~").map_err(error_text)?;
        Ok(PathBuf::from(home).join(remainder))
    }
}
