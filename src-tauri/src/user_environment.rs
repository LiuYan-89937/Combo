use std::env;
use std::ffi::OsString;

#[cfg(any(target_os = "macos", target_os = "linux"))]
use std::collections::HashSet;
#[cfg(any(target_os = "macos", target_os = "linux"))]
use std::ffi::OsStr;
#[cfg(any(target_os = "macos", target_os = "linux"))]
use std::io::Read;
#[cfg(any(target_os = "macos", target_os = "linux"))]
use std::process::{Command, Stdio};
#[cfg(any(target_os = "macos", target_os = "linux"))]
use std::time::Duration;
#[cfg(any(target_os = "macos", target_os = "linux"))]
use wait_timeout::ChildExt;

#[cfg(any(target_os = "macos", target_os = "linux"))]
const SHELL_PATH_MARKER: &str = "__COMBO_SHELL_PATH__";
#[cfg(any(target_os = "macos", target_os = "linux"))]
const SHELL_DISCOVERY_TIMEOUT: Duration = Duration::from_secs(5);

/// Resolve the executable search path inherited by the Python backend.
///
/// GUI applications on macOS and Linux are commonly started with a minimal
/// PATH. Reading the interactive login shell restores user-managed runtimes
/// such as Homebrew Node, uv, bun, and pipx. The application path is appended
/// so platform-provided entries are not lost.
pub fn executable_path() -> Option<OsString> {
    let application_path = env::var_os("PATH");

    #[cfg(any(target_os = "macos", target_os = "linux"))]
    {
        let shell_path = interactive_login_shell_path();
        return merge_paths(shell_path.as_deref(), application_path.as_deref());
    }

    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    {
        application_path
    }
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
fn interactive_login_shell_path() -> Option<OsString> {
    let shell = env::var_os("SHELL")?;
    if shell.is_empty() {
        return None;
    }

    let script = format!("printf '\\n{SHELL_PATH_MARKER}%s\\n' \"$PATH\"");
    let mut child = Command::new(shell)
        .args(["-ilc", &script])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;

    let status = match child.wait_timeout(SHELL_DISCOVERY_TIMEOUT).ok()? {
        Some(status) => status,
        None => {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
    };
    if !status.success() {
        return None;
    }

    let mut output = String::new();
    child.stdout.take()?.read_to_string(&mut output).ok()?;
    let value = output
        .lines()
        .rev()
        .find_map(|line| line.strip_prefix(SHELL_PATH_MARKER))?
        .trim();
    (!value.is_empty()).then(|| OsString::from(value))
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
fn merge_paths(primary: Option<&OsStr>, fallback: Option<&OsStr>) -> Option<OsString> {
    let mut seen = HashSet::new();
    let mut paths = Vec::new();

    for value in [primary, fallback].into_iter().flatten() {
        for path in env::split_paths(value) {
            if !path.as_os_str().is_empty() && seen.insert(path.clone()) {
                paths.push(path);
            }
        }
    }

    (!paths.is_empty())
        .then(|| env::join_paths(paths).ok())
        .flatten()
}
