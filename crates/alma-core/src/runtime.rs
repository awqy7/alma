//! Explicit launch configuration: installed builds never fall back to a checkout.
use crate::store::CoreResult;
use std::path::{Path, PathBuf};
use tokio::process::Command;

#[derive(Clone, Debug)]
pub enum WorkerLaunch {
    Development {
        root: PathBuf,
        python: PathBuf,
    },
    Bundled {
        executable: PathBuf,
        browsers: PathBuf,
    },
}
impl WorkerLaunch {
    pub fn development(root: &Path) -> Self {
        Self::Development {
            root: root.into(),
            python: root.join(if cfg!(windows) {
                ".venv/Scripts/python.exe"
            } else {
                ".venv/bin/python"
            }),
        }
    }
    pub fn bundled(resources: &Path) -> CoreResult<Self> {
        let runtime = resources.join("runtime");
        let executable = runtime.join("worker").join(if cfg!(windows) {
            "alma-worker.exe"
        } else {
            "alma-worker"
        });
        let browsers = runtime.join("browsers");
        if !executable.is_file() || !browsers.is_dir() {
            return Err("WORKER_CRASHED".into());
        }
        Ok(Self::Bundled {
            executable,
            browsers,
        })
    }
    pub(crate) fn command(&self, scratch: &Path) -> Command {
        let mut command = match self {
            Self::Development { root, python } => {
                let mut cmd = Command::new(python);
                cmd.args(["-u", "-m", "engine.worker"]).current_dir(root);
                cmd
            }
            Self::Bundled {
                executable,
                browsers,
            } => {
                let mut cmd = Command::new(executable);
                cmd.current_dir(scratch)
                    .env("PLAYWRIGHT_BROWSERS_PATH", browsers);
                cmd.env_remove("PYTHONHOME").env_remove("PYTHONPATH");
                cmd
            }
        };
        command
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1");
        #[cfg(windows)]
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW; keep stdin/stdout pipes.
        command
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn installed_runtime_requires_its_own_resources() {
        let temp = tempfile::tempdir().unwrap();
        assert!(WorkerLaunch::bundled(temp.path()).is_err());
        let worker = temp.path().join("runtime/worker");
        std::fs::create_dir_all(&worker).unwrap();
        std::fs::create_dir_all(temp.path().join("runtime/browsers")).unwrap();
        std::fs::write(
            worker.join(if cfg!(windows) {
                "alma-worker.exe"
            } else {
                "alma-worker"
            }),
            [],
        )
        .unwrap();
        let launch = WorkerLaunch::bundled(temp.path()).unwrap();
        let command = launch.command(temp.path());
        assert_eq!(command.as_std().get_args().count(), 0); // No `python -m` in installed build.
        assert_eq!(command.as_std().get_current_dir(), Some(temp.path()));
    }
}

/// Installation probe: real bundled process, documents, reconciliation and SQLite.
/// No login or official process is accessed.
pub async fn verify_bundle(resources: &Path) -> CoreResult<serde_json::Value> {
    let launch = WorkerLaunch::bundled(resources)?;
    let mut worker = crate::worker::Worker::spawn_launch(launch.clone(), false).await?;
    worker.restart().await?;
    let ping = worker.call("PING", serde_json::json!({})).await;
    worker.shutdown().await;
    if ping?["protocol_version"] != 1 {
        return Err("IPC_ERROR".into());
    }
    let request = serde_json::from_value(
        serde_json::json!({"sample":"recording", "official_total":"2.790,00", "official_base_date":"09/2026", "expected_process":"0000000-00.2026.0.00.0001"}),
    )?;
    let report = crate::inspection::inspect_with_runtime(launch.clone(), request).await?;
    if report["checks"][0]["status"] != "VALIDATED" || report["checks"][1]["status"] != "VALIDATED"
    {
        return Err("NOT_VERIFIABLE".into());
    }
    let data = tempfile::tempdir()?;
    let store = crate::store::Store::open(&data.path().join("installation.sqlite"))?;
    if !store.reports()?.is_empty() {
        return Err("DATABASE_ERROR".into());
    }
    let demo =
        crate::demo::run(launch, &data.path().join("demo.sqlite"), Default::default()).await?;
    if demo["execution"]["stored"]["saves"] != 3 {
        return Err("NOT_VERIFIABLE".into());
    }
    Ok(
        serde_json::json!({"ok":true,"version":"0.1.0","checks":["packaged_worker","restart","jsonl","html","pdf","reconciliation","sqlite","demo_dom_saves","chromium"],"official_changes":0}),
    )
}
