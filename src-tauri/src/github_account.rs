use keyring::Entry;
use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::{Deserialize, Serialize};

const KEYRING_SERVICE: &str = "top.liuyanai.combo.github";
const KEYRING_ACCOUNT: &str = "default";
const GITHUB_API_VERSION: &str = "2022-11-28";

#[derive(Clone, Deserialize, Serialize)]
pub struct GitHubAccount {
    pub login: String,
    pub display_name: String,
    pub avatar_url: String,
}

#[derive(Deserialize, Serialize)]
struct StoredGitHubCredential {
    account: GitHubAccount,
    combo_session_token: String,
    github_access_token: String,
}

#[derive(Serialize)]
pub struct GitHubRepository {
    id: u64,
    name: String,
    full_name: String,
    private: bool,
    clone_url: String,
    default_branch: String,
    owner_login: String,
    owner_avatar_url: String,
    updated_at: String,
}

#[derive(Deserialize)]
struct GitHubRepositoryResponse {
    id: u64,
    name: String,
    full_name: String,
    private: bool,
    clone_url: String,
    default_branch: String,
    updated_at: String,
    owner: GitHubOwner,
}

#[derive(Deserialize)]
struct GitHubOwner {
    login: String,
    avatar_url: String,
}

#[tauri::command]
pub fn github_store_account(
    account: GitHubAccount,
    combo_session_token: String,
    github_access_token: String,
) -> Result<GitHubAccount, String> {
    if account.login.trim().is_empty()
        || combo_session_token.trim().is_empty()
        || github_access_token.trim().is_empty()
    {
        return Err("GitHub authorization response is incomplete".to_string());
    }
    let stored = StoredGitHubCredential {
        account: account.clone(),
        combo_session_token,
        github_access_token,
    };
    credential_entry()?
        .set_password(&serde_json::to_string(&stored).map_err(error_text)?)
        .map_err(error_text)?;
    Ok(account)
}

#[tauri::command]
pub fn github_account() -> Result<Option<GitHubAccount>, String> {
    match stored_credential() {
        Ok(stored) => Ok(Some(stored.account)),
        Err(error) if error.contains("No matching entry") || error.contains("not found") => Ok(None),
        Err(error) => Err(error),
    }
}

#[tauri::command]
pub async fn github_list_repositories() -> Result<Vec<GitHubRepository>, String> {
    let credential = stored_credential()?;
    let client = reqwest::Client::new();
    let mut repositories = Vec::new();
    for page in 1..=10 {
        let response = client
            .get(format!(
                "https://api.github.com/user/repos?affiliation=owner,collaborator,organization_member&sort=updated&per_page=100&page={page}"
            ))
            .header(USER_AGENT, "Combo-Desktop")
            .header(ACCEPT, "application/vnd.github+json")
            .header("X-GitHub-Api-Version", GITHUB_API_VERSION)
            .header(AUTHORIZATION, format!("Bearer {}", credential.github_access_token))
            .send()
            .await
            .map_err(error_text)?;
        if !response.status().is_success() {
            return Err(format!("GitHub repository request failed: HTTP {}", response.status()));
        }
        let page_values = response
            .json::<Vec<GitHubRepositoryResponse>>()
            .await
            .map_err(error_text)?;
        let page_count = page_values.len();
        repositories.extend(page_values.into_iter().map(|value| GitHubRepository {
            id: value.id,
            name: value.name,
            full_name: value.full_name,
            private: value.private,
            clone_url: value.clone_url,
            default_branch: value.default_branch,
            owner_login: value.owner.login,
            owner_avatar_url: value.owner.avatar_url,
            updated_at: value.updated_at,
        }));
        if page_count < 100 {
            break;
        }
    }
    Ok(repositories)
}

#[tauri::command]
pub fn github_logout() -> Result<(), String> {
    match credential_entry()?.delete_credential() {
        Ok(()) => Ok(()),
        Err(error) if error.to_string().contains("No matching entry") => Ok(()),
        Err(error) => Err(error_text(error)),
    }
}

pub(crate) fn github_access_token() -> Result<String, String> {
    stored_credential().map(|credential| credential.github_access_token)
}

fn stored_credential() -> Result<StoredGitHubCredential, String> {
    let value = credential_entry()?.get_password().map_err(error_text)?;
    serde_json::from_str(&value).map_err(error_text)
}

fn credential_entry() -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).map_err(error_text)
}

fn error_text(error: impl std::fmt::Display) -> String {
    error.to_string()
}
