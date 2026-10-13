//! Presentation mode executes real local DOM actions. No official session is used.
use crate::{inspection::evaluate, runtime::WorkerLaunch, store::CoreResult, worker::Worker};
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::Path;
static LIMIT: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
#[derive(Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct DemoRequest {
    #[serde(default)]
    pub show_browser: bool,
}

pub async fn run(launch: WorkerLaunch, db: &Path, request: DemoRequest) -> CoreResult<Value> {
    let _permit = LIMIT.try_acquire().map_err(|_| "BUSY")?;
    if let Some(parent) = db.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let connection = rusqlite::Connection::open(db)?;
    connection.execute_batch("PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS demo_runs(id TEXT PRIMARY KEY,status TEXT NOT NULL,report TEXT);
       UPDATE demo_runs SET status='INTERRUPTED' WHERE status='RUNNING';")?;
    let id = uuid::Uuid::new_v4().to_string();
    connection.execute("INSERT INTO demo_runs VALUES (?1,'RUNNING',NULL)", [&id])?;
    let result = execute(launch, request).await;
    match result {
        Ok(mut report) => {
            report["run_id"] = json!(id);
            connection.execute(
                "UPDATE demo_runs SET status='COMPLETED',report=?2 WHERE id=?1",
                rusqlite::params![id, report.to_string()],
            )?;
            Ok(report)
        }
        Err(error) => {
            connection.execute("UPDATE demo_runs SET status='FAILED' WHERE id=?1", [id])?;
            Err(error)
        }
    }
}
async fn execute(launch: WorkerLaunch, request: DemoRequest) -> CoreResult<Value> {
    let mut worker = Worker::spawn_launch(launch, true).await?;
    let result=async {
        let perception=worker.call("START_DEMO",json!({"show_browser":request.show_browser})).await?;
        let review=evaluate(&perception);
        let observed=|key:&str|review["observations"].as_array().and_then(|rows|rows.iter().find(|r|r["field"]==key)).and_then(|r|r["value"].as_str()).ok_or("NOT_VERIFIABLE");
        let plan=json!({"total":review["checks"][0]["expected"].as_str().ok_or("NOT_VERIFIABLE")?,"base_date":review["checks"][1]["expected"].as_str().ok_or("NOT_VERIFIABLE")?,"arrears":observed("arrears_amount")?,"expert":observed("expert_amount")?});
        let execution=worker.call("APPLY_DEMO",plan).await?;
        Ok::<_,Box<dyn std::error::Error+Send+Sync>>(json!({"mode":"DEMO","synthetic":true,"official_changes":0,"review":review,"execution":execution,"events":worker.events,"created_at":chrono::Utc::now().to_rfc3339()}))
    }.await;
    worker.shutdown().await;
    result
}
