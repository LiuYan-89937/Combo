use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone, Serialize)]
pub struct OpenWithApplication {
    pub name: String,
    pub path: String,
    pub is_default: bool,
}

pub fn list_applications_for_path(source_path: &str) -> Result<Vec<OpenWithApplication>, String> {
    let source = existing_file(source_path)?;
    list_applications(&source)
}

pub fn open_path_with_application(source_path: &str, application_path: &str) -> Result<(), String> {
    let source = existing_file(source_path)?;
    if application_path.trim().is_empty() {
        return Err("Application path must not be empty".to_string());
    }
    open_with(&source, application_path)
}

#[tauri::command]
pub fn list_open_with_applications(
    source_path: String,
) -> Result<Vec<OpenWithApplication>, String> {
    list_applications_for_path(&source_path)
}

#[tauri::command]
pub fn open_with_application(source_path: String, application_path: String) -> Result<(), String> {
    open_path_with_application(&source_path, &application_path)
}

fn existing_file(source_path: &str) -> Result<PathBuf, String> {
    let source = PathBuf::from(source_path);
    if !source.exists() {
        return Err(format!("File does not exist: {}", source.display()));
    }
    if !source.is_file() {
        return Err(format!("Path is not a file: {}", source.display()));
    }
    source
        .canonicalize()
        .map_err(|error| format!("Failed to resolve {}: {error}", source.display()))
}

#[cfg(target_os = "macos")]
mod platform {
    use super::*;
    use std::collections::HashSet;
    use std::ffi::c_void;
    use std::os::raw::{c_char, c_int, c_long};

    type CFIndex = c_long;
    type CFTypeRef = *const c_void;
    type CFAllocatorRef = *const c_void;
    type CFStringRef = *const c_void;
    type CFURLRef = *const c_void;
    type CFArrayRef = *const c_void;
    type CFErrorRef = *const c_void;

    const K_CF_URL_POSIX_PATH_STYLE: c_int = 0;
    const K_CF_STRING_ENCODING_UTF8: u32 = 0x0800_0100;
    const K_LS_ALL_ROLES: u32 = 0xFFFF_FFFF;

    #[link(name = "CoreFoundation", kind = "framework")]
    unsafe extern "C" {
        fn CFRelease(cf: CFTypeRef);
        fn CFURLCreateFromFileSystemRepresentation(
            allocator: CFAllocatorRef,
            buffer: *const u8,
            buf_len: CFIndex,
            is_directory: bool,
        ) -> CFURLRef;
        fn CFURLCopyFileSystemPath(url: CFURLRef, path_style: c_int) -> CFStringRef;
        /// Out-parameter form: the value is returned through `property_value` and
        /// the caller owns a +1 reference when the call reports success.
        fn CFURLCopyResourcePropertyForKey(
            url: CFURLRef,
            key: CFStringRef,
            property_value: *mut CFTypeRef,
            error: *mut CFErrorRef,
        ) -> bool;
        fn CFStringGetLength(string: CFStringRef) -> CFIndex;
        fn CFStringGetCString(
            string: CFStringRef,
            buffer: *mut c_char,
            buffer_size: CFIndex,
            encoding: u32,
        ) -> bool;
        fn CFArrayGetCount(array: CFArrayRef) -> CFIndex;
        fn CFArrayGetValueAtIndex(array: CFArrayRef, index: CFIndex) -> CFTypeRef;
        static kCFURLLocalizedNameKey: CFStringRef;
    }

    #[link(name = "CoreServices", kind = "framework")]
    unsafe extern "C" {
        fn LSCopyApplicationURLsForURL(url: CFURLRef, roles: u32) -> CFArrayRef;
        fn LSCopyDefaultApplicationURLForURL(
            url: CFURLRef,
            roles: u32,
            error: *mut CFErrorRef,
        ) -> CFURLRef;
    }

