// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod desktop_file_actions;
mod git_repository;
mod github_account;
mod python_sidecar;
mod user_environment;

use desktop_file_actions::{reveal_in_file_manager, save_file_as, select_directory};
use git_repository::{
    git_add_remote, git_begin_turn_snapshot, git_clone_repository, git_commit,
    git_fetch_repository, git_initialize_repository, git_pull_repository, git_push_repository,
    git_reapply_turn, git_repository_diff, git_repository_identity, git_repository_status,
    git_revert_turn, git_set_repository_identity, git_stage_all, git_stage_paths,
    git_sync_repository, git_turn_changes, git_unstage_paths,
};
use github_account::{
    github_account, github_cancel_browser_authorization, github_create_repository,
    github_list_repositories, github_logout, github_poll_browser_authorization,
    github_start_browser_authorization,
};
use python_sidecar::PythonSidecar;
use std::sync::Mutex;
use tauri::Manager;

/// Application state holding the Python backend sidecar handle.
struct AppState {
    sidecar: Mutex<Option<PythonSidecar>>,
}

/// Command to check if the Python backend is running.
#[tauri::command]
fn backend_status(state: tauri::State<AppState>) -> serde_json::Value {
    let mut sidecar = state.sidecar.lock().unwrap();
    match sidecar.as_mut() {
        Some(s) => {
            let running = s.is_running();
            serde_json::json!({
                "running": running,
                "port": s.port(),
                "pid": s.pid(),
                "error": s.last_error(),
                "log_path": s.log_path(),
                "log_tail": if running { None } else { s.log_tail() },
            })
        }
        None => serde_json::json!({
            "running": false,
            "port": null,
            "pid": null,
            "error": "Python backend process has not been initialized",
            "log_path": null,
            "log_tail": null,
        }),
    }
}

/// Command to get the backend base URL for frontend API calls.
#[tauri::command]
fn backend_url(state: tauri::State<AppState>) -> Result<String, String> {
    let mut sidecar = state.sidecar.lock().unwrap();
    match sidecar.as_mut() {
        Some(s) => {
            if s.is_running() {
                Ok(format!("http://127.0.0.1:{}", s.port()))
            } else {
                Err(format!(
                    "{}; log: {}",
                    s.last_error()
                        .unwrap_or("Python backend process is not running"),
                    s.log_path().display()
                ))
            }
        }
        None => Err("Python backend process has not been initialized".to_string()),
    }
}

#[tauri::command]
fn restart_backend(app: tauri::AppHandle, state: tauri::State<AppState>) -> Result<(), String> {
    {
        let mut sidecar = state.sidecar.lock().unwrap();
        if let Some(mut running) = sidecar.take() {
            running.shutdown();
        }
    }
    let restarted = PythonSidecar::spawn(&app).map_err(|error| error.to_string())?;
    *state.sidecar.lock().unwrap() = Some(restarted);
    Ok(())
}

#[tauri::command]
fn shutdown_backend(state: tauri::State<AppState>) {
    if let Some(mut running) = state.sidecar.lock().unwrap().take() {
        running.shutdown();
    }
}

#[tauri::command]
fn desktop_platform() -> &'static str {
    std::env::consts::OS
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(
            |app, _arguments, _working_directory| {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            },
        ))
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(AppState {
            sidecar: Mutex::new(None),
        })
        .setup(|app| {
            // Launch Python backend as a sidecar process
            let app_handle = app.handle().clone();
            let sidecar = PythonSidecar::spawn(&app_handle)?;

            // Store the sidecar handle in app state
            let state = app.state::<AppState>();
            *state.sidecar.lock().unwrap() = Some(sidecar);

            Ok(())
        })
        .on_window_event(|window, event| {
            // Let the window disappear before waiting for backend shutdown.
            if let tauri::WindowEvent::Destroyed = event {
                let app_handle = window.app_handle();
                let state = app_handle.state::<AppState>();
                if let Some(mut sidecar) = state.sidecar.lock().unwrap().take() {
                    sidecar.shutdown();
                };
            }
        })
        .invoke_handler(tauri::generate_handler![
            backend_status,
            backend_url,
            restart_backend,
            shutdown_backend,
            desktop_platform,
            reveal_in_file_manager,
            save_file_as,
            select_directory,
            git_repository_status,
            git_initialize_repository,
            git_add_remote,
            git_repository_identity,
            git_set_repository_identity,
            git_stage_paths,
            git_stage_all,
            git_unstage_paths,
            git_commit,
            git_fetch_repository,
            git_pull_repository,
            git_push_repository,
            git_sync_repository,
            git_begin_turn_snapshot,
            git_turn_changes,
            git_repository_diff,
            git_revert_turn,
            git_reapply_turn,
            git_clone_repository,
            github_start_browser_authorization,
            github_poll_browser_authorization,
            github_cancel_browser_authorization,
            github_account,
            github_list_repositories,
            github_create_repository,
            github_logout,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
