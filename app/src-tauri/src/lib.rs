use std::fs;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;

struct PythonProcess(Mutex<Option<Child>>);

#[tauri::command]
fn get_api_port() -> Result<u16, String> {
    let port_file = std::env::temp_dir().join("pies-alac-rip.port");
    fs::read_to_string(&port_file)
        .map_err(|e| e.to_string())?
        .trim()
        .parse::<u16>()
        .map_err(|e| e.to_string())
}

fn find_python() -> PathBuf {
    // CARGO_MANIFEST_DIR = app/src-tauri; project root is two levels up
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf();
    let venv = project_root.join(".venv/bin/python3");
    if venv.exists() {
        venv
    } else {
        PathBuf::from("python3")
    }
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn wait_for_python(timeout: Duration) -> bool {
    let port_file = std::env::temp_dir().join("pies-alac-rip.port");
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Ok(content) = fs::read_to_string(&port_file) {
            if let Ok(port) = content.trim().parse::<u16>() {
                let url = format!("http://127.0.0.1:{}/health", port);
                if ureq::get(&url)
                    .call()
                    .map(|r| r.status() == 200)
                    .unwrap_or(false)
                {
                    return true;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Remove stale port file from a previous run
    let port_file = std::env::temp_dir().join("pies-alac-rip.port");
    let _ = fs::remove_file(&port_file);

    let python = find_python();
    let root = project_root();

    let child = Command::new(&python)
        .args(["-m", "alac_rip.server"])
        .current_dir(&root)
        .spawn()
        .expect("Failed to spawn Python server — is the venv set up?");

    tauri::Builder::default()
        .setup(move |app| {
            app.manage(PythonProcess(Mutex::new(Some(child))));

            if !wait_for_python(Duration::from_secs(15)) {
                eprintln!("WARNING: Python server did not respond within 15 seconds");
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Ok(mut guard) = window.state::<PythonProcess>().0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![get_api_port])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
