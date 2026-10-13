"""Frozen console sidecar: pipes remain available; Rust hides its Windows console."""
import argparse
import asyncio
import logging
import multiprocessing
import sys
from engine.worker import main

if __name__ == '__main__':
    multiprocessing.freeze_support()
    # Windows console encoding must not corrupt JSONL evidence in Portuguese.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixture-mode',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(stream=sys.stderr,level=logging.INFO,format='%(message)s')
    asyncio.run(main(args.fixture_mode))
