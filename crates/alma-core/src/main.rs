use alma_core::{runner::Runner, store::Store, worker::Worker};
use serde_json::json;
use std::{
    path::PathBuf,
    sync::{atomic::AtomicBool, Arc},
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).is_some_and(|v| v == "queue-fixture") {
        let root = PathBuf::from(args.get(2).ok_or("ROOT_REQUIRED")?).canonicalize()?;
        let url = args.get(3).ok_or("URL_REQUIRED")?;
        let db = PathBuf::from(args.get(4).ok_or("DATABASE_REQUIRED")?);
        let limit = args
            .get(5)
            .map(|v| v.parse::<usize>())
            .transpose()?
            .unwrap_or(100);
        let worker =
            Worker::spawn_launch(alma_core::runtime::WorkerLaunch::development(&root), true)
                .await?;
        let mut runner = Runner {
            store: Store::open(&db)?,
            worker,
            pause: Arc::new(AtomicBool::new(false)),
        };
        runner
            .worker
            .call("CONNECT", json!({"url":url,"headless":true}))
            .await?;
        let mut queue = runner.start_queue("Concluso Decisão RPV", |_| {}).await?;
        for _ in 0..limit {
            if queue["status"] != "RUNNING" {
                break;
            }
            queue = runner.queue_step(|_| {}).await?;
        }
        runner.worker.shutdown().await;
        println!("{}", queue);
        return Ok(());
    }
    if args.get(1).is_some_and(|v| v == "demo") {
        let root = PathBuf::from(args.get(2).ok_or("ROOT_REQUIRED")?).canonicalize()?;
        let db = PathBuf::from(args.get(3).ok_or("DATABASE_REQUIRED")?);
        println!(
            "{}",
            alma_core::demo::run(
                alma_core::runtime::WorkerLaunch::development(&root),
                &db,
                Default::default()
            )
            .await?
        );
        return Ok(());
    }
    if args.get(1).is_some_and(|v| v == "packaged-smoke") {
        let resources = PathBuf::from(args.get(2).ok_or("RESOURCES_REQUIRED")?).canonicalize()?;
        println!("{}", alma_core::runtime::verify_bundle(&resources).await?);
        return Ok(());
    }
    if args.get(1).is_some_and(|v| v == "preview") {
        let root = PathBuf::from(args.get(2).ok_or("PROJECT_ROOT_REQUIRED")?).canonicalize()?;
        let port = args
            .get(3)
            .map(|v| v.parse::<u16>())
            .transpose()?
            .unwrap_or(4318);
        return tokio::task::spawn_blocking(move || alma_core::preview_server::serve(&root, port))
            .await?;
    }
    if args.len() != 5 || args[1] != "fixture" {
        eprintln!("Usage: alma-core fixture PROJECT_ROOT LOOPBACK_URL DATABASE_PATH");
        std::process::exit(2);
    }
    let root = PathBuf::from(&args[2]).canonicalize()?;
    let python = root.join(if cfg!(windows) {
        ".venv/Scripts/python.exe"
    } else {
        ".venv/bin/python"
    });
    let worker = Worker::spawn(&root, &python, true).await?;
    let mut runner = Runner {
        store: Store::open(&PathBuf::from(&args[4]))?,
        worker,
        pause: Arc::new(AtomicBool::new(false)),
    };
    runner
        .worker
        .call("CONNECT", json!({"url":args[3],"headless":true}))
        .await?;
    let result = runner
        .review_current(None, |event| {
            eprintln!("{}", json!({"state":event["state"],"name":event["name"]}))
        })
        .await;
    runner.worker.shutdown().await;
    println!("{}", serde_json::to_string(&result?)?);
    Ok(())
}
