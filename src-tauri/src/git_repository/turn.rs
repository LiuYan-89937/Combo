use super::{
    delta_path, delta_status, diff_line_counts, error_text, path_text, repository_root,
    GitFileChange, GitTurnChanges, WORKSPACE_INPUT_DIRECTORY,
};
use git2::{IndexAddOption, ObjectType, Repository, Signature};
use std::fs;
use std::path::{Path, PathBuf};

pub(super) fn create_worktree_snapshot(
    repo: &Repository,
    reference: &str,
    parent_oid: Option<git2::Oid>,
    request_id: &str,
    phase: &str,
) -> Result<git2::Oid, String> {
    let mut index = repo.index().map_err(error_text)?;
    index.read(true).map_err(error_text)?;
    let mut include_review_file =
        |path: &Path, _matched: &[u8]| i32::from(is_workspace_input_path(path));
    index
        .add_all(
            ["*"],
            IndexAddOption::DEFAULT,
            Some(&mut include_review_file),
        )
        .map_err(error_text)?;
    index
        .update_all(["*"], Some(&mut include_review_file))
        .map_err(error_text)?;
    let tree_oid = write_turn_review_tree(repo, &mut index)?;
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

pub(super) fn turn_changes(
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

pub(super) fn snapshot_tree<'repo>(
    repo: &'repo Repository,
    reference: &str,
) -> Result<git2::Tree<'repo>, String> {
    let oid = reference_target(repo, reference)?;
    let tree = repo
        .find_commit(oid)
        .map_err(error_text)?
        .tree()
        .map_err(error_text)?;
    let mut index = git2::Index::new().map_err(error_text)?;
    index.read_tree(&tree).map_err(error_text)?;
    let review_tree = write_turn_review_tree(repo, &mut index)?;
    repo.find_tree(review_tree).map_err(error_text)
}

fn is_workspace_input_path(path: &Path) -> bool {
    path.ancestors()
        .any(|ancestor| ancestor.ends_with(WORKSPACE_INPUT_DIRECTORY))
}

fn write_turn_review_tree(repo: &Repository, index: &mut git2::Index) -> Result<git2::Oid, String> {
    let mut remove_input_file =
        |path: &Path, _matched: &[u8]| i32::from(!is_workspace_input_path(path));
    index
        .remove_all(["*"], Some(&mut remove_input_file))
        .map_err(error_text)?;
    index.write_tree_to(repo).map_err(error_text)
}

pub(super) fn reference_target(repo: &Repository, reference: &str) -> Result<git2::Oid, String> {
    repo.find_reference(reference)
        .map_err(|_| "turn snapshot was not found".to_string())?
        .target()
        .ok_or_else(|| "turn snapshot reference has no target".to_string())
}

pub(super) fn snapshot_reference(request_key: &str, phase: &str) -> String {
    format!("refs/combo/turns/{request_key}/{phase}")
}

pub(super) fn reference_key(request_id: &str) -> Result<String, String> {
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

pub(super) fn tree_file_bytes(
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

pub(super) fn filesystem_bytes(path: &Path) -> Result<Option<Vec<u8>>, String> {
    if !path.exists() {
        return Ok(None);
    }
    if !path.is_file() {
        return Err(format!("{} is not a regular file", path.display()));
    }
    fs::read(path).map(Some).map_err(error_text)
}
