use serde::{Deserialize, Serialize};
#[derive(Serialize, Deserialize)]
pub struct ComputerPermissions {
    pub required: bool,
    pub accessibility: bool,
    pub screen_recording: bool,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ComputerPermission {
    Accessibility,
    ScreenRecording,
}

#[tauri::command]
pub async fn computer_permissions(app: tauri::AppHandle) -> Result<ComputerPermissions, String> {
    #[cfg(target_os = "macos")]
    {
        let result = tauri::async_runtime::spawn_blocking(move || {
            crate::computer_host::call_on_main_thread(
                &app,
                serde_json::json!({"op":"permissions"}),
                None,
            )
        })
        .await
        .map_err(|e| e.to_string())??;
        serde_json::from_value(result).map_err(|e| e.to_string())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Ok(ComputerPermissions {
            required: false,
            accessibility: true,
            screen_recording: true,
        })
    }
}
#[tauri::command]
pub async fn request_computer_permission(
    app: tauri::AppHandle,
    permission: ComputerPermission,
) -> Result<ComputerPermissions, String> {
    #[cfg(target_os = "macos")]
    {
        let name = match permission {
            ComputerPermission::Accessibility => "accessibility",
            ComputerPermission::ScreenRecording => "screen_recording",
        };
        let handle = app.clone();
        tauri::async_runtime::spawn_blocking(move || {
            crate::computer_host::call_on_main_thread(
                &handle,
                serde_json::json!({"op":"request_permission","permission":name}),
                None,
            )
        })
        .await
        .map_err(|e| e.to_string())??;
    }
    #[cfg(not(target_os = "macos"))]
    let _ = permission;
    computer_permissions(app).await
}
