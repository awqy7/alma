use alma_core::worker::Worker;
use serde_json::json;
use std::{path::PathBuf, time::Duration};

#[tokio::test]
async fn timeout_kills_worker_and_does_not_consume_stale_response() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let python = root.join(if cfg!(windows) {
        ".venv/Scripts/python.exe"
    } else {
        ".venv/bin/python"
    });
    let temp = tempfile::tempdir().unwrap();
    std::fs::create_dir(temp.path().join("engine")).unwrap();
    std::fs::write(temp.path().join("engine/__init__.py"), "").unwrap();
    std::fs::write(temp.path().join("engine/worker.py"),r#"
import json,sys,time
from pathlib import Path
for line in sys.stdin:
    command=json.loads(line)
    if command['name']!='PING': time.sleep(60)
    print(json.dumps({'version':1,'type':'RESULT','id':command['id'],'ok':True,'payload':{}}),flush=True)
Path('closed').write_text('graceful')
"#).unwrap();
    let mut worker = Worker::spawn(temp.path(), &python, false).await.unwrap();
    worker.shutdown().await;
    assert_eq!(
        std::fs::read_to_string(temp.path().join("closed")).unwrap(),
        "graceful"
    );
    worker.restart().await.unwrap();
    worker.deadline = Duration::from_millis(100);
    assert_eq!(
        worker
            .call("HANG", json!({}))
            .await
            .unwrap_err()
            .to_string(),
        "TIMEOUT"
    );
    assert!(worker.call("PING", json!({})).await.is_err());
    worker.shutdown().await;
}
