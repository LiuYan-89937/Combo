use std::env;
use std::fs::{self, File, OpenOptions};
use std::io;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use tauri::{AppHandle, Manager};

use crate::user_environment;

#[cfg(all(windows, not(debug_assertions)))]
use std::os::windows::process::CommandExt;
#[cfg(all(windows, not(debug_assertions)))]
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

const BACKEND_LOG_TAIL_BYTES: usize = 12_000;

/// Python backend sidecar process manager.
pub struct PythonSidecar {
    process: Option<Child>,
    port: u16,
    log_path: PathBuf,
    last_error: Option<String>,
}

impl PythonSidecar {
    /// Spawn the Python backend process.
    pub fn spawn(app: &AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let port = Self::allocate_loopback_port()?;
        let port_str = port.to_string();
        let resource_dir = app.path().resource_dir()?;

        // Determine Python executable path
        // In development: use system Python
        // In production: use bundled Python runtime
        let python_path = if cfg!(debug_assertions) {
            Self::find_system_python()?
        } else {
            Self::find_bundled_python(app)?
        };

        let (project_root, data_root) = if cfg!(debug_assertions) {
            // In dev mode, get from CARGO_MANIFEST_DIR at build time
            // The manifest is in src-tauri/, so parent is project root
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .ok_or("Cannot determine project root")?
                .to_path_buf();
            (root.clone(), root)
        } else {
            // Application resources are immutable. Runtime state belongs to the
            // per-user application data directory and survives app upgrades.
            let data_root = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(data_root.join(".agentfactory"))?;
            (resource_dir.clone(), data_root)
        };
        let log_path = data_root
            .join(".agentfactory")
            .join("logs")
            .join("backend.log");
        let (stdout_log, stderr_log) = Self::open_backend_log(&log_path)?;

        // Launch Python backend
        let mut cmd = Command::new(&python_path);
        cmd.arg("-m")
            .arg("uvicorn")
            .arg("web_frontend.backend.event_api_server:app")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&project_root)
            .env("AGENTFACTORY_PORT", &port_str)
            .env("AGENTFACTORY_PROJECT_ROOT", &project_root)
            .env("AGENTFACTORY_DATA_ROOT", &data_root)
            .env("AGENTFACTORY_PARENT_STDIN_WATCHDOG", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("PYTHONUTF8", "1")
            .env("PYTHONUNBUFFERED", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::from(stdout_log))
            .stderr(Stdio::from(stderr_log));

        if let Some(path) = user_environment::executable_path() {
            cmd.env("PATH", path);
        }

        #[cfg(all(windows, not(debug_assertions)))]
        cmd.creation_flags(CREATE_NO_WINDOW);

        if !cfg!(debug_assertions) {
            let mut python_paths = vec![resource_dir.clone()];
            if let Some(existing) = env::var_os("PYTHONPATH") {
                python_paths.extend(env::split_paths(&existing));
            }
            cmd.env("PYTHONPATH", env::join_paths(python_paths)?);
            cmd.env(
                "PLAYWRIGHT_BROWSERS_PATH",
                resource_dir.join("python").join("playwright-browsers"),
            );
        }

        println!("Launching Python backend: {:?}", cmd);
        let process = cmd.spawn()?;

        Ok(Self {
            process: Some(process),
            port,
            log_path,
            last_error: None,
        })
    }

    fn open_backend_log(path: &Path) -> io::Result<(File, File)> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let stdout = OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(path)?;
        let stderr = stdout.try_clone()?;
        Ok((stdout, stderr))
    }

    fn allocate_loopback_port() -> std::io::Result<u16> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        listener.local_addr().map(|address| address.port())
    }

    /// Find system Python executable (development mode).
    fn find_system_python() -> Result<PathBuf, Box<dyn std::error::Error>> {
        // In dev mode, prefer venv Python if it exists
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let project_root = manifest_dir.parent().ok_or("Cannot find project root")?;
        let venv_python = project_root.join(".venv").join("bin").join("python");

        if venv_python.exists() {
            return Ok(venv_python);
        }

        // Fallback to system Python
        for name in &["python3", "python"] {
            if let Ok(output) = Command::new(name).arg("--version").output() {
                if output.status.success() {
                    return Ok(PathBuf::from(name));
                }
            }
        }
        Err("Python executable not found".into())
    }

    /// Find bundled Python runtime (production mode).
    fn find_bundled_python(app: &AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
        let resource_dir = app.path().resource_dir()?;
        let python_path = if cfg!(target_os = "windows") {
            resource_dir.join("python").join("python.exe")
        } else {
            resource_dir.join("python").join("bin").join("python3")
        };

        if python_path.exists() {
            Ok(python_path)
        } else {
            Err(format!("Bundled Python not found at {:?}", python_path).into())
        }
    }

    /// Check if the backend process is still running.
    pub fn is_running(&mut self) -> bool {
        let Some(process) = self.process.as_mut() else {
            return false;
        };
        match process.try_wait() {
            Ok(None) => true,
            Ok(Some(status)) => {
                self.record_exit_status(status);
                false
            }
            Err(error) => {
                self.last_error = Some(format!("Failed to query backend process: {error}"));
                false
            }
        }
    }

    /// Get the backend port.
    pub fn port(&self) -> u16 {
        self.port
    }

    /// Get the process ID (if running).
    pub fn pid(&self) -> Option<u32> {
        self.process.as_ref().map(|p| p.id())
    }

    pub fn log_path(&self) -> &Path {
        &self.log_path
    }

    pub fn last_error(&self) -> Option<&str> {
        self.last_error.as_deref()
    }

    pub fn log_tail(&self) -> Option<String> {
        let content = fs::read(&self.log_path).ok()?;
        if content.is_empty() {
            return None;
        }
        let start = content.len().saturating_sub(BACKEND_LOG_TAIL_BYTES);
        Some(String::from_utf8_lossy(&content[start..]).into_owned())
    }

    fn record_exit_status(&mut self, status: ExitStatus) {
        if self.last_error.is_none() {
            self.last_error = Some(format!("Python backend exited with status {status}"));
        }
    }

    /// Shutdown the Python backend gracefully.
    pub fn shutdown(&mut self) {
        if let Some(mut process) = self.process.take() {
            println!("Shutting down Python backend (PID: {})", process.id());
            let _ = process.kill();
            if let Ok(status) = process.wait() {
                self.record_exit_status(status);
            }
        }
    }
}

impl Drop for PythonSidecar {
    fn drop(&mut self) {
        self.shutdown();
    }
}
