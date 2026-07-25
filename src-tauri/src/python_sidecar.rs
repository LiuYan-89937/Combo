use std::env;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use tauri::{AppHandle, Manager};

/// Python backend sidecar process manager.
pub struct PythonSidecar {
    process: Option<Child>,
    port: u16,
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

        let (project_root, system_package_root) = if cfg!(debug_assertions) {
            // In dev mode, get from CARGO_MANIFEST_DIR at build time
            // The manifest is in src-tauri/, so parent is project root
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .ok_or("Cannot determine project root")?
                .to_path_buf();
            let system_packages = root.join("SystemPackage");
            (root, system_packages)
        } else {
            // Production state belongs to the per-user application data
            // directory. Bundled resources remain immutable application assets.
            let root = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(root.join(".agentfactory"))?;
            let system_packages = resource_dir.join("SystemPackage");
            (root, system_packages)
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
            .current_dir(&project_root)
            .env("AGENTFACTORY_NATIVE_RUNTIME", "1")
            .env("AGENTFACTORY_PORT", &port_str)
            .env("AGENTFACTORY_PROJECT_ROOT", &project_root)
            .env("AGENTFACTORY_SYSTEM_PACKAGE_ROOT", &system_package_root)
            .env("AGENTFACTORY_PARENT_STDIN_WATCHDOG", "1")
            .stdin(Stdio::piped());

        if !cfg!(debug_assertions) {
            let mut python_paths = vec![resource_dir];
            if let Some(existing) = env::var_os("PYTHONPATH") {
                python_paths.extend(env::split_paths(&existing));
            }
            cmd.env("PYTHONPATH", env::join_paths(python_paths)?);
        }

        println!("Launching Python backend: {:?}", cmd);
        let process = cmd.spawn()?;

        Ok(Self {
            process: Some(process),
            port,
        })
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
        self.process
            .as_mut()
            .is_some_and(|process| matches!(process.try_wait(), Ok(None)))
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
