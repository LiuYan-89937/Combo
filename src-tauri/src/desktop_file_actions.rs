use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

#[tauri::command]
pub fn reveal_in_file_manager(source_path: String) -> Result<(), String> {
    let source = existing_path(&source_path)?;
    reveal_path(&source)
}

#[tauri::command]
pub fn save_file_as(source_path: String) -> Result<Option<String>, String> {
    let source = existing_file(&source_path)?;
    let suggested_name = source
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| "Source file has no valid file name".to_string())?;
    let destination = rfd::FileDialog::new()
        .set_file_name(suggested_name)
        .save_file();
    let Some(destination) = destination else {
        return Ok(None);
    };
    if same_path(&source, &destination) {
        return Ok(Some(destination.to_string_lossy().into_owned()));
    }
    fs::copy(&source, &destination).map_err(|error| {
        format!(
            "Failed to save {} as {}: {error}",
            source.display(),
            destination.display()
        )
    })?;
    Ok(Some(destination.to_string_lossy().into_owned()))
}

fn existing_path(source_path: &str) -> Result<PathBuf, String> {
    let source = PathBuf::from(source_path);
    if !source.exists() {
        return Err(format!(
            "Workspace entry does not exist: {}",
            source.display()
        ));
    }
    source
        .canonicalize()
        .map_err(|error| format!("Failed to resolve {}: {error}", source.display()))
}

fn existing_file(source_path: &str) -> Result<PathBuf, String> {
    let source = existing_path(source_path)?;
    if !source.is_file() {
        return Err(format!(
            "Workspace entry is not a file: {}",
            source.display()
        ));
    }
    Ok(source)
}

fn same_path(left: &Path, right: &Path) -> bool {
    right
        .canonicalize()
        .map(|resolved| resolved == left)
        .unwrap_or(false)
}

#[cfg(target_os = "macos")]
fn reveal_path(source: &Path) -> Result<(), String> {
    spawn_file_manager(Command::new("open").arg("-R").arg(source), "Finder")
}

#[cfg(target_os = "windows")]
fn reveal_path(source: &Path) -> Result<(), String> {
    let selection = format!("/select,{}", source.display());
    spawn_file_manager(
        Command::new("explorer.exe").arg(selection),
        "Windows Explorer",
    )
}

#[cfg(all(unix, not(target_os = "macos")))]
fn reveal_path(source: &Path) -> Result<(), String> {
    let target = if source.is_dir() {
        source
    } else {
        source.parent().ok_or_else(|| {
            format!(
                "Workspace file has no parent directory: {}",
                source.display()
            )
        })?
    };
    spawn_file_manager(
        Command::new("xdg-open").arg(target),
        "the system file manager",
    )
}

fn spawn_file_manager(command: &mut Command, application: &str) -> Result<(), String> {
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Failed to open {application}: {error}"))
}
