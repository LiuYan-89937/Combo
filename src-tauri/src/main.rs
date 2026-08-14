// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod desktop_file_actions;
mod git_repository;
mod github_account;
mod python_sidecar;
mod user_environment;

use desktop_file_actions::{reveal_in_file_manager, save_file_as, select_directory};
use git_repository::{
    git_begin_turn_snapshot, git_clone_repository, git_repository_diff, git_repository_status,
    git_revert_turn, git_turn_changes,
};
use github_account::{
    github_account, github_list_repositories, github_logout, github_poll_device_authorization,
    github_start_device_authorization,
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
            // Cleanup Python backend when the main window closes
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let app_handle = window.app_handle();
                let state = app_handle.state::<AppState>();
                if let Some(sidecar) = state.sidecar.lock().unwrap().as_mut() {
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
            git_begin_turn_snapshot,
            git_turn_changes,
            git_repository_diff,
            git_revert_turn,
            git_clone_repository,
            github_start_device_authorization,
            github_poll_device_authorization,
            github_account,
            github_list_repositories,
            github_logout,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
