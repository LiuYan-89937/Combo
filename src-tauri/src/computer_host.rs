//! Authenticated private transport to the upstream CU engine; no desktop policy here.
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread::{self, JoinHandle};
use std::time::Duration;
use tauri::AppHandle;
use uuid::Uuid;

#[derive(Clone, Debug)]
pub struct ComputerHostEndpoint {
    pub address: String,
    pub token: String,
}
struct Lease {
    id: String,
    cancelled: Arc<AtomicBool>,
}
pub struct ComputerHost {
    endpoint: ComputerHostEndpoint,
    shutdown: Arc<AtomicBool>,
    active: Arc<Mutex<Option<Lease>>>,
    thread: Option<JoinHandle<()>>,
}
impl ComputerHost {
    pub fn start(app: AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        listener.set_nonblocking(true)?;
        let endpoint = ComputerHostEndpoint {
            address: listener.local_addr()?.to_string(),
            token: Uuid::new_v4().to_string(),
        };
        let shutdown = Arc::new(AtomicBool::new(false));
        let active = Arc::new(Mutex::new(None::<Lease>));
        let engine = Arc::new(Engine::new(app));
        let worker = {
            let shutdown = shutdown.clone();
            let active = active.clone();
            let token = endpoint.token.clone();
            thread::spawn(move || {
                while !shutdown.load(Ordering::SeqCst) {
                    match listener.accept() {
                        Ok((stream, _)) => {
                            let engine = engine.clone();
                            let active = active.clone();
                            let token = token.clone();
                            let shutdown = shutdown.clone();
                            thread::spawn(move || serve(stream, &token, engine, active, shutdown));
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            thread::sleep(Duration::from_millis(25))
                        }
                        Err(_) => break,
                    }
                }
            })
        };
        Ok(Self {
            endpoint,
            shutdown,
            active,
            thread: Some(worker),
        })
    }
    pub fn endpoint(&self) -> ComputerHostEndpoint {
        self.endpoint.clone()
    }
    pub fn shutdown(&mut self) {
        self.shutdown.store(true, Ordering::SeqCst);
        if let Some(lease) = self.active.lock().unwrap().as_ref() {
            lease.cancelled.store(true, Ordering::SeqCst);
        }
        if let Some(worker) = self.thread.take() {
            let _ = worker.join();
        }
    }
}
impl Drop for ComputerHost {
    fn drop(&mut self) {
        self.shutdown();
    }
}

fn serve(
    mut stream: TcpStream,
    token: &str,
    engine: Arc<Engine>,
    active: Arc<Mutex<Option<Lease>>>,
    shutdown: Arc<AtomicBool>,
) {
    // Each connection has a dedicated blocking request loop. Accepted sockets
    // can inherit the listener's nonblocking mode on macOS.
    if let Err(error) = stream.set_nonblocking(false) {
        eprintln!("CU host connection setup failed: {error}");
        return;
    }
    let Ok(input) = stream.try_clone() else {
        return;
    };
    let mut reader = BufReader::new(input);
    let mut owned: Option<(String, Arc<AtomicBool>)> = None;
    loop {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => {}
            Err(error) => {
                eprintln!("CU host connection read failed: {error}");
                break;
            }
        }
        let response = (|| -> Result<Value, String> {
            let mut request: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
            if request["token"].as_str() != Some(token) {
                return Err("invalid host token".into());
            }
            if shutdown.load(Ordering::SeqCst) {
                return Err("host is stopping".into());
            }
            let operation = request["op"].as_str().unwrap_or("").to_owned();
            if operation == "cancel_session" {
                let guard = active.lock().unwrap();
                let matched = guard
                    .as_ref()
                    .filter(|lease| Some(lease.id.as_str()) == request["session_id"].as_str());
                if let Some(lease) = matched {
                    lease.cancelled.store(true, Ordering::SeqCst);
                }
                return Ok(json!({"cancelled":matched.is_some()}));
            }
            if operation == "start" {
                let mut guard = active.lock().unwrap();
                if owned.is_some() || guard.is_some() {
                    return Err("another CU session is active".into());
                }
                let id = Uuid::new_v4().to_string();
                let cancelled = Arc::new(AtomicBool::new(false));
                *guard = Some(Lease {
                    id: id.clone(),
                    cancelled: cancelled.clone(),
                });
                drop(guard);
                owned = Some((id.clone(), cancelled.clone()));
                engine.call(json!({"op":"start","session_id":id}), Some(cancelled))?;
                return Ok(json!({"session_id":id,"engine":"open-computer-use"}));
            }
            let (id, cancelled) = owned.as_ref().ok_or("inactive session")?;
            if request["session_id"].as_str() != Some(id.as_str()) {
                return Err("session ownership mismatch".into());
            }
            if operation == "stop" {
                engine.call(json!({"op":"stop","session_id":id}), None)?;
                *active.lock().unwrap() = None;
                owned = None;
                return Ok(json!({}));
            }
            if operation != "tools" && operation != "call" {
                return Err("unknown transport operation".into());
            }
            request.as_object_mut().unwrap().remove("token");
            engine.call(request, Some(cancelled.clone()))
        })();
        let output = match response {
            Ok(value) => json!({"ok":true,"result":value}),
            Err(error) => json!({"ok":false,"error":error}),
        };
        if let Err(error) = writeln!(stream, "{output}") {
            eprintln!("CU host connection write failed: {error}");
            break;
        }
    }
    if let Some((id, cancelled)) = owned {
        cancelled.store(true, Ordering::SeqCst);
        let _ = engine.call(json!({"op":"stop","session_id":id}), None);
        let mut guard = active.lock().unwrap();
        if guard.as_ref().is_some_and(|lease| lease.id == id) {
            *guard = None;
        }
    }
}

