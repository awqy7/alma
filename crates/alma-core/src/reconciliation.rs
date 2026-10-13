use crate::contracts::*;
use rust_decimal::Decimal;
use serde::Deserialize;
use std::{collections::BTreeSet, str::FromStr};

#[derive(Debug, Deserialize)]
pub struct Rule {
    pub id: String,
    pub version: String,
    pub field: String,
    pub comparison: String,
    pub tolerance: Option<String>,
}
pub fn rules() -> Vec<Rule> {
    serde_json::from_str(include_str!("../../../rules/rules.json"))
        .expect("embedded rules must be valid")
}
fn canonical(value: &str, rule: &Rule) -> Option<String> {
    match rule.comparison.as_str() {
        "decimal_equal" => {
            if rule.tolerance.as_deref() != Some("0.00") {
                return None;
            }
            if !value
                .chars()
                .all(|c| c.is_ascii_digit() || c == '.' || c == '-')
            {
                return None;
            }
            let d = Decimal::from_str(value).ok()?;
            if d.scale() > 2 {
                return None;
            }
            Some(d.normalize().to_string())
        }
        "date_equal" => {
            if value.len() != 10 {
                return None;
            }
            chrono::NaiveDate::parse_from_str(value, "%Y-%m-%d")
                .ok()
                .map(|d| d.to_string())
        }
        _ => None,
    }
}
pub fn reconcile(snapshot: &RpvSnapshot, facts: &[ExtractedFact]) -> ValidationReport {
    let rules = rules();
    let mut fields = Vec::new();
    let mut entities = vec![(None, &snapshot.requisition.fields)];
    for party in snapshot.beneficiaries.iter().chain(snapshot.fees.iter()) {
        entities.push((Some(party.id.as_str()), &party.fields));
    }
    for (subject, values) in entities {
        for (field, value) in values {
            let rule = rules.iter().find(|r| &r.field == field);
            let sources: Vec<_> = facts
                .iter()
                .filter(|f| {
                    &f.field == field
                        && f.subject_id.as_deref() == subject
                        && f.source.process_id == snapshot.process_id
                        && f.source.requisition_id == snapshot.requisition_id
                })
                .collect();
            let usable = sources.iter().all(|f| {
                f.scope_verified
                    && !matches!(f.confidence, Confidence::OcrLow)
                    && (f.source.page.is_some_and(|p| p > 0)
                        || f.source
                            .html_location
                            .as_ref()
                            .is_some_and(|p| p.starts_with('/')))
                    && !f.source.raw_text.is_empty()
                    && f.source.sha256.len() == 64
                    && f.source.sha256.bytes().all(|b| b.is_ascii_hexdigit())
                    && f.source.normalized_value == f.value_normalized
            });
            let doc_values: Option<BTreeSet<String>> = rule.and_then(|r| {
                sources
                    .iter()
                    .map(|f| canonical(&f.value_normalized, r))
                    .collect()
            });
            let actual = rule.and_then(|r| {
                value
                    .normalized
                    .as_ref()?
                    .as_str()
                    .and_then(|v| canonical(v, r))
            });
            let status = if rule.is_none() || !usable || sources.is_empty() || doc_values.is_none()
            {
                ValidationStatus::NotVerifiable
            } else if doc_values.as_ref().unwrap().len() > 1 {
                ValidationStatus::ConflictingSources
            } else if value.presence == Presence::Missing {
                ValidationStatus::Absent
            } else if value.presence != Presence::Present || actual.is_none() {
                ValidationStatus::NotVerifiable
            } else if doc_values.as_ref().unwrap().contains(&actual.unwrap()) {
                ValidationStatus::Validated
            } else {
                ValidationStatus::Divergent
            };
            fields.push(FieldValidation {
                field: field.clone(),
                subject_id: subject.map(str::to_owned),
                eproc_raw: value.raw.clone(),
                eproc_normalized: value.normalized.clone(),
                document_raw: sources.iter().map(|f| f.value_raw.clone()).collect(),
                document_normalized: sources.iter().map(|f| f.value_normalized.clone()).collect(),
                status,
                rule_id: rule.map_or("NO_RULE", |r| r.id.as_str()).into(),
                rule_version: rule.map_or("1", |r| r.version.as_str()).into(),
                evidence: sources.iter().map(|f| f.source.clone()).collect(),
            });
        }
    }
    ValidationReport {
        document_review: None,
        coverage: snapshot.coverage.clone(),
        process_id: snapshot.process_id.clone(),
        requisition_id: snapshot.requisition_id.clone(),
        created_at: chrono::Utc::now().to_rfc3339(),
        fields,
    }
}
