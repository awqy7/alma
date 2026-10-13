use crate::{contracts::*, state::ProcessState};
use rusqlite::{params, Connection, OptionalExtension};
use sha2::{Digest, Sha256};
use std::path::Path;

pub type CoreResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
pub struct Store {
    pub(crate) connection: Connection,
}
impl Store {
    pub fn open(path: &Path) -> CoreResult<Self> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
            std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .mode(0o600)
                .open(path)?;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        }
        let connection = Connection::open(path)?;
        connection.pragma_update(None, "journal_mode", "WAL")?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        connection.busy_timeout(std::time::Duration::from_secs(5))?;
        connection.execute_batch("CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
            rule_version TEXT NOT NULL, app_version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS processes (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), state TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS job_targets (
            job_id TEXT PRIMARY KEY REFERENCES processes(id), identity_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES processes(id), payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots (
            report_id TEXT PRIMARY KEY REFERENCES reports(id), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facts (
            report_id TEXT NOT NULL REFERENCES reports(id), ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(report_id, ordinal));
            CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES processes(id),
            action TEXT NOT NULL, timestamp TEXT NOT NULL, previous_hash TEXT NOT NULL, current_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY, job_id TEXT, plan TEXT NOT NULL, result TEXT NOT NULL, executed_at TEXT NOT NULL);")?;
        let mut store = Self { connection };
        store.recover()?;
        store.init_queue()?;
        Ok(store)
    }
    fn recover(&mut self) -> CoreResult<()> {
        let jobs: Vec<(String, String)> = self
            .connection
            .prepare("SELECT id,state FROM processes")?
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
            .collect::<Result<_, _>>()?;
        for (id, state) in jobs {
            let state: ProcessState = serde_json::from_str(&state)?;
            if !matches!(
                state,
                ProcessState::Validated
                    | ProcessState::Failed
                    | ProcessState::Exception
                    | ProcessState::Paused
                    | ProcessState::Queued
            ) {
                self.transition(&id, ProcessState::Paused)?;
            }
        }
        Ok(())
    }
    pub fn create_job(&mut self) -> CoreResult<String> {
        let id = uuid::Uuid::new_v4().to_string();
        let now = chrono::Utc::now().to_rfc3339();
        let tx = self.connection.transaction()?;
        tx.execute(
            "INSERT INTO runs VALUES (?1,?2,NULL,'QUEUED','1','0.1.0')",
            params![id, now],
        )?;
        tx.execute(
            "INSERT INTO processes VALUES (?1,?1,?2,?3)",
            params![id, serde_json::to_string(&ProcessState::Queued)?, now],
        )?;
        tx.commit()?;
        Ok(id)
    }
    pub fn state(&self, job: &str) -> CoreResult<ProcessState> {
        let state: String =
            self.connection
                .query_row("SELECT state FROM processes WHERE id=?1", [job], |r| {
                    r.get(0)
                })?;
        Ok(serde_json::from_str(&state)?)
    }
    pub fn bind_target(&mut self, job: &str, snapshot: &RpvSnapshot) -> CoreResult<()> {
        let identity = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&(
                &snapshot.process_id,
                &snapshot.requisition_id
            ))?)
        );
        self.connection.execute(
            "INSERT OR IGNORE INTO job_targets VALUES (?1,?2)",
            params![job, identity],
        )?;
        let stored: String = self.connection.query_row(
            "SELECT identity_hash FROM job_targets WHERE job_id=?1",
            [job],
            |r| r.get(0),
        )?;
        if stored != identity {
            return Err("PROCESS_NOT_FOUND".into());
        }
        Ok(())
    }
    pub fn transition(&mut self, job: &str, next: ProcessState) -> CoreResult<()> {
        let previous = self.state(job)?;
        if !previous.allows(next) {
            return Err("INVALID_STATE_TRANSITION".into());
        }
        let tx = self.connection.transaction()?;
        Self::write_transition(&tx, job, next)?;
        tx.commit()?;
        Ok(())
    }
    fn write_transition(
        tx: &rusqlite::Transaction<'_>,
        job: &str,
        next: ProcessState,
    ) -> CoreResult<()> {
        let now = chrono::Utc::now().to_rfc3339();
        let action = serde_json::to_string(&next)?;
        let prev_hash: String = tx
            .query_row(
                "SELECT current_hash FROM events ORDER BY seq DESC LIMIT 1",
                [],
                |r| r.get(0),
            )
            .optional()?
            .unwrap_or_default();
        let hash = format!(
            "{:x}",
            Sha256::digest(format!("{prev_hash}|{job}|{action}|{now}"))
        );
        tx.execute(
            "UPDATE processes SET state=?1,updated_at=?2 WHERE id=?3",
            params![action, now, job],
        )?;
        tx.execute(
            "UPDATE runs SET status=?1,finished_at=?2 WHERE id=?3",
            params![
                action,
                if matches!(
                    next,
                    ProcessState::Validated | ProcessState::Failed | ProcessState::Exception
                ) {
                    Some(&now)
                } else {
                    None
                },
                job
            ],
        )?;
        tx.execute("INSERT INTO events(job_id,action,timestamp,previous_hash,current_hash) VALUES (?1,?2,?3,?4,?5)",params![job,action,now,prev_hash,hash])?;
        Ok(())
    }
    pub fn persist_report(
        &mut self,
        job: &str,
        snapshot: &RpvSnapshot,
        facts: &[ExtractedFact],
        report: &ValidationReport,
    ) -> CoreResult<String> {
        let input =
            serde_json::to_string(&(snapshot, facts, include_str!("../../../rules/rules.json")))?;
        let id = format!("{:x}", Sha256::digest(format!("{job}|{input}")));
        let tx = self.connection.transaction()?;
        tx.execute(
            "INSERT OR IGNORE INTO reports VALUES (?1,?2,?3,?4)",
            params![id, job, serde_json::to_string(report)?, report.created_at],
        )?;
        tx.execute(
            "INSERT OR IGNORE INTO snapshots VALUES (?1,?2)",
            params![id, serde_json::to_string(snapshot)?],
        )?;
        for (i, fact) in facts.iter().enumerate() {
            tx.execute(
                "INSERT OR IGNORE INTO facts VALUES (?1,?2,?3)",
                params![id, i as i64, serde_json::to_string(fact)?],
            )?;
        }
        // Report, facts, final state and audit event commit together.
        if ProcessState::Reconciling
            == serde_json::from_str::<ProcessState>(&tx.query_row(
                "SELECT state FROM processes WHERE id=?1",
                [job],
                |r| r.get::<_, String>(0),
            )?)?
        {
            Self::write_transition(&tx, job, ProcessState::Validated)?;
        }
        tx.commit()?;
        Ok(id)
    }
    pub fn reports(&self) -> CoreResult<Vec<ValidationReport>> {
        let payloads: Vec<String> = self
            .connection
            .prepare("SELECT payload FROM reports ORDER BY created_at DESC")?
            .query_map([], |r| r.get(0))?
            .collect::<Result<_, _>>()?;
        payloads
            .into_iter()
            .map(|p| Ok(serde_json::from_str(&p)?))
            .collect()
    }
    pub fn jobs(&self) -> CoreResult<Vec<serde_json::Value>> {
        Ok(self.connection.prepare("SELECT id,state,updated_at FROM processes ORDER BY updated_at DESC")?
            .query_map([], |r| Ok(serde_json::json!({"id":r.get::<_,String>(0)?,
                "state":serde_json::from_str::<serde_json::Value>(&r.get::<_,String>(1)?).unwrap_or_default(),
                "updated_at":r.get::<_,String>(2)?})))?.collect::<Result<_,_>>()?)
    }
    pub fn events(&self) -> CoreResult<Vec<serde_json::Value>> {
        Ok(self.connection.prepare("SELECT job_id,action,timestamp,current_hash FROM events ORDER BY seq DESC LIMIT 500")?
            .query_map([], |r| Ok(serde_json::json!({"job_id":r.get::<_,String>(0)?,
                "action":r.get::<_,String>(1)?,"timestamp":r.get::<_,String>(2)?,"hash":r.get::<_,String>(3)?})))?
            .collect::<Result<_,_>>()?)
    }
    pub fn record_execution(
        &mut self,
        job_id: Option<&str>,
        plan: &serde_json::Value,
        result: &serde_json::Value,
    ) -> CoreResult<String> {
        let id = uuid::Uuid::new_v4().to_string();
        let now = chrono::Utc::now().to_rfc3339();
        self.connection.execute(
            "INSERT INTO executions VALUES (?1,?2,?3,?4,?5)",
            params![
                id,
                job_id,
                serde_json::to_string(plan)?,
                serde_json::to_string(result)?,
                now
            ],
        )?;
        Ok(id)
    }
    pub fn executions(&self) -> CoreResult<Vec<serde_json::Value>> {
        Ok(self.connection.prepare("SELECT id,job_id,plan,result,executed_at FROM executions ORDER BY executed_at DESC LIMIT 50")?
            .query_map([], |r| Ok(serde_json::json!({
                "id": r.get::<_,String>(0)?,
                "job_id": r.get::<_,Option<String>>(1)?,
                "plan": serde_json::from_str::<serde_json::Value>(&r.get::<_,String>(2)?).unwrap_or_default(),
                "result": serde_json::from_str::<serde_json::Value>(&r.get::<_,String>(3)?).unwrap_or_default(),
                "executed_at": r.get::<_,String>(4)?
            })))?.collect::<Result<_,_>>()?)
    }
}
