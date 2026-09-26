use super::{
    conflict_paths, current_branch_name, discover_repository, ensure_clean_worktree, error_text,
    remote_tracking, repository_signature, repository_status, GitRemoteOperationResult,
    RemoteOperation, RemoteTracking,
};
use crate::github_account::github_access_token;
use git2::{
    build::CheckoutBuilder, Cred, CredentialType, FetchOptions, PushOptions, RemoteCallbacks,
    Repository,
};
use std::sync::{Arc, Mutex};

pub(super) async fn run_remote_operation(
    path: String,
    operation: RemoteOperation,
) -> Result<GitRemoteOperationResult, String> {
    let access_token = github_access_token().ok();
    tauri::async_runtime::spawn_blocking(move || {
        let repo = discover_repository(&path)?;
        match operation {
            RemoteOperation::Fetch => fetch_repository(&repo, access_token.as_deref()),
            RemoteOperation::Pull => pull_repository(&repo, access_token.as_deref()),
            RemoteOperation::Push => push_repository(&repo, access_token.as_deref()),
            RemoteOperation::Sync => {
                let branch = current_branch_name(&repo)?;
                let has_upstream =
                    remote_tracking(&repo, &branch)?.is_some_and(|tracking| tracking.has_upstream);
                if !has_upstream {
                    return push_repository(&repo, access_token.as_deref());
                }
                let pulled = pull_repository(&repo, access_token.as_deref())?;
                if !pulled.conflicting_files.is_empty() {
                    return Ok(pulled);
                }
                push_repository(&repo, access_token.as_deref())
            }
        }
    })
    .await
    .map_err(error_text)?
}

fn fetch_repository(
    repo: &Repository,
    access_token: Option<&str>,
) -> Result<GitRemoteOperationResult, String> {
    let branch = current_branch_name(repo)?;
    let tracking =
        remote_tracking(repo, &branch)?.ok_or_else(|| "repository has no remote".to_string())?;
    fetch_remote(repo, &tracking, access_token)?;
    remote_result(repo, "fetched", Vec::new())
}

fn pull_repository(
    repo: &Repository,
    access_token: Option<&str>,
) -> Result<GitRemoteOperationResult, String> {
    ensure_clean_worktree(repo)?;
    let branch = current_branch_name(repo)?;
    let tracking = remote_tracking(repo, &branch)?
        .filter(|value| value.has_upstream)
        .ok_or_else(|| "current branch has no upstream".to_string())?;
    fetch_remote(repo, &tracking, access_token)?;
    let upstream = repo
        .find_reference(&tracking.tracking_reference)
        .map_err(|_| "upstream branch was not found after fetch".to_string())?;
    let annotated = repo
        .reference_to_annotated_commit(&upstream)
        .map_err(error_text)?;
    let (analysis, _) = repo.merge_analysis(&[&annotated]).map_err(error_text)?;
    if analysis.is_up_to_date() {
        return remote_result(repo, "up_to_date", Vec::new());
    }
    if analysis.is_fast_forward() {
        fast_forward(repo, &branch, annotated.id())?;
        return remote_result(repo, "pulled", Vec::new());
    }
    if !analysis.is_normal() {
        return Err("upstream cannot be merged into the current branch".to_string());
    }
    let signature = repository_signature(repo)?;
    repo.merge(&[&annotated], None, None).map_err(error_text)?;
    let mut index = repo.index().map_err(error_text)?;
    if index.has_conflicts() {
        let conflicts = conflict_paths(&mut index)?;
        return remote_result(repo, "conflicts", conflicts);
    }
    let tree_oid = index.write_tree_to(repo).map_err(error_text)?;
    let tree = repo.find_tree(tree_oid).map_err(error_text)?;
    let local = repo
        .head()
        .map_err(error_text)?
        .peel_to_commit()
        .map_err(error_text)?;
    let remote = repo.find_commit(annotated.id()).map_err(error_text)?;
    repo.commit(
        Some("HEAD"),
        &signature,
        &signature,
        &format!(
            "Merge remote-tracking branch '{}/{}'",
            tracking.name, branch
        ),
        &tree,
        &[&local, &remote],
    )
    .map_err(error_text)?;
    repo.checkout_head(None).map_err(error_text)?;
    repo.cleanup_state().map_err(error_text)?;
    remote_result(repo, "pulled", Vec::new())
}

