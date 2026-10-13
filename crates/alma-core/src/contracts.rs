use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ValidationStatus {
    Validated,
    Divergent,
    Absent,
    NotVerifiable,
    ConflictingSources,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Presence {
    Present,
    Missing,
    NotApplicable,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldValue {
    pub raw: Option<String>,
    pub normalized: Option<serde_json::Value>,
    pub presence: Presence,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entity {
    pub fields: BTreeMap<String, FieldValue>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Party {
    pub id: String,
    pub fields: BTreeMap<String, FieldValue>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RpvSnapshot {
    #[serde(default)]
    pub coverage: BTreeMap<String, String>,
    pub process_id: String,
    pub requisition_id: String,
    pub captured_at: String,
    pub requisition: Entity,
    #[serde(default)]
    pub beneficiaries: Vec<Party>,
    #[serde(default)]
    pub fees: Vec<Party>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Evidence {
    pub process_id: String,
    pub requisition_id: String,
    pub document_id: String,
    pub document_name: String,
    pub event: Option<String>,
    pub page: Option<u32>,
    #[serde(default)]
    pub html_location: Option<String>,
    pub raw_text: String,
    pub bbox: Option<Vec<f64>>,
    pub normalized_value: String,
    pub sha256: String,
    pub extracted_at: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Confidence {
    ExactText,
    StructuredTable,
    RegexMatch,
    OcrHigh,
    OcrLow,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractedFact {
    #[serde(default)]
    pub scope_verified: bool,
    pub field: String,
    pub subject_id: Option<String>,
    pub value_raw: String,
    pub value_normalized: String,
    pub source: Evidence,
    pub confidence: Confidence,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldValidation {
    pub field: String,
    pub subject_id: Option<String>,
    pub eproc_raw: Option<String>,
    pub eproc_normalized: Option<serde_json::Value>,
    pub document_raw: Vec<String>,
    pub document_normalized: Vec<String>,
    pub status: ValidationStatus,
    pub rule_id: String,
    pub rule_version: String,
    pub evidence: Vec<Evidence>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationReport {
    #[serde(default)]
    pub document_review: Option<serde_json::Value>,
    pub coverage: BTreeMap<String, String>,
    pub process_id: String,
    pub requisition_id: String,
    pub created_at: String,
    pub fields: Vec<FieldValidation>,
}
