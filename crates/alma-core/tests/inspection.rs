use alma_core::inspection::{evaluate, inspect, InspectionRequest};
use serde_json::json;
use std::path::PathBuf;

#[tokio::test]
async fn real_pdfs_dry_run_decisions_and_date_role() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    for (variant, expected) in [
        ("standard", "DIVERGENT"),
        ("table", "DIVERGENT"),
        ("conflict", "NOT_VERIFIABLE"),
        ("no_base_date", "DIVERGENT"),
        ("recording", "DIVERGENT"),
        ("wrong_process", "NOT_VERIFIABLE"),
        ("multiple_experts", "NOT_VERIFIABLE"),
    ] {
        let request: InspectionRequest = serde_json::from_value(
            json!({"sample":variant,"official_total":"2.400,00","official_base_date":"10/2026", "expected_process":if ["recording","wrong_process","multiple_experts"].contains(&variant) {Some("0000000-00.2026.0.00.0001")} else {None}}),
        )
        .unwrap();
        let report = inspect(&root, request).await.unwrap();
        assert_eq!(report["checks"][0]["status"], expected);
        assert_eq!(report["official_changes"], 0);
        assert_eq!(report["supervised_plan"]["ready"], false);
        if variant == "recording" {
            assert_eq!(report["observations"][3]["value"], "2026-09-12");
            assert_eq!(report["documents"][0]["format"], "HTML");
            assert!(report["document_checks"]
                .as_array()
                .unwrap()
                .iter()
                .all(|c| c["status"] == "VALIDATED"));
        }
        if variant == "multiple_experts" {
            assert!(report["supervised_plan"]["blockers"]
                .as_array()
                .unwrap()
                .iter()
                .any(|b| b["code"] == "MULTIPLE_DOCUMENTS"));
            assert!(report["checks"][0]["expected"].is_null());
        }
        if variant == "wrong_process" {
            assert!(report["supervised_plan"]["blockers"]
                .as_array()
                .unwrap()
                .iter()
                .any(|b| b["code"] == "DOCUMENT_SCOPE_INVALID"));
        }
        assert_eq!(report["steps"][3]["state"], "BLOCKED");
        if variant == "wrong_process" {
            assert_eq!(report["checks"][1]["status"], "NOT_VERIFIABLE");
        } else {
            assert_eq!(report["checks"][1]["status"], "DIVERGENT");
        }
        if ["standard", "table", "no_base_date", "recording"].contains(&variant) {
            assert_eq!(report["checks"][0]["expected"], "2790.00");
        }
    }
}

#[test]
fn unreadable_and_low_confidence_prevent_selection() {
    let report = evaluate(
        &json!({"documents":[{"unreadable_pages":[2]}],"candidates":[{"field":"arrears_amount","normalized":"2400.00","confidence":"NATIVE_TEXT","ambiguous_context":false}]}),
    );
    assert_eq!(report["observations"][0]["status"], "NOT_VERIFIABLE");
    let report = evaluate(
        &json!({"documents":[],"candidates":[{"field":"arrears_amount","normalized":"2400.00","confidence":"OCR_LOW","ambiguous_context":false}]}),
    );
    assert_eq!(report["observations"][0]["status"], "NOT_VERIFIABLE");
}

#[test]
fn confirmed_month_rule_preserves_provenance_and_refuses_date_conflict() {
    let mut input = json!({"documents":[{"unreadable_pages":[]}],"official_base_date":"2026-09","candidates":[
        {"field":"proposal_date","normalized":"2026-09-12","confidence":"NATIVE_TEXT","ambiguous_context":false,"text":"Cidade, 12 de setembro de 2026.","sha256":"synthetic"}
    ]});
    let report = evaluate(&input);
    assert_eq!(report["checks"][1]["status"], "VALIDATED");
    assert_eq!(report["checks"][1]["expected"], "2026-09");
    assert_eq!(report["checks"][1]["derived_from"], "2026-09-12");
    assert_eq!(report["checks"][1]["rule_id"], "RPV_PROPOSAL_MONTH_V1");
    assert_eq!(report["checks"][1]["evidence"][0]["sha256"], "synthetic");
    input["candidates"].as_array_mut().unwrap().push(json!({"field":"base_date","normalized":"2026-10","confidence":"NATIVE_TEXT","ambiguous_context":false}));
    let report = evaluate(&input);
    assert_eq!(report["checks"][1]["status"], "CONFLICTING_SOURCES");
    assert!(report["checks"][1]["expected"].is_null());
    assert!(report["supervised_plan"]["fields"][3]["value"].is_null());
}
