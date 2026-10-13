// Protocol error codes, mirrored from engine/ipc/contracts.py.
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ErrorCode {
    BrowserProfileInUse,
    BrowserNavigationFailed,
    SessionNotFound,
    SessionExpired,
    ReauthRequired,
    LocalizerNotFound,
    ProcessNotFound,
    RequisitionNotFound,
    DocumentNotFound,
    MultipleDocuments,
    DownloadFailed,
    PdfParseFailed,
    OcrFailed,
    FieldNotFound,
    FieldAmbiguous,
    UiChanged,
    Timeout,
    HttpError,
    RateLimited,
    ConflictingSources,
    NotVerifiable,
    WorkerCrashed,
    IpcError,
    DatabaseError,
    DiscoveryRequired,
    SnapshotChanged,
    SessionScopeChanged,
}
