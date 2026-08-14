use git2::{
    build::RepoBuilder, Cred, CredentialType, Diff, DiffDelta, DiffOptions, FetchOptions,
    IndexAddOption, ObjectType, Patch, RemoteCallbacks, Repository, Signature, Status,
    StatusOptions,
};
use serde::Serialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};
use tauri::Emitter;

use crate::github_account::github_access_token;

const MAX_DIFF_TEXT_BYTES: usize = 2 * 1024 * 1024;

#[derive(Serialize)]
pub struct GitRepositoryStatus {
    repository_root: String,
    branch: Option<String>,
    detached: bool,
    ahead: usize,
    behind: usize,
    files: Vec<GitFileStatus>,
}

#[derive(Clone, Serialize)]
pub struct GitFileStatus {
    path: String,
    change_type: String,
    staged: bool,
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
pub struct GitRevertResult {
    reverted: bool,
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
    let root = repository_root(&repo)?;
    let (branch, detached, ahead, behind) = branch_state(&repo)?;
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
            additions,
            deletions,
        });
    }
    files.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(GitRepositoryStatus {
        repository_root: path_text(root),
        branch,
        detached,
        ahead,
        behind,
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
pub fn git_revert_turn(path: String, request_id: String) -> Result<GitRevertResult, String> {
    let repo = discover_repository(&path)?;
    let root = repository_root(&repo)?.to_path_buf();
    let request_key = reference_key(&request_id)?;
    let before = snapshot_tree(&repo, &snapshot_reference(&request_key, "before"))?;
    let after = snapshot_tree(&repo, &snapshot_reference(&request_key, "after"))?;
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
            let expected = tree_file_bytes(&repo, &after, &relative)?;
            let current = filesystem_bytes(&root.join(&relative))?;
            if current != expected {
                conflicts.push(relative.to_string_lossy().replace('\\', "/"));
            }
            restore_targets.insert(
                relative.clone(),
                tree_file_bytes(&repo, &before, &relative)?,
            );
        }
    }
    if !conflicts.is_empty() {
        return Ok(GitRevertResult {
            reverted: false,
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
    Ok(GitRevertResult {
        reverted: true,
        affected_files: affected,
        conflicting_files: Vec::new(),
    })
}

fn discover_repository(path: &str) -> Result<Repository, String> {
    let candidate = Path::new(path);
    if !candidate.exists() {
        return Err("workspace path does not exist".to_string());
    }
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

fn branch_state(repo: &Repository) -> Result<(Option<String>, bool, usize, usize), String> {
    let head = match repo.head() {
        Ok(head) => head,
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

fn create_worktree_snapshot(
    repo: &Repository,
    reference: &str,
    parent_oid: Option<git2::Oid>,
    request_id: &str,
    phase: &str,
) -> Result<git2::Oid, String> {
    let mut index = repo.index().map_err(error_text)?;
    index.read(true).map_err(error_text)?;
    index
        .add_all(["*"], IndexAddOption::DEFAULT, None)
        .map_err(error_text)?;
    index.update_all(["*"], None).map_err(error_text)?;
    let tree_oid = index.write_tree_to(repo).map_err(error_text)?;
    let tree = repo.find_tree(tree_oid).map_err(error_text)?;
    let signature = Signature::now("Combo", "snapshot@combo.local").map_err(error_text)?;
    let parent = parent_oid
        .map(|oid| repo.find_commit(oid).map_err(error_text))
        .transpose()?;
    let parents: Vec<&git2::Commit<'_>> = parent.iter().collect();
    repo.commit(
        Some(reference),
        &signature,
        &signature,
        &format!("Combo turn {request_id} {phase}"),
        &tree,
        &parents,
    )
    .map_err(error_text)
}

fn turn_changes(
    repo: &Repository,
    request_id: &str,
    request_key: &str,
) -> Result<GitTurnChanges, String> {
    let before = snapshot_tree(repo, &snapshot_reference(request_key, "before"))?;
    let after = snapshot_tree(repo, &snapshot_reference(request_key, "after"))?;
    let diff = repo
        .diff_tree_to_tree(Some(&before), Some(&after), None)
        .map_err(error_text)?;
    let counts = diff_line_counts(&diff)?;
    let mut files = Vec::new();
    let mut additions = 0;
    let mut deletions = 0;
    for delta in diff.deltas() {
        let path = delta_path(&delta)?.to_string_lossy().replace('\\', "/");
        let (file_additions, file_deletions) = counts.get(&path).copied().unwrap_or_default();
        additions += file_additions;
        deletions += file_deletions;
        files.push(GitFileChange {
            old_path: delta
                .old_file()
                .path()
                .map(|value| value.to_string_lossy().replace('\\', "/")),
            path,
            change_type: delta_status(delta.status()).to_string(),
            additions: file_additions,
            deletions: file_deletions,
            binary: delta.flags().contains(git2::DiffFlags::BINARY),
        });
    }
    Ok(GitTurnChanges {
        request_id: request_id.to_string(),
        repository_root: path_text(repository_root(repo)?),
        files,
        additions,
        deletions,
    })
}

fn snapshot_tree<'repo>(
    repo: &'repo Repository,
    reference: &str,
) -> Result<git2::Tree<'repo>, String> {
    let oid = reference_target(repo, reference)?;
    repo.find_commit(oid)
        .map_err(error_text)?
        .tree()
        .map_err(error_text)
}

fn reference_target(repo: &Repository, reference: &str) -> Result<git2::Oid, String> {
    repo.find_reference(reference)
        .map_err(|_| "turn snapshot was not found".to_string())?
        .target()
        .ok_or_else(|| "turn snapshot reference has no target".to_string())
}

fn snapshot_reference(request_key: &str, phase: &str) -> String {
    format!("refs/combo/turns/{request_key}/{phase}")
}

fn reference_key(request_id: &str) -> Result<String, String> {
    let value: String = request_id
        .chars()
        .filter(|character| {
            character.is_ascii_alphanumeric() || *character == '-' || *character == '_'
        })
        .take(120)
        .collect();
    if value.is_empty() {
        return Err("request id is invalid".to_string());
    }
    Ok(value)
}

fn tree_file_bytes(
    repo: &Repository,
    tree: &git2::Tree<'_>,
    relative: &Path,
) -> Result<Option<Vec<u8>>, String> {
    let entry = match tree.get_path(relative) {
        Ok(entry) => entry,
        Err(error) if error.code() == git2::ErrorCode::NotFound => return Ok(None),
        Err(error) => return Err(error_text(error)),
    };
    if entry.kind() != Some(ObjectType::Blob) {
        return Ok(None);
    }
    let blob = repo.find_blob(entry.id()).map_err(error_text)?;
    Ok(Some(blob.content().to_vec()))
}

fn filesystem_bytes(path: &Path) -> Result<Option<Vec<u8>>, String> {
    if !path.exists() {
        return Ok(None);
    }
    if !path.is_file() {
        return Err(format!("{} is not a regular file", path.display()));
    }
    fs::read(path).map(Some).map_err(error_text)
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
    if status.intersects(Status::WT_NEW | Status::INDEX_NEW) {
        "added"
    } else if status.intersects(Status::WT_DELETED | Status::INDEX_DELETED) {
        "deleted"
    } else if status.intersects(Status::WT_RENAMED | Status::INDEX_RENAMED) {
        "renamed"
    } else if status.intersects(Status::CONFLICTED) {
        "conflicted"
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
