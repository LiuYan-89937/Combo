use std::process::{Child, Command};
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

/// Python backend sidecar process manager.
pub struct PythonSidecar {
    process: Option<Child>,
    port: u16,
}

impl PythonSidecar {
    /// Spawn the Python backend process.
    pub fn spawn(app: &AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let port = 8000u16; // TODO: dynamic port allocation

        // Determine Python executable path
        // In development: use system Python
        // In production: use bundled Python runtime
        let python_path = if cfg!(debug_assertions) {
            Self::find_system_python()?
        } else {
            Self::find_bundled_python(app)?
        };

        // Set environment variables for native runtime mode
        let mut env_vars = std::collections::HashMap::new();
        env_vars.insert("AGENTFACTORY_NATIVE_RUNTIME", "1");
        env_vars.insert("AGENTFACTORY_PORT", &port.to_string());

        // Get project root (parent of src-tauri in dev, resource dir in prod)
        let project_root = if cfg!(debug_assertions) {
            app.path().app_config_dir()?
                .parent()
                .and_then(|p| p.parent())
                .ok_or("Cannot determine project root")?
                .to_path_buf()
        } else {
            app.path().resource_dir()?
        };

        // Launch Python backend
        let mut cmd = Command::new(&python_path);
        cmd.arg("-m")
            .arg("uvicorn")
            .arg("web_frontend.backend.event_api_server:app")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&project_root);

        // Inject environment variables
        for (key, value) in env_vars {
            cmd.env(key, value);
        }

        println!("Launching Python backend: {:?}", cmd);
        let process = cmd.spawn()?;

        Ok(Self {
            process: Some(process),
            port,
        })
    }

    /// Find system Python executable (development mode).
    fn find_system_python() -> Result<PathBuf, Box<dyn std::error::Error>> {
        // Try common Python names
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
    pub fn is_running(&self) -> bool {
        self.process.is_some()
    }

    /// Get the backend port.
    pub fn port(&self) -> u16 {
        self.port
    }

    /// Get the process ID (if running).
    pub fn pid(&self) -> Option<u32> {
        self.process.as_ref().map(|p| p.id())
    }

    /// Shutdown the Python backend gracefully.
    pub fn shutdown(&mut self) {
        if let Some(mut process) = self.process.take() {
            println!("Shutting down Python backend (PID: {})", process.id());
            let _ = process.kill();
            let _ = process.wait();
        }
    }
}

impl Drop for PythonSidecar {
    fn drop(&mut self) {
        self.shutdown();
    }
}
