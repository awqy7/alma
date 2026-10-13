use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ProcessState {
    Queued,
    SessionCheck,
    OpeningProcess,
    ReadingRequisition,
    IndexingDocuments,
    Downloading,
    Parsing,
    Extracting,
    Normalizing,
    Reconciling,
    Validated,
    Exception,
    Failed,
    Paused,
}
impl ProcessState {
    pub fn allows(self, next: Self) -> bool {
        use ProcessState::*;
        matches!(
            (self, next),
            (Queued, SessionCheck)
                | (SessionCheck, OpeningProcess)
                | (OpeningProcess, ReadingRequisition)
                | (ReadingRequisition, IndexingDocuments)
                | (ReadingRequisition, Reconciling)
                | (IndexingDocuments, Downloading)
                | (IndexingDocuments, Reconciling)
                | (Downloading, Parsing)
                | (Parsing, Extracting)
                | (Extracting, Normalizing)
                | (Normalizing, Downloading)
                | (Normalizing, Reconciling)
                | (Reconciling, Validated)
                | (Paused, SessionCheck)
                | (Exception, SessionCheck)
                | (Failed, SessionCheck)
        ) || (!matches!(self, Validated | Failed | Exception | Paused)
            && matches!(next, Paused | Failed | Exception))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn forbids_skipping_and_resumes_via_session() {
        assert!(!ProcessState::Queued.allows(ProcessState::Validated));
        assert!(ProcessState::Parsing.allows(ProcessState::Paused));
        assert!(!ProcessState::Paused.allows(ProcessState::Parsing));
        assert!(ProcessState::Paused.allows(ProcessState::SessionCheck));
    }
}
