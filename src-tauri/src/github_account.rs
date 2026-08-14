use keyring::Entry;
use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::{Deserialize, Serialize};

const KEYRING_SERVICE: &str = "top.liuyanai.combo.github";
const KEYRING_ACCOUNT: &str = "default";
const GITHUB_API_VERSION: &str = "2022-11-28";
const COMBO_SERVICE_URL: &str = env!("COMBO_SERVICE_URL");

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

#[derive(Deserialize, Serialize)]
pub struct GitHubBrowserAuthorization {
    flow_id: String,
    poll_secret: String,
    authorization_url: String,
    expires_in: u64,
    interval: u64,
}

#[derive(Serialize)]
pub struct GitHubBrowserPoll {
    status: String,
    retry_after_seconds: u64,
    account: Option<GitHubAccount>,
}

#[derive(Deserialize)]
struct GitHubBrowserAuthorizedResponse {
    status: String,
    github_access_token: String,
    user: GitHubServiceUser,
}

#[derive(Deserialize)]
struct GitHubServiceUser {
    github_login: String,
    display_name: String,
    avatar_url: String,
}

#[derive(Deserialize)]
struct GitHubAuthorizationPending {
    status: String,
    retry_after_seconds: u64,
}

#[derive(Deserialize)]
struct GitHubServiceErrorEnvelope {
    error: Option<GitHubServiceError>,
    message: Option<String>,
}

#[derive(Deserialize)]
struct GitHubServiceError {
    message: String,
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

#[derive(Serialize)]
struct GitHubCreateRepositoryRequest<'a> {
    name: &'a str,
    private: bool,
    auto_init: bool,
}

#[derive(Deserialize)]
struct GitHubOwner {
    login: String,
    avatar_url: String,
}

fn repository_view(value: GitHubRepositoryResponse) -> GitHubRepository {
    GitHubRepository {
        id: value.id,
        name: value.name,
        full_name: value.full_name,
        private: value.private,
        clone_url: value.clone_url,
        default_branch: value.default_branch,
        owner_login: value.owner.login,
        owner_avatar_url: value.owner.avatar_url,
        updated_at: value.updated_at,
    }
}

#[tauri::command]
pub async fn github_start_browser_authorization() -> Result<GitHubBrowserAuthorization, String> {
    let response = reqwest::Client::new()
        .post(service_endpoint("/api/v1/auth/github/desktop/start"))
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/json")
        .send()
        .await
        .map_err(error_text)?;
    if !response.status().is_success() {
        return Err(service_error(response, "GitHub browser authorization failed").await);
    }
    response
        .json::<GitHubBrowserAuthorization>()
        .await
        .map_err(error_text)
}

#[tauri::command]
pub async fn github_poll_browser_authorization(
    flow_id: String,
    poll_secret: String,
) -> Result<GitHubBrowserPoll, String> {
    let request = authorization_request(&flow_id, &poll_secret)?;
    let response = reqwest::Client::new()
        .post(service_endpoint("/api/v1/auth/github/desktop/poll"))
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/json")
        .json(&request)
        .send()
        .await
        .map_err(error_text)?;
    if response.status() == reqwest::StatusCode::ACCEPTED {
        let pending = response
            .json::<GitHubAuthorizationPending>()
            .await
            .map_err(error_text)?;
        return Ok(GitHubBrowserPoll {
            status: pending.status,
            retry_after_seconds: pending.retry_after_seconds.max(1),
            account: None,
        });
    }
    if !response.status().is_success() {
        return Err(service_error(response, "GitHub browser authorization failed").await);
    }
    let authorized = response
        .json::<GitHubBrowserAuthorizedResponse>()
        .await
        .map_err(error_text)?;
    if authorized.status != "authorized" || authorized.github_access_token.trim().is_empty() {
        return Err("GitHub authorization response is incomplete".to_string());
    }
    let account = GitHubAccount {
        display_name: if authorized.user.display_name.trim().is_empty() {
            authorized.user.github_login.clone()
        } else {
            authorized.user.display_name
        },
        login: authorized.user.github_login,
        avatar_url: authorized.user.avatar_url,
    };
    store_credential(account.clone(), authorized.github_access_token)?;
    Ok(GitHubBrowserPoll {
        status: "authorized".to_string(),
        retry_after_seconds: 0,
        account: Some(account),
    })
}

#[tauri::command]
pub async fn github_cancel_browser_authorization(
    flow_id: String,
    poll_secret: String,
) -> Result<(), String> {
    let request = authorization_request(&flow_id, &poll_secret)?;
    let response = reqwest::Client::new()
        .post(service_endpoint("/api/v1/auth/github/desktop/cancel"))
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/json")
        .json(&request)
        .send()
        .await
        .map_err(error_text)?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err(service_error(response, "GitHub authorization cancellation failed").await)
    }
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
        repositories.extend(page_values.into_iter().map(repository_view));
        if page_count < 100 {
            break;
        }
    }
    Ok(repositories)
}

#[tauri::command]
pub async fn github_create_repository(
    name: String,
    private: bool,
) -> Result<GitHubRepository, String> {
    let credential = stored_credential()?;
    let name = name.trim();
    if name.is_empty() {
        return Err("GitHub repository name is required".to_string());
    }
    let response = reqwest::Client::new()
        .post("https://api.github.com/user/repos")
        .header(USER_AGENT, "Combo-Desktop")
        .header(ACCEPT, "application/vnd.github+json")
        .header("X-GitHub-Api-Version", GITHUB_API_VERSION)
        .header(
            AUTHORIZATION,
            format!("Bearer {}", credential.github_access_token),
        )
        .json(&GitHubCreateRepositoryRequest {
            name,
            private,
            auto_init: false,
        })
        .send()
        .await
        .map_err(error_text)?;
    if !response.status().is_success() {
        return Err(format!(
            "GitHub repository creation failed: HTTP {}",
            response.status()
        ));
    }
    response
        .json::<GitHubRepositoryResponse>()
        .await
        .map(repository_view)
        .map_err(error_text)
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

#[derive(Serialize)]
struct GitHubAuthorizationRequest<'a> {
    flow_id: &'a str,
    poll_secret: &'a str,
}

fn authorization_request<'a>(
    flow_id: &'a str,
    poll_secret: &'a str,
) -> Result<GitHubAuthorizationRequest<'a>, String> {
    let flow_id = flow_id.trim();
    let poll_secret = poll_secret.trim();
    if flow_id.is_empty() || poll_secret.is_empty() {
        return Err("GitHub browser authorization session is required".to_string());
    }
    Ok(GitHubAuthorizationRequest {
        flow_id,
        poll_secret,
    })
}

fn service_endpoint(path: &str) -> String {
    format!("{}{}", COMBO_SERVICE_URL.trim_end_matches('/'), path)
}

async fn service_error(response: reqwest::Response, context: &str) -> String {
    let status = response.status();
    let payload = response.json::<GitHubServiceErrorEnvelope>().await.ok();
    let detail = payload
        .and_then(|value| value.error.map(|error| error.message).or(value.message))
        .filter(|message| !message.trim().is_empty());
    detail
        .map(|message| format!("{context}: {message}"))
        .unwrap_or_else(|| format!("{context}: HTTP {status}"))
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
