use alma_core::{contracts::*, reconciliation::reconcile, state::ProcessState, store::Store};
use serde_json::json;

fn input(value: &str) -> (RpvSnapshot, ExtractedFact) {
    let snapshot = serde_json::from_value(json!({"process_id":"synthetic","requisition_id":"rpv1","captured_at":"2026-01-01T00:00:00Z",
        "requisition":{"fields":{"irpf":{"raw":value,"normalized":value,"presence":"present"}}}})).unwrap();
    let fact = serde_json::from_value(json!({"field":"irpf","subject_id":null,"value_raw":"R$ 370,00","value_normalized":"370.00",
        "confidence":"EXACT_TEXT","scope_verified":true,"source":{"process_id":"synthetic","requisition_id":"rpv1","document_id":"doc1",
        "document_name":"MEMORIA_CALCULO","event":"83","page":3,"raw_text":"IRPF: R$ 370,00","bbox":null,
        "normalized_value":"370.00","sha256":"a".repeat(64),"extracted_at":"2026-01-01T00:00:00Z"}})).unwrap();
    (snapshot, fact)
}
#[test]
fn exact_divergent_absent_conflicting_and_unverifiable() {
    let (mut s, f) = input("370.00");
    assert_eq!(
        reconcile(&s, &[f.clone()]).fields[0].status,
        ValidationStatus::Validated
    );
    s.requisition.fields.get_mut("irpf").unwrap().normalized = Some(json!("330.00"));
    let r = reconcile(&s, &[f.clone()]);
    assert_eq!(r.fields[0].status, ValidationStatus::Divergent);
    assert_eq!(r.fields[0].evidence[0].page, Some(3));
    assert_eq!(
        reconcile(&s, &[]).fields[0].status,
        ValidationStatus::NotVerifiable
    );
    let mut other = f.clone();
    other.value_normalized = "371.00".into();
    other.source.normalized_value = "371.00".into();
    assert_eq!(
        reconcile(&s, &[f.clone(), other]).fields[0].status,
        ValidationStatus::ConflictingSources
    );
    s.requisition.fields.get_mut("irpf").unwrap().presence = Presence::Missing;
    assert_eq!(
        reconcile(&s, &[f.clone()]).fields[0].status,
        ValidationStatus::Absent
    );
    let mut low = f.clone();
    low.confidence = Confidence::OcrLow;
    assert_eq!(
        reconcile(&s, &[low]).fields[0].status,
        ValidationStatus::NotVerifiable
    );
    let mut wrong = f;
    wrong.subject_id = Some("another-beneficiary".into());
    assert_eq!(
        reconcile(&s, &[wrong]).fields[0].status,
        ValidationStatus::NotVerifiable
    );
}
#[test]
fn decimal_is_exact_and_never_float() {
    let (s, mut f) = input("9007199254740993.01");
    f.value_normalized = "9007199254740993.02".into();
    f.source.normalized_value = f.value_normalized.clone();
    assert_eq!(
        reconcile(&s, &[f]).fields[0].status,
        ValidationStatus::Divergent
    );
}

#[test]
fn unverified_scope_never_validates_and_resume_binds_identity() {
    let (mut s, mut f) = input("370.00");
    f.scope_verified = false;
    assert_eq!(
        reconcile(&s, &[f]).fields[0].status,
        ValidationStatus::NotVerifiable
    );
    let temp = tempfile::tempdir().unwrap();
    let mut store = Store::open(&temp.path().join("audit.sqlite")).unwrap();
    let job = store.create_job().unwrap();
    store.bind_target(&job, &s).unwrap();
    s.requisition_id = "other".into();
    assert!(store.bind_target(&job, &s).is_err());
}

#[test]
fn report_and_completed_state_commit_together() {
    use ProcessState::*;
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("audit.sqlite");
    let job;
    {
        let mut store = Store::open(&path).unwrap();
        job = store.create_job().unwrap();
        for state in [
            SessionCheck,
            OpeningProcess,
            ReadingRequisition,
            IndexingDocuments,
            Reconciling,
        ] {
            store.transition(&job, state).unwrap();
        }
        let (s, f) = input("330.00");
        let facts = vec![f];
        store
            .persist_report(&job, &s, &facts, &reconcile(&s, &facts))
            .unwrap();
        assert_eq!(store.state(&job).unwrap(), Validated);
    }
    let store = Store::open(&path).unwrap();
    assert_eq!(store.state(&job).unwrap(), Validated);
    assert_eq!(store.reports().unwrap().len(), 1);
}
#[test]
fn restart_pauses_and_report_inserts_are_idempotent() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("audit.sqlite");
    let job;
    {
        let mut store = Store::open(&path).unwrap();
        job = store.create_job().unwrap();
        store.transition(&job, ProcessState::SessionCheck).unwrap();
        let (s, f) = input("330.00");
        let facts = vec![f];
        let report = reconcile(&s, &facts);
        assert_eq!(
            store.persist_report(&job, &s, &facts, &report).unwrap(),
            store.persist_report(&job, &s, &facts, &report).unwrap()
        );
        assert_eq!(store.reports().unwrap().len(), 1);
    }
    let mut store = Store::open(&path).unwrap();
    assert_eq!(store.state(&job).unwrap(), ProcessState::Paused);
    store.transition(&job, ProcessState::SessionCheck).unwrap();
    assert_eq!(store.events().unwrap().len(), 3);
    assert_eq!(
        store.reports().unwrap()[0].fields[0].evidence[0].page,
        Some(3)
    );
}