    struct OwnedCf(CFTypeRef);
    impl Drop for OwnedCf {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe { CFRelease(self.0) };
            }
        }
    }

    fn cf_string(value: CFStringRef) -> Option<String> {
        if value.is_null() {
            return None;
        }
        let length = unsafe { CFStringGetLength(value) };
        let capacity = (length.max(0) as usize).saturating_mul(4).saturating_add(1);
        let mut bytes = vec![0 as c_char; capacity.max(1)];
        let converted = unsafe {
            CFStringGetCString(
                value,
                bytes.as_mut_ptr(),
                bytes.len() as CFIndex,
                K_CF_STRING_ENCODING_UTF8,
            )
        };
        if !converted {
            return None;
        }
        let end = bytes
            .iter()
            .position(|byte| *byte == 0)
            .unwrap_or(bytes.len());
        let raw = bytes[..end]
            .iter()
            .map(|byte| *byte as u8)
            .collect::<Vec<_>>();
        String::from_utf8(raw).ok()
    }

    fn url_path(url: CFURLRef) -> Option<String> {
        let path = unsafe { CFURLCopyFileSystemPath(url, K_CF_URL_POSIX_PATH_STYLE) };
        if path.is_null() {
            return None;
        }
        let owned = OwnedCf(path as CFTypeRef);
        let result = cf_string(path);
        drop(owned);
        result
    }

    /// Localized display name of an application bundle.
    ///
    /// `LSCopyDisplayNameForURL` is not used here: its real signature is
    /// `OSStatus LSCopyDisplayNameForURL(CFURLRef, CFStringRef *)`, so the
    /// single-argument copy that looks natural crashes by writing the result
    /// through an uninitialised out-pointer. The header deprecates it in favour
    /// of `kCFURLLocalizedNameKey`, which also returns a value we own.
    fn display_name(url: CFURLRef) -> Option<String> {
        let mut value: CFTypeRef = std::ptr::null();
        let mut error: CFErrorRef = std::ptr::null();
        let found = unsafe {
            CFURLCopyResourcePropertyForKey(url, kCFURLLocalizedNameKey, &mut value, &mut error)
        };
        if !error.is_null() {
            unsafe { CFRelease(error as CFTypeRef) };
        }
        if !found || value.is_null() {
            return None;
        }
        let owned = OwnedCf(value);
        let result = cf_string(value);
        drop(owned);
        result
    }

    pub(super) fn list(source: &Path) -> Result<Vec<OpenWithApplication>, String> {
        let bytes = source.to_string_lossy();
        let url = unsafe {
            CFURLCreateFromFileSystemRepresentation(
                std::ptr::null(),
                bytes.as_bytes().as_ptr(),
                bytes.len() as CFIndex,
                false,
            )
        };
        if url.is_null() {
            return Err(format!(
                "Failed to create file URL for {}",
                source.display()
            ));
        }
        let url_owned = OwnedCf(url as CFTypeRef);

        let mut default_error: CFErrorRef = std::ptr::null();
        let default_url =
            unsafe { LSCopyDefaultApplicationURLForURL(url, K_LS_ALL_ROLES, &mut default_error) };
        if !default_error.is_null() {
            unsafe { CFRelease(default_error as CFTypeRef) };
        }
        let default_owned = OwnedCf(default_url as CFTypeRef);
        let default_path = if default_url.is_null() {
            None
        } else {
            url_path(default_url)
        };

        let applications = unsafe { LSCopyApplicationURLsForURL(url, K_LS_ALL_ROLES) };
        if applications.is_null() {
            return Err(format!("No applications found for {}", source.display()));
        }
        let applications_owned = OwnedCf(applications as CFTypeRef);
        let mut result = Vec::new();
        let mut seen = HashSet::new();
        for index in 0..unsafe { CFArrayGetCount(applications) } {
            let application_url =
                unsafe { CFArrayGetValueAtIndex(applications, index) } as CFURLRef;
            if application_url.is_null() {
                continue;
            }
            let Some(path) = url_path(application_url) else {
                continue;
            };
            if !seen.insert(path.clone()) {
                continue;
            }
            let fallback = Path::new(&path)
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or(&path)
                .to_string();
            let name = display_name(application_url).unwrap_or(fallback);
            result.push(OpenWithApplication {
                is_default: default_path.as_deref() == Some(path.as_str()),
                name,
                path,
            });
        }
        drop(applications_owned);
        drop(default_owned);
        drop(url_owned);
        if result.is_empty() {
            return Err(format!("No applications found for {}", source.display()));
        }
        let mut result = deduplicate_by_name(result);
        result.sort_by(|left, right| {
            right
                .is_default
                .cmp(&left.is_default)
                .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
                .then_with(|| left.path.cmp(&right.path))
        });
        Ok(result)
    }

    /// Collapses applications that share a display name.
    ///
    /// LaunchServices registers the same product under several bundle paths (an
    /// updater cache, the Preboot cryptex volume, a Parallels shared disk), which
    /// would otherwise show up as repeated identical menu rows.
    fn deduplicate_by_name(applications: Vec<OpenWithApplication>) -> Vec<OpenWithApplication> {
        let mut unique: Vec<OpenWithApplication> = Vec::new();
        for application in applications {
            match unique
                .iter_mut()
                .find(|existing| existing.name.to_lowercase() == application.name.to_lowercase())
            {
                Some(existing) => {
                    if outranks(&application, existing) {
                        *existing = application;
                    }
                }
                None => unique.push(application),
            }
        }
        unique
    }

    /// Whether `candidate` is the better representative than `current` for a name.
    fn outranks(candidate: &OpenWithApplication, current: &OpenWithApplication) -> bool {
        if candidate.is_default != current.is_default {
            return candidate.is_default;
        }
        let candidate_installed = candidate.path.starts_with("/Applications/");
        let current_installed = current.path.starts_with("/Applications/");
        if candidate_installed != current_installed {
            return candidate_installed;
        }
        candidate.path.len() < current.path.len()
    }

    pub(super) fn open(source: &Path, application: &str) -> Result<(), String> {
        Command::new("open")
            .arg("-a")
            .arg(application)
            .arg(source)
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("Failed to open with application {application}: {error}"))
    }
}

