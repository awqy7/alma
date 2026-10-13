use crate::{runtime::WorkerLaunch, store::CoreResult};
use serde_json::{json, Value};
use std::{path::Path, process::Stdio, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout},
    time::timeout,
};

#[derive(Debug, thiserror::Error)]
#[error("{code}")]
pub struct WorkerError {
    pub code: String,
    pub retryable: bool,
}
pub struct Worker {
    child: Child,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
    pub events: Vec<Value>,
    pub deadline: Duration,
    governor: crate::governor::ResourceGovernor,
    _scratch: tempfile::TempDir,
    launch: WorkerLaunch,
    fixture: bool,
}
impl Worker {
    pub fn stage_document(
        &self,
        index: usize,
        name: &str,
        bytes: &[u8],
    ) -> CoreResult<std::path::PathBuf> {
        if name.to_ascii_lowercase().ends_with(".html")
            || name.to_ascii_lowercase().ends_with(".htm")
        {
            if bytes.len() > 8 * 1024 * 1024 || std::str::from_utf8(bytes).is_err() {
                return Err("NOT_VERIFIABLE".into());
            }
            let path = self._scratch.path().join(format!("upload-{index}.html"));
            std::fs::write(&path, bytes)?;
            Ok(path)
        } else {
            self.stage_pdf(index, bytes)
        }
    }
    pub fn stage_pdf(&self, index: usize, bytes: &[u8]) -> CoreResult<std::path::PathBuf> {
        if bytes.len() > 8 * 1024 * 1024 || !bytes.starts_with(b"%PDF-") {
            return Err("PDF_PARSE_FAILED".into());
        }
        let path = self._scratch.path().join(format!("upload-{index}.pdf"));
        std::fs::write(&path, bytes)?;
        Ok(path)
    }
    pub async fn spawn(root: &Path, python: &Path, fixture: bool) -> CoreResult<Self> {
        Self::spawn_launch(
            WorkerLaunch::Development {
                root: root.into(),
                python: python.into(),
            },
            fixture,
        )
        .await
    }
    pub async fn spawn_launch(launch: WorkerLaunch, fixture: bool) -> CoreResult<Self> {
        let scratch = tempfile::Builder::new().prefix("alma-worker-").tempdir()?;
        let mut command = launch.command(scratch.path());
        command.env("ALMA_TEMP_ROOT", scratch.path());
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        if fixture {
            command.arg("--fixture-mode");
        }
        let mut child = command.spawn()?;
        let input = child.stdin.take().ok_or("WORKER_CRASHED")?;
        let output = BufReader::new(child.stdout.take().ok_or("WORKER_CRASHED")?);
        let mut worker = Self {
            child,
            input: Some(input),
            output,
            events: vec![],
            deadline: Duration::from_secs(100),
            governor: Default::default(),
            _scratch: scratch,
            launch,
            fixture,
        };
        worker.call("PING", json!({})).await?;
        Ok(worker)
    }
    pub async fn call(&mut self, name: &str, payload: Value) -> CoreResult<Value> {
        // Only idempotent reads/downloads are retried, and only explicit 429/5xx.
        for attempt in 0..3 {
            let start = std::time::Instant::now();
            if name != "CLOSE_PROCESS" && !self.governor.allow(start) {
                return Err("RATE_LIMITED".into());
            }
            tokio::time::sleep(self.governor.spacing()).await;
            let result = self.call_once(name, payload.clone()).await;
            let retry = result
                .as_ref()
                .err()
                .and_then(|e| e.downcast_ref::<WorkerError>())
                .is_some_and(|e| {
                    e.retryable && matches!(e.code.as_str(), "HTTP_ERROR" | "RATE_LIMITED")
                });
            self.governor
                .record(start.elapsed(), !retry, std::time::Instant::now());
            if !retry
                || attempt == 2
                || !matches!(
                    name,
                    "READ_PROCESS" | "READ_REQUISITION" | "INDEX_DOCUMENTS" | "DOWNLOAD_DOCUMENT"
                )
            {
                return result;
            }
            tokio::time::sleep(crate::governor::ResourceGovernor::backoff(attempt)).await;
        }
        Err("HTTP_ERROR".into())
    }
    async fn call_once(&mut self, name: &str, payload: Value) -> CoreResult<Value> {
        let id = uuid::Uuid::new_v4().to_string();
        let message = json!({"version":1,"id":id,"type":"COMMAND","name":name,"payload":payload});
        let deadline = self.deadline;
        let result = timeout(deadline, async {
            let input = self.input.as_mut().ok_or("WORKER_CRASHED")?;
            input.write_all(format!("{message}\n").as_bytes()).await?;
            input.flush().await?;
            loop {
                let mut line = Vec::new();
                // Read chunks with a hard bound instead of allocating unbounded read_line.
                loop {
                    let available = self.output.fill_buf().await?;
                    if available.is_empty() {
                        return Err("WORKER_CRASHED".into());
                    }
                    let end = available.iter().position(|b| *b == b'\n').map(|i| i + 1);
                    let n = end.unwrap_or(available.len());
                    if line.len() + n > 8 * 1024 * 1024 {
                        return Err("IPC_ERROR".into());
                    }
                    line.extend_from_slice(&available[..n]);
                    self.output.consume(n);
                    if end.is_some() {
                        break;
                    }
                }
                let response: Value = serde_json::from_slice(&line)?;
                if response["version"] != 1 {
                    return Err("IPC_ERROR".into());
                }
                if response["type"] == "EVENT" {
                    if self.events.len() == 1000 {
                        self.events.remove(0);
                    }
                    self.events.push(response);
                    continue;
                }
                if response["id"] != id {
                    return Err("IPC_ERROR".into());
                }
                if response["type"] == "ERROR" {
                    serde_json::from_value::<crate::error_code::ErrorCode>(
                        response["code"].clone(),
                    )
                    .map_err(|_| "IPC_ERROR")?;
                    return Err(Box::new(WorkerError {
                        code: response["code"].as_str().unwrap_or("IPC_ERROR").into(),
                        retryable: response["retryable"].as_bool().unwrap_or(false),
                    })
                        as Box<dyn std::error::Error + Send + Sync>);
                }
                if response["type"] != "RESULT" || response["ok"] != true {
                    return Err("IPC_ERROR".into());
                }
                return Ok(response["payload"].clone());
            }
        })
        .await;
        match result {
            Ok(Ok(payload)) => Ok(payload),
            Ok(Err(error)) => {
                if error.downcast_ref::<WorkerError>().is_none() {
                    let _ = self.child.kill().await;
                }
                Err(error)
            }
            Err(_) => {
                let _ = self.child.kill().await;
                Err("TIMEOUT".into())
            }
        }
    }
    pub async fn shutdown(&mut self) {
        // Drop the pipe handle: shutdown() alone does not guarantee EOF on pipes.
        drop(self.input.take());
        if timeout(Duration::from_secs(5), self.child.wait())
            .await
            .is_err()
        {
            let _ = self.child.kill().await;
        }
    }
    pub async fn restart(&mut self) -> CoreResult<()> {
        self.shutdown().await;
        *self = Self::spawn_launch(self.launch.clone(), self.fixture).await?;
        Ok(())
    }
}
