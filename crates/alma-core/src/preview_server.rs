//! Local rehearsal transport only. Production desktop continues to use Tauri IPC.
use crate::{
    inspection::{inspect, InspectionRequest},
    store::CoreResult,
};
use std::{io::Read, path::Path, sync::Mutex};
use tiny_http::{Header, Method, Response, Server, StatusCode};

/// Persistent runner that keeps the Chromium session alive across requests.
struct LiveWorker {
    runner: crate::runner::Runner,
}

pub fn serve(root: &Path, port: u16) -> CoreResult<()> {
    let server = Server::http(("127.0.0.1", port))?;
    let address = server.server_addr().to_string();
    let origin = format!("http://{address}");
    println!("ALMA ensaio local: {origin}");
    let runtime = tokio::runtime::Runtime::new()?;
    let live: Mutex<Option<LiveWorker>> = Mutex::new(None);
    for mut request in server.incoming_requests() {
        let host = request
            .headers()
            .iter()
            .find(|h| h.field.equiv("Host"))
            .map(|h| h.value.as_str());
        let supplied_origin = request
            .headers()
            .iter()
            .find(|h| h.field.equiv("Origin"))
            .map(|h| h.value.as_str());
        if host != Some(address.as_str()) || supplied_origin.is_some_and(|o| o != origin) {
            let _ = request.respond(Response::empty(StatusCode(403)));
            continue;
        }
        // Helper: require origin for POST
        macro_rules! require_origin {
            () => {
                if supplied_origin != Some(origin.as_str()) {
                    let _ = request.respond(Response::empty(StatusCode(403)));
                    continue;
                }
            };
        }
        // Helper: JSON response
        macro_rules! json_respond {
            ($req:expr, $status:expr, $body:expr) => {{
                let _ = $req.respond(
                    Response::from_string($body)
                        .with_status_code($status)
                        .with_header(header("Content-Type", "application/json; charset=utf-8"))
                        .with_header(header("Cache-Control", "no-store")),
                );
            }};
        }

        if request.url() == "/api/status" {
            let result: CoreResult<serde_json::Value> = {
                let guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                if let Some(lw) = guard.as_ref() {
                    Ok(serde_json::json!({
                        "reports": lw.runner.store.reports()?,
                        "jobs": lw.runner.store.jobs()?,
                        "events": lw.runner.store.events()?,
                        "executions": lw.runner.store.executions()?,
                        "queue": lw.runner.store.queue_status()?,
                    }))
                } else {
                    let db_path = root.join("runtime/preview.sqlite");
                    if db_path.exists() {
                        let store = crate::store::Store::open(&db_path)?;
                        Ok(serde_json::json!({
                            "reports": store.reports()?,
                            "jobs": store.jobs()?,
                            "events": store.events()?,
                            "executions": store.executions()?,
                            "queue": store.queue_status()?,
                        }))
                    } else {
                        Ok(serde_json::json!({
                            "reports": [],
                            "jobs": [],
                            "events": [],
                            "executions": [],
                        }))
                    }
                }
            };
            match result {
                Ok(val) => json_respond!(request, 200, val.to_string()),
                Err(e) => json_respond!(request, 422, format!("{{\"error\":\"{e}\"}}")),
            }
            continue;
        }

        if request.method() == &Method::Post
            && matches!(
                request.url(),
                "/api/queue/start" | "/api/queue/step" | "/api/queue/pause"
            )
        {
            require_origin!();
            let action = request.url().to_owned();
            let mut body = Vec::new();
            request.as_reader().take(4097).read_to_end(&mut body)?;
            let result: CoreResult<serde_json::Value> = if body.len() > 4096 {
                Err("IPC_ERROR".into())
            } else {
                runtime.block_on(async {
                    let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                    let runner = &mut guard.as_mut().ok_or("NOT_CONNECTED")?.runner;
                    match action.as_str() {
                        "/api/queue/start" => {
                            let value: serde_json::Value = serde_json::from_slice(&body)?;
                            runner
                                .start_queue(
                                    value["localizer"].as_str().ok_or("IPC_ERROR")?,
                                    |_| {},
                                )
                                .await
                        }
                        "/api/queue/step" => runner.queue_step(|_| {}).await,
                        _ => {
                            runner
                                .pause
                                .store(true, std::sync::atomic::Ordering::SeqCst);
                            runner.store.pause_queue()?;
                            runner.store.queue_status()
                        }
                    }
                })
            };
            match result {
                Ok(value) => json_respond!(request, 200, value.to_string()),
                Err(error) => json_respond!(
                    request,
                    422,
                    serde_json::json!({"error":public_error(error.as_ref())}).to_string()
                ),
            }
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/connect" {
            require_origin!();
            let mut body = Vec::new();
            request.as_reader().take(4097).read_to_end(&mut body).ok();
            let result: CoreResult<serde_json::Value> = if body.len() > 4096 {
                Err("IPC_ERROR".into())
            } else {
                serde_json::from_slice::<serde_json::Value>(&body)
                    .map_err(|_| "IPC_ERROR".into())
                    .and_then(|req| {
                        let url = req["url"].as_str().unwrap_or("").to_string();
                        if url.is_empty() {
                            return Err("IPC_ERROR".into());
                        }
                        runtime.block_on(async {
                            let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                            // Shutdown existing worker if any
                            if let Some(mut lw) = guard.take() {
                                lw.runner.worker.shutdown().await;
                            }
                            let db_path = root.join("runtime/preview.sqlite");
                            if let Some(parent) = db_path.parent() {
                                std::fs::create_dir_all(parent).ok();
                            }
                            let store = crate::store::Store::open(&db_path)?;
                            let launch = crate::runtime::WorkerLaunch::development(root);
                            let worker = crate::worker::Worker::spawn_launch(launch, false).await?;
                            let pause =
                                std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
                            let mut runner = crate::runner::Runner {
                                store,
                                worker,
                                pause,
                            };
                            let connect_result = runner
                                .worker
                                .call("CONNECT", serde_json::json!({"url": url}))
                                .await?;
                            *guard = Some(LiveWorker { runner });
                            Ok(connect_result)
                        })
                    })
            };
            match result {
                Ok(val) => json_respond!(request, 200, val.to_string()),
                Err(e) => json_respond!(request, 422, format!("{{\"error\":\"{e}\"}}")),
            }
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/session" {
            require_origin!();
            let result: CoreResult<serde_json::Value> = runtime.block_on(async {
                let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                let lw = guard.as_mut().ok_or("NOT_CONNECTED")?;
                lw.runner
                    .worker
                    .call("CHECK_SESSION", serde_json::json!({}))
                    .await
            });
            match result {
                Ok(val) => json_respond!(request, 200, val.to_string()),
                Err(e) => json_respond!(request, 422, format!("{{\"error\":\"{e}\"}}")),
            }
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/review" {
            require_origin!();
            let mut body = Vec::new();
            request.as_reader().take(4097).read_to_end(&mut body).ok();
            let resume = serde_json::from_slice::<serde_json::Value>(&body)
                .ok()
                .and_then(|v| v["job"].as_str().map(String::from));
            let result: CoreResult<serde_json::Value> = runtime.block_on(async {
                let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                let lw = guard.as_mut().ok_or("NOT_CONNECTED")?;
                lw.runner
                    .pause
                    .store(false, std::sync::atomic::Ordering::SeqCst);
                let report = lw.runner.review_current(resume.as_deref(), |_| {}).await?;
                Ok(serde_json::to_value(report)?)
            });
            match result {
                Ok(val) => json_respond!(request, 200, val.to_string()),
                Err(e) => json_respond!(request, 422, format!("{{\"error\":\"{e}\"}}")),
            }
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/eproc" {
            require_origin!();
            let mut body = Vec::new();
            request
                .as_reader()
                .take(8 * 1024 * 1024 + 1)
                .read_to_end(&mut body)
                .ok();
            let result: CoreResult<serde_json::Value> = if body.len() > 8 * 1024 * 1024 {
                Err("IPC_ERROR".into())
            } else {
                serde_json::from_slice::<serde_json::Value>(&body)
                    .map_err(|_| "IPC_ERROR".into())
                    .and_then(|req| {
                        let command = req["command"].as_str().unwrap_or("").to_string();
                        let payload = req.get("payload").cloned().unwrap_or(serde_json::json!({}));
                        // Allowlist of commands safe for the preview session
                        let allowed = [
                            "CHECK_SESSION",
                            "READ_PROCESS",
                            "READ_REQUISITION",
                            "READ_BENEFICIARIES",
                            "READ_FEES",
                            "LIST_PROCESSES",
                            "OPEN_PROCESS",
                            "OPEN_REQUISITION",
                            "OPEN_LOCALIZER",
                            "INDEX_DOCUMENTS",
                            "DOWNLOAD_DOCUMENT",
                            "PARSE_DOCUMENT",
                            "LIST_REQUISITIONS",
                            "DISCOVER_PROCESSES",
                            "START_DIAGNOSTICS",
                            "STOP_DIAGNOSTICS",
                            "CLOSE_PROCESS",
                        ];
                        if !allowed.contains(&command.as_str()) {
                            return Err("IPC_ERROR".into());
                        }
                        runtime.block_on(async {
                            let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                            let lw = guard.as_mut().ok_or("NOT_CONNECTED")?;
                            lw.runner.worker.call(&command, payload).await
                        })
                    })
            };
            match result {
                Ok(val) => json_respond!(request, 200, val.to_string()),
                Err(e) => json_respond!(request, 422, format!("{{\"error\":\"{e}\"}}")),
            }
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/disconnect" {
            require_origin!();
            let result: CoreResult<serde_json::Value> = runtime.block_on(async {
                let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                if let Some(mut lw) = guard.take() {
                    lw.runner.worker.shutdown().await;
                }
                Ok(serde_json::json!({"disconnected": true}))
            });
            match result {
                Ok(val) => json_respond!(request, 200, val.to_string()),
                Err(e) => json_respond!(request, 422, format!("{{\"error\":\"{e}\"}}")),
            }
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/demo" {
            require_origin!();
            let mut body = Vec::new();
            request.as_reader().take(4097).read_to_end(&mut body)?;
            let result = if body.len() > 4096 {
                Err("IPC_ERROR".into())
            } else {
                serde_json::from_slice::<crate::demo::DemoRequest>(&body)
                    .map_err(|_| "IPC_ERROR".into())
                    .and_then(|req| {
                        runtime.block_on(crate::demo::run(
                            crate::runtime::WorkerLaunch::development(root),
                            &root.join("runtime/demo.sqlite"),
                            req,
                        ))
                    })
            };
            let (body,status)=match result {Ok(report)=>(report.to_string(),200),Err(_)=>("{\"error\":\"Demonstração interrompida. Nenhuma ação oficial foi executada.\"}".into(),422)};
            json_respond!(request, status, body);
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/apply_real_plan" {
            require_origin!();
            let mut body = Vec::new();
            request.as_reader().take(8193).read_to_end(&mut body)?;
            let result: Result<serde_json::Value, Box<dyn std::error::Error + Send + Sync>> =
                if body.len() > 8192 {
                    Err("IPC_ERROR".into())
                } else {
                    serde_json::from_slice::<serde_json::Value>(&body)
                        .map_err(|_| "IPC_ERROR".into())
                        .and_then(|plan| {
                            // Try persistent runner first, fall back to ephemeral
                            runtime.block_on(async {
                                let mut guard = live.lock().map_err(|_| "LOCK_ERROR")?;
                                if let Some(lw) = guard.as_mut() {
                                    return lw.runner.apply_real_plan(plan, |_| {}).await;
                                }
                                drop(guard);
                                let launch = crate::runtime::WorkerLaunch::development(root);
                                let mut worker =
                                    crate::worker::Worker::spawn_launch(launch, false).await?;
                                let res = worker.call("APPLY_REAL_PLAN", plan).await?;
                                worker.shutdown().await;
                                Ok(res)
                            })
                        })
                };
            let (body, status) = match result {
                Ok(val) => (val.to_string(), 200),
                Err(e) => (format!("{{\"error\":\"{}\"}}", e), 422),
            };
            json_respond!(request, status, body);
            continue;
        }
        if request.method() == &Method::Post && request.url() == "/api/inspect" {
            require_origin!();
            if request.body_length().is_some_and(|n| n > 48 * 1024 * 1024) {
                let _ = request.respond(Response::empty(StatusCode(403)));
                continue;
            }
            let mut bytes = Vec::new();
            request
                .as_reader()
                .take(48 * 1024 * 1024 + 1)
                .read_to_end(&mut bytes)?;
            let result = if bytes.len() > 48 * 1024 * 1024 {
                Err("IPC_ERROR".into())
            } else {
                serde_json::from_slice::<InspectionRequest>(&bytes)
                    .map_err(|_| "IPC_ERROR".into())
                    .and_then(|req| runtime.block_on(inspect(root, req)))
            };
            let (body,status)=match result {Ok(value)=>(value.to_string(),200),Err(_)=>("{\"error\":\"Não foi possível ler os arquivos ou os valores informados. Use até 4 PDFs ou HTMLs UTF-8 de 8 MB e valores no formato 2.790,00.\"}".into(),422)};
            json_respond!(request, status, body);
            continue;
        }
        if request.method() != &Method::Get {
            let _ = request.respond(Response::empty(StatusCode(405)));
            continue;
        }
        let url = request.url().split('?').next().unwrap_or("");
        let relative = if url == "/" {
            "index.html"
        } else {
            url.trim_start_matches('/')
        };
        if relative.contains("..")
            || relative.contains('%')
            || relative.contains('\\')
            || !(relative == "index.html" || relative.starts_with("assets/"))
        {
            let _ = request.respond(Response::empty(StatusCode(404)));
            continue;
        }
        let path = root.join("apps/desktop/dist").join(relative);
        let Ok(bytes) = std::fs::read(&path) else {
            let _ = request.respond(Response::empty(StatusCode(404)));
            continue;
        };
        let mime = match path.extension().and_then(|s| s.to_str()) {
            Some("js") => "text/javascript",
            Some("css") => "text/css",
            _ => "text/html; charset=utf-8",
        };
        let response=Response::from_data(bytes).with_header(header("Content-Type",mime)).with_header(header("Cache-Control","no-store"))
            .with_header(header("X-Content-Type-Options","nosniff"))
            .with_header(header("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src blob:; frame-src blob:; frame-ancestors 'none'"));
        let _ = request.respond(response);
    }
    Ok(())
}
fn header(name: &str, value: &str) -> Header {
    Header::from_bytes(name, value).unwrap()
}

fn public_error(error: &dyn std::error::Error) -> String {
    let text = error.to_string();
    if text.len() < 64 && text.chars().all(|c| c.is_ascii_uppercase() || c == '_') {
        text
    } else {
        "EXCEPTION".into()
    }
}
