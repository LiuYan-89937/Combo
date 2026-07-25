// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod python_sidecar;

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
    let sidecar = state.sidecar.lock().unwrap();
    match sidecar.as_ref() {
        Some(s) => serde_json::json!({
            "running": s.is_running(),
            "port": s.port(),
            "pid": s.pid(),
        }),
        None => serde_json::json!({
            "running": false,
            "port": null,
            "pid": null,
        }),
    }
}

/// Command to get the backend base URL for frontend API calls.
#[tauri::command]
fn backend_url(state: tauri::State<AppState>) -> String {
    let sidecar = state.sidecar.lock().unwrap();
    match sidecar.as_ref() {
        Some(s) => format!("http://127.0.0.1:{}", s.port()),
        None => "http://127.0.0.1:8000".to_string(),
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
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
        .invoke_handler(tauri::generate_handler![backend_status, backend_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