struct Engine {
    app: AppHandle,
    #[cfg(target_os = "windows")]
    worker: Mutex<Option<Worker>>,
}
impl Engine {
    fn new(app: AppHandle) -> Self {
        Self {
            app,
            #[cfg(target_os = "windows")]
            worker: Mutex::new(None),
        }
    }
    fn call(&self, request: Value, cancelled: Option<Arc<AtomicBool>>) -> Result<Value, String> {
        if cancelled
            .as_ref()
            .is_some_and(|flag| flag.load(Ordering::SeqCst))
        {
            return Err("session cancelled".into());
        }
        #[cfg(target_os = "macos")]
        let response = call_on_main_thread(&self.app, request, cancelled)?;
        #[cfg(target_os = "windows")]
        let response = {
            let mut worker = self.worker.lock().map_err(|_| "CU worker unavailable")?;
            if worker.is_none() {
                *worker = Some(Worker::start(&self.app)?);
            }
            let result = worker.as_mut().unwrap().call(&request);
            if result.is_err() {
                *worker = None;
            } // A broken worker is never replayed.
            result?
        };
        if let Some(error) = response["bridge_error"].as_str() {
            return Err(error.into());
        }
        Ok(response)
    }
}

#[cfg(target_os = "macos")]
extern "C" {
    fn combo_cu_dispatch(input: *const std::ffi::c_char) -> *mut std::ffi::c_char;
    fn combo_cu_free(output: *mut std::ffi::c_char);
}
#[cfg(target_os = "macos")]
pub fn call_on_main_thread(
    app: &AppHandle,
    request: Value,
    cancelled: Option<Arc<AtomicBool>>,
) -> Result<Value, String> {
    let (send, receive) = std::sync::mpsc::channel();
    app.run_on_main_thread(move || {
        let result = (|| {
            if cancelled
                .as_ref()
                .is_some_and(|flag| flag.load(Ordering::SeqCst))
            {
                return Err("session cancelled".to_string());
            }
            let input = std::ffi::CString::new(request.to_string()).map_err(|e| e.to_string())?;
            unsafe {
                let output = combo_cu_dispatch(input.as_ptr());
                if output.is_null() {
                    return Err("native engine returned no response".into());
                }
                let text = std::ffi::CStr::from_ptr(output)
                    .to_string_lossy()
                    .into_owned();
                combo_cu_free(output);
                serde_json::from_str(&text).map_err(|e| e.to_string())
            }
        })();
        let _ = send.send(result);
    })
    .map_err(|e| e.to_string())?;
    receive
        .recv()
        .map_err(|_| "native engine stopped".to_string())?
}

#[cfg(target_os = "windows")]
struct Worker {
    child: std::process::Child,
    input: std::process::ChildStdin,
    output: BufReader<std::process::ChildStdout>,
}
#[cfg(target_os = "windows")]
impl Worker {
    fn start(app: &AppHandle) -> Result<Self, String> {
        use std::process::{Command, Stdio};
        use tauri::Manager;
        let name = "combo-cu.exe";
        let bundled = app
            .path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("computer-use")
            .join(name);
        let path = if bundled.is_file() {
            bundled
        } else {
            std::env::current_exe()
                .map_err(|e| e.to_string())?
                .parent()
                .ok_or("executable directory unavailable")?
                .join("computer-use")
                .join(name)
        };
        let mut command = Command::new(path);
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        Ok(Self {
            input: child.stdin.take().unwrap(),
            output: BufReader::new(child.stdout.take().unwrap()),
            child,
        })
    }
    fn call(&mut self, request: &Value) -> Result<Value, String> {
        writeln!(self.input, "{request}").map_err(|e| e.to_string())?;
        let mut line = String::new();
        if self
            .output
            .read_line(&mut line)
            .map_err(|e| e.to_string())?
            == 0
        {
            return Err("CU worker exited; action outcome unknown".into());
        }
        serde_json::from_str(&line).map_err(|e| e.to_string())
    }
}
#[cfg(target_os = "windows")]
impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
