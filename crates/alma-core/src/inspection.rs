use crate::{runtime::WorkerLaunch, store::CoreResult, worker::Worker};
use base64::{engine::general_purpose::STANDARD, Engine};
static INSPECTION_LIMIT: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::BTreeSet, path::Path, str::FromStr};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Upload {
    pub name: String,
    pub data: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InspectionRequest {
    #[serde(default)]
    pub files: Vec<Upload>,
    pub sample: Option<String>,
    pub official_total: Option<String>,
    pub official_base_date: Option<String>,
    pub expected_process: Option<String>,
}
#[derive(Serialize)]
pub struct Observation {
    pub field: String,
    pub status: String,
    pub value: Option<String>,
    pub reason: String,
    pub evidence: Vec<Value>,
}
fn document_checks(perception: &Value) -> (Vec<Value>, bool, usize) {
    let mut checks = vec![];
    let mut scope_invalid = false;
    let mut experts = 0;
    for doc in perception["documents"].as_array().into_iter().flatten() {
        let metadata = &doc["metadata"];
        let values = |key: &str| -> BTreeSet<String> {
            metadata[key]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|v| v["normalized"].as_str().map(str::to_owned))
                .collect()
        };
        if let Some(expected) = perception["expected_process"].as_str() {
            let ids = values("process_number");
            let valid = ids.len() == 1 && ids.contains(expected);
            scope_invalid |= !valid;
            checks.push(json!({"document_id":doc["id"],"document_name":doc["name"],
                "field":"process_number","status":if valid {"VALIDATED"} else {"NOT_VERIFIABLE"},
                "reason":if valid {"Número documental corresponde ao processo informado (não valida dígitos verificadores)."} else {"Processo ausente, diferente ou ambíguo; estes documentos não podem compor a requisição."},
                "evidence":metadata["process_number"]}));
        }
        if doc["profile"] == "ambiguous" {
            scope_invalid = true;
        }
        if doc["profile"] == "expert_payment" {
            experts += 1;
            for (field, allowed) in [
                ("request_type", vec!["pagamento"]),
                (
                    "actor_type",
                    vec![
                        "perito",
                        "perita",
                        "peritos",
                        "peritas",
                        "peritas(os)",
                        "peritos(as)",
                    ],
                ),
                (
                    "defendant",
                    vec![
                        "inss",
                        "instituto nacional do seguro social",
                        "instituto nacional do seguro social - inss",
                    ],
                ),
            ] {
                let found = values(field);
                let valid = found.len() == 1
                    && found.first().is_some_and(|v| allowed.contains(&v.as_str()));
                scope_invalid |= !valid;
                checks.push(json!({"document_id":doc["id"],"document_name":doc["name"],"field":field,
                    "status":if valid {"VALIDATED"} else {"NOT_VERIFIABLE"},
                    "reason":if valid {"Campo corresponde ao padrão documental observado."} else {"Campo ausente ou fora do padrão observado; exige revisão."},"evidence":metadata[field]}));
            }
        }
    }
    (checks, scope_invalid, experts)
}
pub fn evaluate(perception: &Value) -> Value {
    let candidates = perception["candidates"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let incomplete = perception["documents"].as_array().is_none_or(|docs| {
        docs.is_empty()
            || docs.iter().any(|d| {
                d["unreadable_pages"]
                    .as_array()
                    .is_none_or(|p| !p.is_empty())
            })
    });
    let (document_checks, scope_invalid, expert_count) = document_checks(perception);
    let mut observations = vec![];
    for field in [
        "arrears_amount",
        "expert_amount",
        "base_date",
        "proposal_date",
        "agreement_amount",
        "payment_date",
    ] {
        let evidence: Vec<Value> = candidates
            .iter()
            .filter(|c| c["field"] == field)
            .cloned()
            .collect();
        let values: BTreeSet<_> = evidence
            .iter()
            .filter_map(|e| e["normalized"].as_str())
            .collect();
        let uncertain = evidence
            .iter()
            .any(|e| e["ambiguous_context"] != false || e["confidence"] != "NATIVE_TEXT");
        let (status, reason) = if scope_invalid || (field == "expert_amount" && expert_count > 1) {
            ("NOT_VERIFIABLE", "Vinculação documental inválida ou múltiplos pedidos do perito. Revisão obrigatória antes de escolher valores.")
        } else if incomplete {
            (
                "NOT_VERIFIABLE",
                "Há página sem leitura utilizável. Não concluí a conferência.",
            )
        } else if evidence.is_empty() {
            (
                "ABSENT",
                "Não encontrei um rótulo inequívoco para este dado.",
            )
        } else if values.len() > 1 {
            (
                "CONFLICTING_SOURCES",
                "Encontrei valores diferentes. Nenhum foi escolhido automaticamente.",
            )
        } else if uncertain || values.len() != 1 {
            (
                "NOT_VERIFIABLE",
                "O contexto tem mais de uma interpretação ou a leitura precisa de revisão.",
            )
        } else {
            (
                "FOUND",
                "Identifiquei um valor com rótulo explícito. Confira sua origem abaixo.",
            )
        };
        observations.push(Observation {
            field: field.into(),
            status: status.into(),
            value: if status == "FOUND" {
                values.first().map(|v| v.to_string())
            } else {
                None
            },
            reason: reason.into(),
            evidence,
        });
    }
    let value = |key: &str| {
        observations
            .iter()
            .find(|o| o.field == key)
            .and_then(|o| o.value.as_deref())
    };
    let sum = value("arrears_amount")
        .and_then(|a| Decimal::from_str(a).ok())
        .zip(value("expert_amount").and_then(|p| Decimal::from_str(p).ok()))
        .and_then(|(a, p)| a.checked_add(p));
    let official = perception["official_total"]
        .as_str()
        .and_then(|v| Decimal::from_str(v).ok());
    let sum_status = match (sum, official) {
        (Some(a), Some(b)) if a == b => "VALIDATED",
        (Some(_), Some(_)) => "DIVERGENT",
        (Some(_), None) => "CALCULATED",
        _ => "NOT_VERIFIABLE",
    };
    let policy: Value =
        serde_json::from_str(include_str!("../../../rules/recorded_procedure.json"))
            .expect("bundled policy");
    let proposal = value("proposal_date");
    let derived_month = proposal
        .filter(|d| chrono::NaiveDate::parse_from_str(d, "%Y-%m-%d").is_ok())
        .map(|d| &d[..7]);
    let explicit = value("base_date");
    let observation = |key: &str| observations.iter().find(|o| o.field == key).unwrap();
    let date_conflict = observation("proposal_date").status == "CONFLICTING_SOURCES"
        || observation("base_date").status == "CONFLICTING_SOURCES"
        || derived_month.zip(explicit).is_some_and(|(a, b)| a != b);
    let date_uncertain = observation("proposal_date").status == "NOT_VERIFIABLE"
        || observation("base_date").status == "NOT_VERIFIABLE";
    let base = if date_conflict || date_uncertain {
        None
    } else {
        derived_month.or(explicit)
    };
    let supplied = perception["official_base_date"].as_str();
    let date_status = if date_conflict {
        "CONFLICTING_SOURCES"
    } else {
        match (base, supplied) {
            (Some(_), None) if derived_month.is_some() => "DERIVED",
            (Some(_), None) => "FOUND",
            (Some(a), Some(b)) if a.len() != b.len() => "NOT_VERIFIABLE",
            (Some(a), Some(b)) if a == b => "VALIDATED",
            (Some(_), Some(_)) => "DIVERGENT",
            _ => "NOT_VERIFIABLE",
        }
    };
    let date_evidence = if derived_month.is_some() {
        &observation("proposal_date").evidence
    } else {
        &observation("base_date").evidence
    };
    let checks = json!([
        {"field":"total","status":sum_status,"expected":sum.map(|v|v.to_string()),"provided":perception["official_total"],
         "reason":"Soma aritmética dos atrasados e do valor solicitado ao perito. Compara apenas com o total informado neste ensaio; não confirma a regra jurídica de composição."},
        {"field":"base_date","status":date_status,"expected":base,"provided":perception["official_base_date"],
         "reason":"Regra confirmada nesta sessão: data-base = mês/ano da data da proposta. Conflitos com data-base explícita impedem conclusão.","rule_id":policy["id"],"rule_version":policy["version"],"derived_from":proposal,"evidence":date_evidence}
    ]);
    let mut stops = vec![
        json!({"code":"POLICY_REQUIRED","reason":"Confirmar a aplicabilidade da composição do total e das opções de juros, tributos e honorários ao processo selecionado."}),
        json!({"code":"DISCOVERY_REQUIRED","reason":"Mapear e validar os formulários, identidade dos itens e salvamento no ambiente autorizado."}),
    ];
    if perception["expected_process"].is_null() {
        stops.push(json!({"code":"PROCESS_REQUIRED","reason":"Informe o processo para conferir a vinculação dos documentos."}));
    }
    if scope_invalid {
        stops.push(json!({"code":"DOCUMENT_SCOPE_INVALID","reason":"Documento sem identificação suficiente ou fora do padrão deste procedimento."}));
    }
    if expert_count > 1 {
        stops.push(json!({"code":"MULTIPLE_DOCUMENTS","reason":"Há mais de um pedido de perito, mesmo que os valores sejam iguais. Não somar nem escolher automaticamente."}));
    }
    if base.is_none() {
        stops.push(json!({"code":"BASE_DATE_UNRESOLVED","reason":"Data da proposta ausente, leitura incerta ou datas em conflito."}));
    }
    let plan = json!({"mode":"SUPERVISED","ready":false,"official_changes":0,
        "fields":[{"target":"Total do ofício","value":sum.map(|v|v.to_string()),"status":"PROPOSED"},
                  {"target":"Total do beneficiário","value":value("arrears_amount"),"status":"PROPOSED"},
                  {"target":"Devolução à Seção Judiciária","value":value("expert_amount"),"status":"POLICY_REQUIRED"},
                  {"target":"Data-base dos itens","value":base,"status":if base.is_some() {"DERIVED_BY_RULE"} else {"NOT_VERIFIABLE"},"rule_id":policy["id"]}],
        "actions":[{"name":"Salvar ofício e itens","state":"BLOCKED"},{"name":"Intimar partes","state":"EXCLUDED"},{"name":"Preparar transmissão","state":"EXCLUDED"}],
        "blockers":stops});
    json!({"id":uuid::Uuid::new_v4().to_string(),"created_at":chrono::Utc::now().to_rfc3339(),
    "mode":"REHEARSAL","official_changes":0,"document_checks":document_checks,"date_policy":policy,"supervised_plan":plan,"documents":perception["documents"],"observations":observations,"checks":checks,
    "scope_notice":"Conferência dos arquivos fornecidos. O número do processo só é confrontado quando informado; identidade do beneficiário e aplicabilidade das regras exigem confirmação.",
    "steps":[
        {"title":"Ler os documentos locais","state":"DONE","detail":"Texto, posição, página e hash foram processados pelo motor."},
        {"title":"Identificar valores e datas","state":"DONE","detail":"Rótulos conhecidos; fontes diferentes são preservadas."},
        {"title":"Conferir soma e data-base","state":"DONE","detail":"Regras determinísticas aplicadas aos dados encontrados."},
        {"title":"Preencher e salvar no eproc","state":"BLOCKED","detail":"Não executado. Consulte os impedimentos no plano supervisionado."},
        {"title":"Intimar partes e preparar transmissão","state":"BLOCKED","detail":"Não executado. Não existe acionamento destas ações."}
    ]})
}

pub async fn inspect(root: &Path, request: InspectionRequest) -> CoreResult<Value> {
    inspect_with_runtime(WorkerLaunch::development(root), request).await
}
pub async fn inspect_with_runtime(
    launch: WorkerLaunch,
    request: InspectionRequest,
) -> CoreResult<Value> {
    let _permit = INSPECTION_LIMIT.try_acquire().map_err(|_| "BUSY")?;
    if request.files.len() > 4
        || request
            .files
            .iter()
            .any(|f| f.name.len() > 180 || f.data.len() > 12 * 1024 * 1024)
        || (request.sample.is_some() && !request.files.is_empty())
    {
        return Err("IPC_ERROR".into());
    }
    let mut worker = Worker::spawn_launch(launch, false).await?;
    let mut staged = vec![];
    for (index, file) in request.files.iter().enumerate() {
        let bytes = STANDARD
            .decode(&file.data)
            .map_err(|_| "PDF_PARSE_FAILED")?;
        let path = worker.stage_document(index, &file.name, &bytes)?;
        staged.push(json!({"path":path,"name":file.name}));
    }
    let response = worker
        .call(
            "INSPECT_LOCAL_DOCUMENTS",
            json!({"documents":staged,"sample":request.sample,
        "official_total":request.official_total,"official_base_date":request.official_base_date,"expected_process":request.expected_process}),
        )
        .await;
    worker.shutdown().await;
    let mut report = evaluate(&response?);
    report["synthetic"] = json!(request.sample.is_some());
    Ok(report)
}
