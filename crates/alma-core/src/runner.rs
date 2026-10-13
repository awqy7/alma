use crate::{
    contracts::*,
    reconciliation::reconcile,
    state::ProcessState as S,
    store::{CoreResult, Store},
    worker::Worker,
};
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

pub struct Runner {
    pub store: Store,
    pub worker: Worker,
    pub pause: Arc<AtomicBool>,
}
impl Runner {
    fn step(&mut self, job: &str, next: S, emit: &mut impl FnMut(Value)) -> CoreResult<()> {
        if self.pause.load(Ordering::SeqCst) {
            self.store.transition(job, S::Paused)?;
            emit(json!({"job_id":job,"state":"PAUSED"}));
            return Err("PAUSED".into());
        }
        self.store.transition(job, next)?;
        tracing::info!(run_id=job,component="core",action=?next,status="OK");
        emit(json!({"job_id":job,"state":next}));
        Ok(())
    }
    pub async fn review_current(
        &mut self,
        resume: Option<&str>,
        mut emit: impl FnMut(Value),
    ) -> CoreResult<ValidationReport> {
        let job = if let Some(id) = resume {
            id.to_owned()
        } else {
            self.store.create_job()?
        };
        let result = self.execute(&job, &mut emit).await;
        if let Err(ref error) = result {
            if !matches!(
                self.store.state(&job)?,
                S::Paused | S::Failed | S::Exception | S::Validated
            ) {
                let state = if matches!(
                    error.to_string().as_str(),
                    "REAUTH_REQUIRED" | "SESSION_EXPIRED" | "UI_CHANGED"
                ) {
                    S::Paused
                } else {
                    S::Exception
                };
                self.store.transition(&job, state)?;
                emit(json!({"job_id":job,"state":state,"error_code":error.to_string()}));
            }
        }
        // Cleanup on both failure and success; a crashed worker is killed by supervisor.
        let _ = self.worker.call("CLOSE_PROCESS", json!({})).await;
        result
    }
    async fn execute(
        &mut self,
        job: &str,
        emit: &mut impl FnMut(Value),
    ) -> CoreResult<ValidationReport> {
        self.step(job, S::SessionCheck, emit)?;
        let session = self.worker.call("CHECK_SESSION", json!({})).await?;
        if session["state"] != "AUTHENTICATED" {
            return Err("REAUTH_REQUIRED".into());
        }
        self.step(job, S::OpeningProcess, emit)?;
        // Current-page MVP: verify the manually opened process, do not invent navigation.
        self.worker.call("READ_PROCESS", json!({})).await?;
        self.step(job, S::ReadingRequisition, emit)?;
        let snapshot: RpvSnapshot =
            serde_json::from_value(self.worker.call("READ_REQUISITION", json!({})).await?)?;
        self.store.bind_target(job, &snapshot)?;
        self.step(job, S::IndexingDocuments, emit)?;
        let docs = self.worker.call("INDEX_DOCUMENTS", json!({})).await?;
        let candidates = docs["candidates"].as_array().ok_or("IPC_ERROR")?;
        if candidates.len() > 10 {
            return Err("MULTIPLE_DOCUMENTS".into());
        }
        let mut facts: Vec<ExtractedFact> = vec![];
        let mut incomplete = false;
        let mut documents = vec![];
        let mut candidates_found = vec![];
        for doc in candidates {
            self.step(job, S::Downloading, emit)?;
            self.worker
                .call("DOWNLOAD_DOCUMENT", json!({"document_id":doc["id"]}))
                .await?;
            self.step(job, S::Parsing, emit)?;
            let parsed = self
                .worker
                .call(
                    "PARSE_DOCUMENT",
                    json!({"document_id":doc["id"],
                "process_id":snapshot.process_id,"requisition_id":snapshot.requisition_id}),
                )
                .await?;
            incomplete |= !parsed["unreadable_pages"]
                .as_array()
                .ok_or("IPC_ERROR")?
                .is_empty();
            documents.extend(
                parsed["perception"]["documents"]
                    .as_array()
                    .ok_or("IPC_ERROR")?
                    .iter()
                    .cloned(),
            );
            candidates_found.extend(
                parsed["perception"]["candidates"]
                    .as_array()
                    .ok_or("IPC_ERROR")?
                    .iter()
                    .cloned(),
            );
            self.step(job, S::Extracting, emit)?;
            facts.extend(serde_json::from_value::<Vec<ExtractedFact>>(
                parsed["facts"].clone(),
            )?);
            self.step(job, S::Normalizing, emit)?;
        }
        self.step(job, S::Reconciling, emit)?;
        let mut report = reconcile(&snapshot, &facts);
        if incomplete {
            // Unread pages may contain contrary evidence: retain sources, never validate.
            for field in &mut report.fields {
                field.status = ValidationStatus::NotVerifiable;
            }
        }
        let expected_process: String = snapshot
            .process_id
            .chars()
            .filter(|c| c.is_ascii_digit())
            .collect();
        if expected_process.len() != 20 {
            return Err("PROCESS_NOT_FOUND".into());
        }
        let mut document_review = crate::inspection::evaluate(&json!({
            "documents":documents,"candidates":candidates_found,"expected_process":expected_process,
            "official_total":snapshot.requisition.fields.get("total_value").and_then(|v| v.normalized.clone()),
            "official_base_date":null
        }));
        document_review["mode"] = json!("READ_ONLY");
        document_review["synthetic"] = json!(false);
        document_review["scope_notice"] = json!("Documentos obtidos dos links do processo na sessão autorizada. Soma documental confrontada com o total lido do cabeçalho; itens e regras de composição ainda exigem revisão.");
        document_review["checks"][0]["reason"] = json!("Soma exata dos atrasados e do pedido do perito, comparada com o cabeçalho da RPV. Igualdade aritmética não autoriza criar itens nem confirma a composição jurídica.");
        report.document_review = Some(document_review);
        // Detect user navigation or edits while documents were being read.
        let fresh: RpvSnapshot =
            serde_json::from_value(self.worker.call("READ_REQUISITION", json!({})).await?)?;
        self.store.bind_target(job, &fresh)?;
        if serde_json::to_value(&fresh.requisition)? != serde_json::to_value(&snapshot.requisition)?
        {
            return Err("SNAPSHOT_CHANGED".into());
        }
        self.store.persist_report(job, &snapshot, &facts, &report)?;
        emit(json!({"job_id":job,"state":"VALIDATED"}));
        emit(json!({"job_id":job,"name":"REPORT_READY","report":report}));
        Ok(report)
    }
    pub async fn apply_real_plan(
        &mut self,
        plan: Value,
        mut emit: impl FnMut(Value),
    ) -> CoreResult<Value> {
        let job = self.store.create_job()?;
        self.step(&job, S::SessionCheck, &mut emit)?;
        let session = self.worker.call("CHECK_SESSION", json!({})).await?;
        if session["state"] != "AUTHENTICATED" {
            return Err("REAUTH_REQUIRED".into());
        }
        self.step(&job, S::OpeningProcess, &mut emit)?;
        self.worker.call("READ_PROCESS", json!({})).await?;
        self.step(&job, S::ReadingRequisition, &mut emit)?;
        let snapshot: RpvSnapshot =
            serde_json::from_value(self.worker.call("READ_REQUISITION", json!({})).await?)?;
        self.store.bind_target(&job, &snapshot)?;
        self.step(&job, S::Reconciling, &mut emit)?;
        emit(json!({"job_id":job,"state":"APPLYING_PLAN","plan":&plan}));
        let result = self.worker.call("APPLY_REAL_PLAN", plan.clone()).await?;
        self.store.record_execution(Some(&job), &plan, &result)?;
        self.step(&job, S::Validated, &mut emit)?;
        emit(json!({"job_id":job,"name":"PLAN_APPLIED","result":&result}));
        Ok(result)
    }
}