#[cfg(not(target_os = "macos"))]
mod platform {
    use super::*;

    pub(super) fn list(_source: &Path) -> Result<Vec<OpenWithApplication>, String> {
        let path = if cfg!(target_os = "windows") {
            "start"
        } else {
            "xdg-open"
        };
        Ok(vec![OpenWithApplication {
            name: "Default application".to_string(),
            path: path.to_string(),
            is_default: true,
        }])
    }

    pub(super) fn open(source: &Path, application: &str) -> Result<(), String> {
        let result = if cfg!(target_os = "windows") {
            Command::new("cmd")
                .arg("/C")
                .arg("start")
                .arg("")
                .arg(application)
                .arg(source)
                .spawn()
        } else {
            Command::new(application).arg(source).spawn()
        };
        result
            .map(|_| ())
            .map_err(|error| format!("Failed to open with application {application}: {error}"))
    }
}

fn list_applications(source: &Path) -> Result<Vec<OpenWithApplication>, String> {
    platform::list(source)
}

fn open_with(source: &Path, application: &str) -> Result<(), String> {
    platform::open(source, application)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn list_open_with_applications_for_pdf() {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock before epoch")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("combo-open-with-{suffix}.pdf"));
        fs::write(&path, b"%PDF-1.4\n").expect("create test PDF");
        let path_string = path.to_string_lossy().into_owned();
        let result = list_applications_for_path(&path_string);
        println!("open_with applications for {path_string}: {result:#?}");
        let applications = result.expect("LaunchServices application enumeration");
        assert!(!applications.is_empty());
        assert_eq!(
            applications
                .iter()
                .filter(|application| application.is_default)
                .count(),
            1
        );
        fs::remove_file(path).expect("remove test PDF");
    }
}
