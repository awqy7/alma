#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use alma_core::{runner::Runner, runtime::WorkerLaunch, store::Store, worker::Worker};
use serde_json::{json, Value};
#[cfg(debug_assertions)]
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use tauri::{Emitter, Manager, State};
use tokio::sync::Mutex;

struct AppState {
    launch: WorkerLaunch,
    runner: Mutex<Runner>,
    pause: Arc<AtomicBool>,
}
#[tauri::command]
async fn inspect_documents(
    request: alma_core::inspection::InspectionRequest,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    alma_core::inspection::inspect_with_runtime(state.launch.clone(), request)
        .await
        .map_err(safe_error)
}
#[tauri::command]
async fn run_demo(
    request: alma_core::demo::DemoRequest,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    let db = app
        .path()
        .app_data_dir()
        .map_err(|_| "DATABASE_ERROR")?
        .join("demo.sqlite");
    alma_core::demo::run(state.launch.clone(), &db, request)
        .await
        .map_err(safe_error)
}
fn safe_error(error: Box<dyn std::error::Error + Send + Sync>) -> String {
    let text = error.to_string();
    if text.len() < 64 && text.chars().all(|c| c.is_ascii_uppercase() || c == '_') {
        text
    } else {
        "EXCEPTION".into()
    }
}
#[tauri::command]
async fn connect(url: String, state: State<'_, AppState>) -> Result<Value, String> {
    state
        .runner
        .lock()
        .await
        .worker
        .call("CONNECT", json!({"url":url}))
        .await
        .map_err(safe_error)
}
#[tauri::command]
async fn open_target(
    localizer: String,
    process_number: String,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    let mut runner = state.runner.try_lock().map_err(|_| "BUSY")?;
    for (command, payload) in [
        ("OPEN_LOCALIZER", json!({"name":localizer})),
        ("LIST_PROCESSES", json!({})),
        ("OPEN_PROCESS", json!({"process_number":process_number})),
        ("OPEN_REQUISITION", json!({})),
    ] {
        runner
            .worker
            .call(command, payload)
            .await
            .map_err(safe_error)?;
        let _ = app.emit("alma:event", json!({"action":command,"status":"DONE"}));
    }
    Ok(json!({"opened":true,"official_changes":0}))
}
#[tauri::command]
async fn check_session(state: State<'_, AppState>) -> Result<Value, String> {
    state
        .runner
        .lock()
        .await
        .worker
        .call("CHECK_SESSION", json!({}))
        .await
        .map_err(safe_error)
}
#[tauri::command]
async fn status(state: State<'_, AppState>) -> Result<Value, String> {
    let runner = state.runner.lock().await;
    Ok(
        json!({"reports":runner.store.reports().map_err(safe_error)?,"jobs":runner.store.jobs().map_err(safe_error)?,
        "events":runner.store.events().map_err(safe_error)?,"executions":runner.store.executions().map_err(safe_error)?,"queue":runner.store.queue_status().map_err(safe_error)?}),
    )
}
#[tauri::command]
fn pause(state: State<'_, AppState>) {
    state.pause.store(true, Ordering::SeqCst);
}
#[tauri::command]
async fn start_queue(localizer: String, app: tauri::AppHandle, state: State<'_, AppState>) -> Result<Value,String> {
    state.runner.try_lock().map_err(|_|"BUSY")?.start_queue(&localizer,|event|{let _=app.emit("alma:event",event);}).await.map_err(safe_error)
}
#[tauri::command]
async fn queue_step(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<Value,String> {
    state.runner.try_lock().map_err(|_|"BUSY")?.queue_step(|event|{let _=app.emit("alma:event",event);}).await.map_err(safe_error)
}
#[tauri::command]
async fn pause_queue(state: State<'_, AppState>) -> Result<(),String> {
    state.pause.store(true,Ordering::SeqCst);
    state.runner.lock().await.store.pause_queue().map_err(safe_error)
}
#[tauri::command]
async fn restart_worker(state: State<'_, AppState>) -> Result<(), String> {
    state
        .runner
        .try_lock()
        .map_err(|_| "BUSY".to_string())?
        .worker
        .restart()
        .await
        .map_err(safe_error)
}
#[tauri::command]
async fn review(
    job: Option<String>,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    // One owned runner serializes browser and SQLite access. Reject a second request.
    let mut runner = state.runner.try_lock().map_err(|_| "BUSY".to_string())?;
    state.pause.store(false, Ordering::SeqCst);
    let report = runner
        .review_current(job.as_deref(), |event| {
            let _ = app.emit("alma:event", event);
        })
        .await
        .map_err(safe_error)?;
    serde_json::to_value(report).map_err(|_| "IPC_ERROR".into())
}
#[tauri::command]
async fn apply_real_plan(
    plan: Value,
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    let mut runner = state.runner.try_lock().map_err(|_| "BUSY".to_string())?;
    runner
        .apply_real_plan(plan, |event| {
            let _ = app.emit("alma:event", event);
        })
        .await
        .map_err(safe_error)
}
fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    if args.get(1).is_some_and(|v| v == "--package-smoke") {
        let result = (|| -> alma_core::store::CoreResult<Value> {
            let exe = std::env::current_exe()?;
            let parent = exe.parent().ok_or("WORKER_CRASHED")?;
            #[cfg(target_os = "linux")]
            let resources = parent.join("../lib/ALMA");
            #[cfg(not(target_os = "linux"))]
            let resources = parent.to_path_buf();
            tauri::async_runtime::block_on(alma_core::runtime::verify_bundle(&resources))
        })();
        let (receipt, code) = match result {
            Ok(value) => (value, 0),
            Err(error) => (json!({"ok":false,"error":safe_error(error)}), 1),
        };
        let Some(output) = args.get(2) else {
            std::process::exit(2);
        };
        if std::fs::write(output, receipt.to_string()).is_err() {
            std::process::exit(2);
        }
        std::process::exit(code);
    }
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();
    tauri::Builder::default()
        .setup(|app| {
            #[cfg(debug_assertions)]
            let launch = WorkerLaunch::development(
                &PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../..")
                    .canonicalize()?,
            );
            #[cfg(not(debug_assertions))]
            let launch = WorkerLaunch::bundled(&app.path().resource_dir()?).map_err(|_| {
                std::io::Error::other("Pacote ALMA incompleto: reinstale o aplicativo.")
            })?;
            let data = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data)?;
            let store = Store::open(&data.join("alma.sqlite"))
                .map_err(|_| std::io::Error::other("DATABASE_ERROR"))?;
            let worker =
                tauri::async_runtime::block_on(Worker::spawn_launch(launch.clone(), false))
                    .map_err(|_| std::io::Error::other("WORKER_CRASHED"))?;
            let pause = Arc::new(AtomicBool::new(false));
            app.manage(AppState {
                launch,
                runner: Mutex::new(Runner {
                    store,
                    worker,
                    pause: pause.clone(),
                }),
                pause,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            connect,
            check_session,
            open_target,
            status,
            pause,
            review,
            apply_real_plan,
            restart_worker,
            start_queue,
            queue_step,
            pause_queue,
            inspect_documents,
            run_demo
        ])
        .build(tauri::generate_context!())
        .expect("ALMA desktop initialization failed")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                let state = app.state::<AppState>();
                state.pause.store(true, Ordering::SeqCst);
                tauri::async_runtime::block_on(async {
                    state.runner.lock().await.worker.shutdown().await;
                });
            }
        });
}
