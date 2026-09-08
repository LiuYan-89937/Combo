use std::{env, fs, path::PathBuf, process::Command};

fn run(command: &mut Command) {
    let status = command
        .status()
        .expect("could not start native CU build tool");
    assert!(status.success(), "native CU build failed: {command:?}");
}

fn build_computer_use() {
    let manifest = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let source = manifest.join("../native/computer-use");
    let output = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let resources = manifest.join("resources/computer-use");
    fs::create_dir_all(&resources).unwrap();
    for name in ["LICENSE", "THIRD_PARTY_NOTICES.md", "UPSTREAM.json"] {
        fs::copy(source.join(name), resources.join(name)).unwrap();
    }
    println!("cargo:rerun-if-changed={}", source.display());
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap();
    let arch = env::var("CARGO_CFG_TARGET_ARCH").unwrap();
    let artifact = if os == "macos" {
        let swift_arch = match arch.as_str() {
            "aarch64" => "arm64",
            "x86_64" => "x86_64",
            _ => panic!("unsupported macOS architecture"),
        };
        let scratch = output.join("swift");
        run(Command::new("swift")
            .arg("build")
            .arg("--package-path")
            .arg(&source)
            .arg("--scratch-path")
            .arg(&scratch)
            .args([
                "-c",
                "release",
                "--arch",
                swift_arch,
                "--product",
                "ComboCU",
            ]));
        let result = Command::new("swift")
            .arg("build")
            .arg("--package-path")
            .arg(&source)
            .arg("--scratch-path")
            .arg(&scratch)
            .args(["-c", "release", "--arch", swift_arch, "--show-bin-path"])
            .output()
            .expect("Swift output path unavailable");
        assert!(result.status.success(), "Swift output path unavailable");
        let binary = PathBuf::from(String::from_utf8(result.stdout).unwrap().trim())
            .join("libComboCU.dylib");
        let name = "libComboCU.dylib";
        fs::copy(binary, resources.join(name)).unwrap();
        println!("cargo:rustc-link-search=native={}", resources.display());
        println!("cargo:rustc-link-lib=dylib=ComboCU");
        println!("cargo:rustc-link-arg=-Wl,-rpath,@executable_path/../Frameworks");
        println!("cargo:rustc-link-arg=-Wl,-rpath,@executable_path/computer-use");
        name
    } else {
        assert!(os == "windows", "Combo CU supports only macOS and Windows");
        let go_arch = match arch.as_str() {
            "aarch64" => "arm64",
            "x86_64" => "amd64",
            _ => panic!("unsupported CU architecture"),
        };
        let name = "combo-cu.exe";
        run(Command::new("go")
            .current_dir(source.join(&os))
            .env("GOOS", &os)
            .env("GOARCH", go_arch)
            .args(["build", "-trimpath", "-o"])
            .arg(resources.join(name))
            .arg("."));
        name
    };
    // Direct cargo runs use an adjacent artifact; packaged apps use bundle resources/frameworks.
    let profile = output.ancestors().nth(3).expect("Cargo profile path");
    let adjacent = profile.join("computer-use");
    fs::create_dir_all(&adjacent).unwrap();
    fs::copy(resources.join(artifact), adjacent.join(artifact)).unwrap();
}

fn main() {
    println!("cargo:rerun-if-env-changed=COMBO_SERVICE_URL");
    let service_url =
        env::var("COMBO_SERVICE_URL").unwrap_or_else(|_| "https://liuyanai.top".to_string());
    println!("cargo:rustc-env=COMBO_SERVICE_URL={service_url}");
    build_computer_use();
    tauri_build::build()
}
