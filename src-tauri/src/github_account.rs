use keyring::Entry;
use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::{Deserialize, Serialize};

const KEYRING_SERVICE: &str = "top.liuyanai.combo.github";
const KEYRING_ACCOUNT: &str = "default";
const GITHUB_CLIENT_ID: &str = "Ov23lipoe6KMBX7wd8dL";
const GITHUB_API_VERSION: &str = "2022-11-28";
const GITHUB_DEVICE_CODE_URL: &str = "https://github.com/login/device/code";
const GITHUB_ACCESS_TOKEN_URL: &str = "https://github.com/login/oauth/access_token";

#[derive(Clone, Deserialize, Serialize)]
pub struct GitHubAccount {
    pub login: String,
    pub display_name: String,
    pub avatar_url: String,
}

#[derive(Deserialize, Serialize)]
struct StoredGitHubCredential {
    account: GitHubAccount,
    github_access_token: String,
}

#[derive(Serialize)]
pub struct GitHubDeviceAuthorization {
    device_code: String,
    user_code: String,
    verification_uri: String,
    expires_in: u64,
    interval: u64,
}

#[derive(Serialize)]
pub struct GitHubDevicePoll {
    status: String,
    retry_after_seconds: u64,
    account: Option<GitHubAccount>,
}

#[derive(Deserialize)]
struct GitHubDeviceAuthorizationResponse {
    device_code: String,
    user_code: String,
    verification_uri: String,
    expires_in: u64,
    interval: u64,
}

#[derive(Deserialize)]
struct GitHubDeviceTokenResponse {
    access_token: Option<String>,
    error: Option<String>,
    interval: Option<u64>,
}

#[derive(Deserialize)]
struct GitHubUserResponse {
    login: String,
    name: Option<String>,
    avatar_url: String,
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
pub async fn github_start_device_authorization() -> Result<GitHubDeviceAuthorization, String> {
    let response = reqwest::Client::new()
        .post(GITHUB_DEVICE_CODE_URL)
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/json")
        .form(&[("client_id", GITHUB_CLIENT_ID), ("scope", "read:user repo")])
        .send()
        .await
        .map_err(error_text)?;
    if !response.status().is_success() {
        return Err(format!(
            "GitHub device authorization failed: HTTP {}",
            response.status()
        ));
    }
    let value = response
        .json::<GitHubDeviceAuthorizationResponse>()
        .await
        .map_err(error_text)?;
    Ok(GitHubDeviceAuthorization {
        device_code: value.device_code,
        user_code: value.user_code,
        verification_uri: value.verification_uri,
        expires_in: value.expires_in,
        interval: value.interval.max(5),
    })
}

#[tauri::command]
pub async fn github_poll_device_authorization(
    device_code: String,
) -> Result<GitHubDevicePoll, String> {
    if device_code.trim().is_empty() {
        return Err("GitHub device code is required".to_string());
    }
    let response = reqwest::Client::new()
        .post(GITHUB_ACCESS_TOKEN_URL)
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/json")
        .form(&[
            ("client_id", GITHUB_CLIENT_ID),
            ("device_code", device_code.trim()),
            ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
        ])
        .send()
        .await
        .map_err(error_text)?;
    if !response.status().is_success() {
        return Err(format!(
            "GitHub device token request failed: HTTP {}",
            response.status()
        ));
    }
    let value = response
        .json::<GitHubDeviceTokenResponse>()
        .await
        .map_err(error_text)?;
    if let Some(access_token) = value.access_token.filter(|token| !token.trim().is_empty()) {
        let account = fetch_account(&access_token).await?;
        store_credential(account.clone(), access_token)?;
        return Ok(GitHubDevicePoll {
            status: "authorized".to_string(),
            retry_after_seconds: 0,
            account: Some(account),
        });
    }
    let status = value
        .error
        .unwrap_or_else(|| "authorization_pending".to_string());
    Ok(GitHubDevicePoll {
        retry_after_seconds: value.interval.unwrap_or(5).max(5),
        status,
        account: None,
    })
}

#[tauri::command]
pub fn github_account() -> Result<Option<GitHubAccount>, String> {
    match stored_credential() {
        Ok(stored) => Ok(Some(stored.account)),
        Err(error) if error.contains("No matching entry") || error.contains("not found") => {
            Ok(None)
        }
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
            return Err(format!(
                "GitHub repository request failed: HTTP {}",
                response.status()
            ));
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

async fn fetch_account(access_token: &str) -> Result<GitHubAccount, String> {
    let response = reqwest::Client::new()
        .get("https://api.github.com/user")
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/vnd.github+json")
        .header("X-GitHub-Api-Version", GITHUB_API_VERSION)
        .header(AUTHORIZATION, format!("Bearer {access_token}"))
        .send()
        .await
        .map_err(error_text)?;
    if !response.status().is_success() {
        return Err(format!(
            "GitHub account request failed: HTTP {}",
            response.status()
        ));
    }
    let user = response
        .json::<GitHubUserResponse>()
        .await
        .map_err(error_text)?;
    Ok(GitHubAccount {
        display_name: user
            .name
            .filter(|name| !name.trim().is_empty())
            .unwrap_or_else(|| user.login.clone()),
        login: user.login,
        avatar_url: user.avatar_url,
    })
}

fn store_credential(account: GitHubAccount, github_access_token: String) -> Result<(), String> {
    let stored = StoredGitHubCredential {
        account,
        github_access_token,
    };
    credential_entry()?
        .set_password(&serde_json::to_string(&stored).map_err(error_text)?)
        .map_err(error_text)
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
