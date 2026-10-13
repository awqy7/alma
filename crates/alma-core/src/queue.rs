//! Durable read-only scheduler. One process or RPV per tick, one worker owned by Rust.
use crate::{
    runner::Runner,
    state::ProcessState,
    store::{CoreResult, Store},
};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use std::sync::atomic::Ordering;

impl Store {
    pub(crate) fn init_queue(&mut self) -> CoreResult<()> {
        self.connection.execute_batch("CREATE TABLE IF NOT EXISTS review_queues(
            id TEXT PRIMARY KEY, localizer TEXT NOT NULL, scope_id TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, error_code TEXT);
            CREATE TABLE IF NOT EXISTS review_queue_items(
            queue_id TEXT NOT NULL REFERENCES review_queues(id), process_number TEXT NOT NULL,
            requisition_id TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
            job_id TEXT, error_code TEXT, ordinal INTEGER NOT NULL,
            PRIMARY KEY(queue_id,process_number,requisition_id));
            UPDATE review_queues SET status='PAUSED',error_code='APP_RESTARTED' WHERE status IN ('RUNNING','DISCOVERING');
            UPDATE review_queue_items SET state='PENDING' WHERE state='RUNNING';")?;
        Ok(())
    }
    pub fn queue_status(&self) -> CoreResult<Value> {
        let queue: Option<(String,String,String,Option<String>)> = self.connection.query_row(
            "SELECT id,localizer,status,error_code FROM review_queues ORDER BY created_at DESC LIMIT 1", [],
            |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?;
        let Some((id, localizer, status, error)) = queue else {
            return Ok(Value::Null);
        };
        let items = self.connection.prepare("SELECT process_number,requisition_id,kind,state,job_id,error_code FROM review_queue_items WHERE queue_id=?1 ORDER BY ordinal,requisition_id")?
            .query_map([&id], |r| Ok(json!({"process_number":r.get::<_,String>(0)?,"requisition_id":r.get::<_,String>(1)?,
                "kind":r.get::<_,String>(2)?,"state":r.get::<_,String>(3)?,"job_id":r.get::<_,Option<String>>(4)?,"error_code":r.get::<_,Option<String>>(5)?})))?
            .collect::<Result<Vec<_>,_>>()?;
        Ok(json!({"id":id,"localizer":localizer,"status":status,"error_code":error,"items":items}))
    }
    pub fn pause_queue(&mut self) -> CoreResult<()> {
        self.connection.execute(
            "UPDATE review_queues SET status='PAUSED',error_code=NULL WHERE status='RUNNING'",
            [],
        )?;
        Ok(())
    }
}

fn safe_code(error: &dyn std::error::Error) -> String {
    let value = error.to_string();
    if value.len() < 64 && value.chars().all(|c| c.is_ascii_uppercase() || c == '_') {
        value
    } else {
        "EXCEPTION".into()
    }
}

impl Runner {
    pub async fn start_queue(
        &mut self,
        localizer: &str,
        mut emit: impl FnMut(Value),
    ) -> CoreResult<Value> {
        if localizer.trim().is_empty() || localizer.len() > 200 {
            return Err("IPC_ERROR".into());
        }
        let session = self.worker.call("CHECK_SESSION", json!({})).await?;
        if session["state"] != "AUTHENTICATED" {
            return Err("REAUTH_REQUIRED".into());
        }
        let scope = session["scope_id"].as_str().ok_or("DISCOVERY_REQUIRED")?;
        let previous: Option<String>=self.store.connection.query_row(
            "SELECT id FROM review_queues WHERE localizer=?1 AND scope_id=?2 AND status!='COMPLETED' AND id=(SELECT id FROM review_queues ORDER BY created_at DESC LIMIT 1)",
            params![localizer,scope], |r|r.get(0)).optional()?;
        let id = previous.unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        self.store.connection.execute(
            "INSERT OR IGNORE INTO review_queues VALUES(?1,?2,?3,'DISCOVERING',?4,NULL)",
            params![id, localizer, scope, chrono::Utc::now().to_rfc3339()],
        )?;
        self.store.connection.execute(
            "UPDATE review_queues SET status='DISCOVERING',error_code=NULL WHERE id=?1",
            [&id],
        )?;
        emit(json!({"action":"QUEUE_DISCOVERY","queue_id":id}));
        let result = self
            .worker
            .call("DISCOVER_PROCESSES", json!({"localizer":localizer}))
            .await;
        let processes = match result {
            Ok(value) => value,
            Err(error) => {
                self.store.connection.execute(
                    "UPDATE review_queues SET status='PAUSED',error_code=?2 WHERE id=?1",
                    params![id, safe_code(error.as_ref())],
                )?;
                return Err(error);
            }
        };
        let processes = processes.as_array().ok_or("IPC_ERROR")?;
        let tx = self.store.connection.transaction()?;
        for (index, process) in processes.iter().enumerate() {
            let number = process["process_number"].as_str().ok_or("IPC_ERROR")?;
            if number.len() != 20 || !number.bytes().all(|c| c.is_ascii_digit()) {
                return Err("IPC_ERROR".into());
            }
            tx.execute("INSERT OR IGNORE INTO review_queue_items VALUES(?1,?2,'','PROCESS','PENDING',NULL,NULL,?3)",params![id,number,index as i64])?;
        }
        tx.execute(
            "UPDATE review_queues SET status='RUNNING' WHERE id=?1",
            [&id],
        )?;
        tx.commit()?;
        self.pause.store(false, Ordering::SeqCst);
        let state = self.store.queue_status()?;
        emit(json!({"action":"QUEUE_READY","queue":state}));
        Ok(state)
    }