fn push_repository(
    repo: &Repository,
    access_token: Option<&str>,
) -> Result<GitRemoteOperationResult, String> {
    let branch = current_branch_name(repo)?;
    let tracking =
        remote_tracking(repo, &branch)?.ok_or_else(|| "repository has no remote".to_string())?;
    require_remote_authentication(tracking.url.as_deref(), access_token)?;
    let failures = Arc::new(Mutex::new(Vec::<String>::new()));
    let callback_failures = failures.clone();
    let mut callbacks = authentication_callbacks(access_token.map(str::to_string));
    callbacks.push_update_reference(move |_reference, status| {
        if let Some(message) = status {
            callback_failures.lock().unwrap().push(message.to_string());
        }
        Ok(())
    });
    let mut options = PushOptions::new();
    options.remote_callbacks(callbacks);
    let mut remote = repo.find_remote(&tracking.name).map_err(error_text)?;
    let refspec = format!("refs/heads/{branch}:refs/heads/{branch}");
    remote
        .push(&[&refspec], Some(&mut options))
        .map_err(error_text)?;
    let failures = failures.lock().unwrap();
    if !failures.is_empty() {
        return Err(failures.join("; "));
    }
    drop(failures);
    configure_upstream_after_push(repo, &tracking.name, &branch)?;
    remote_result(repo, "pushed", Vec::new())
}

fn fetch_remote(
    repo: &Repository,
    tracking: &RemoteTracking,
    access_token: Option<&str>,
) -> Result<(), String> {
    let mut remote = repo.find_remote(&tracking.name).map_err(error_text)?;
    let mut options = FetchOptions::new();
    options.remote_callbacks(authentication_callbacks(access_token.map(str::to_string)));
    remote
        .fetch(&[] as &[&str], Some(&mut options), None)
        .map_err(error_text)
}

fn authentication_callbacks(access_token: Option<String>) -> RemoteCallbacks<'static> {
    let mut callbacks = RemoteCallbacks::new();
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
        if allowed.contains(CredentialType::USERNAME) {
            return Cred::username(username.unwrap_or("git"));
        }
        Cred::default()
    });
    callbacks
}

fn require_remote_authentication(
    remote_url: Option<&str>,
    access_token: Option<&str>,
) -> Result<(), String> {
    let url = remote_url.unwrap_or_default().to_ascii_lowercase();
    if url.starts_with("https://github.com/") && access_token.is_none() {
        return Err("github authentication required".to_string());
    }
    Ok(())
}

fn fast_forward(repo: &Repository, branch: &str, target: git2::Oid) -> Result<(), String> {
    let reference_name = format!("refs/heads/{branch}");
    let mut reference = repo.find_reference(&reference_name).map_err(error_text)?;
    reference
        .set_target(target, "Combo pull: fast-forward")
        .map_err(error_text)?;
    repo.set_head(&reference_name).map_err(error_text)?;
    let mut checkout = CheckoutBuilder::new();
    checkout.force();
    repo.checkout_head(Some(&mut checkout)).map_err(error_text)
}

fn configure_upstream_after_push(
    repo: &Repository,
    remote_name: &str,
    branch: &str,
) -> Result<(), String> {
    let head_oid = repo
        .head()
        .map_err(error_text)?
        .target()
        .ok_or_else(|| "current branch has no commit".to_string())?;
    let tracking_reference = format!("refs/remotes/{remote_name}/{branch}");
    repo.reference(
        &tracking_reference,
        head_oid,
        true,
        "Combo push: update remote tracking branch",
    )
    .map_err(error_text)?;
    let mut config = repo.config().map_err(error_text)?;
    config
        .set_str(&format!("branch.{branch}.remote"), remote_name)
        .map_err(error_text)?;
    config
        .set_str(
            &format!("branch.{branch}.merge"),
            &format!("refs/heads/{branch}"),
        )
        .map_err(error_text)
}

fn remote_result(
    repo: &Repository,
    outcome: &str,
    conflicting_files: Vec<String>,
) -> Result<GitRemoteOperationResult, String> {
    Ok(GitRemoteOperationResult {
        outcome: outcome.to_string(),
        conflicting_files,
        status: repository_status(repo)?,
    })
}
