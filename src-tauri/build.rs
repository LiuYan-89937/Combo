fn main() {
    println!("cargo:rerun-if-env-changed=COMBO_SERVICE_URL");
    let service_url =
        std::env::var("COMBO_SERVICE_URL").unwrap_or_else(|_| "https://liuyanai.top".to_string());
    println!("cargo:rustc-env=COMBO_SERVICE_URL={service_url}");
    tauri_build::build()
}