    pub async fn queue_step(&mut self, mut emit: impl FnMut(Value)) -> CoreResult<Value> {
        let queue = self.store.queue_status()?;
        if queue["status"] != "RUNNING" {
            return Ok(queue);
        }
        let id = queue["id"].as_str().ok_or("IPC_ERROR")?.to_owned();
        if self.pause.load(Ordering::SeqCst) {
            self.store.pause_queue()?;
            return self.store.queue_status();
        }
        let item: Option<(String,String,String,Option<String>,i64)>=self.store.connection.query_row(
            "SELECT process_number,requisition_id,kind,job_id,ordinal FROM review_queue_items WHERE queue_id=?1 AND state='PENDING' ORDER BY ordinal,requisition_id LIMIT 1",[&id],
            |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?))).optional()?;
        let Some((process, req, kind, job, ordinal)) = item else {
            self.store.connection.execute(
                "UPDATE review_queues SET status='COMPLETED' WHERE id=?1",
                [&id],
            )?;
            return self.store.queue_status();
        };
        let result: CoreResult<()>=async {
            let session=self.worker.call("CHECK_SESSION",json!({})).await?;
            if session["state"]!="AUTHENTICATED" {return Err("REAUTH_REQUIRED".into());}
            let scope: String=self.store.connection.query_row("SELECT scope_id FROM review_queues WHERE id=?1",[&id],|r|r.get(0))?;
            if session["scope_id"]!=scope {return Err("SESSION_SCOPE_CHANGED".into());}
            self.store.connection.execute("UPDATE review_queue_items SET state='RUNNING',error_code=NULL WHERE queue_id=?1 AND process_number=?2 AND requisition_id=?3",params![id,process,req])?;
            emit(json!({"action":"QUEUE_ITEM","process_number":process,"requisition_id":req}));
            if let Some(ref job)=job {
                if self.store.state(job)?==ProcessState::Validated {return Ok(());}
            }
            self.worker.call("OPEN_PROCESS",json!({"process_number":process})).await?;
            let requisitions=self.worker.call("LIST_REQUISITIONS",json!({})).await?;
            if kind=="PROCESS" {
                let tx=self.store.connection.transaction()?;
                for req in requisitions.as_array().ok_or("IPC_ERROR")? {
                    let key=req["requisition_id"].as_str().ok_or("IPC_ERROR")?;
                    if key.is_empty() {return Err("IPC_ERROR".into());}
                    tx.execute("INSERT OR IGNORE INTO review_queue_items VALUES(?1,?2,?3,'RPV','PENDING',NULL,NULL,?4)",params![id,process,key,ordinal])?;
                }
                tx.commit()?;
            } else {
                self.worker.call("OPEN_REQUISITION",json!({"requisition_id":req})).await?;
                let job=match job {Some(job)=>job,None=>self.store.create_job()?};
                self.store.connection.execute("UPDATE review_queue_items SET job_id=?4 WHERE queue_id=?1 AND process_number=?2 AND requisition_id=?3",params![id,process,req,job])?;
                self.review_current(Some(&job),&mut emit).await?;
            }
            Ok(())
        }.await;
        match result {
            Ok(()) => {
                self.store.connection.execute("UPDATE review_queue_items SET state='COMPLETED' WHERE queue_id=?1 AND process_number=?2 AND requisition_id=?3",params![id,process,req])?;
            }
            Err(error) => {
                let code = safe_code(error.as_ref());
                let pause = matches!(
                    code.as_str(),
                    "REAUTH_REQUIRED"
                        | "SESSION_EXPIRED"
                        | "SESSION_SCOPE_CHANGED"
                        | "UI_CHANGED"
                        | "TIMEOUT"
                        | "WORKER_CRASHED"
                        | "IPC_ERROR"
                        | "RATE_LIMITED"
                        | "HTTP_ERROR"
                        | "PAUSED"
                );
                self.store.connection.execute("UPDATE review_queue_items SET state=?4,error_code=?5 WHERE queue_id=?1 AND process_number=?2 AND requisition_id=?3",params![id,process,req,if pause {"PENDING"} else {"EXCEPTION"},code])?;
                if pause {
                    self.store.connection.execute(
                        "UPDATE review_queues SET status='PAUSED',error_code=?2 WHERE id=?1",
                        params![id, code],
                    )?;
                }
                emit(json!({"action":"QUEUE_EXCEPTION","error_code":code}));
            }
        }
        if self.pause.load(Ordering::SeqCst) {
            self.store.pause_queue()?;
        }
        self.store.queue_status()
    }
}
