"""Regenerate reviewable JSON schemas from the worker's contract definitions."""
import json
from pathlib import Path
from engine.ipc.contracts import Command, RpvSnapshot, ExtractedFact

root = Path(__file__).resolve().parents[1]
for model in (Command, RpvSnapshot, ExtractedFact):
    target = root / 'docs/contracts' / f'{model.__name__}.schema.json'
    target.write_text(json.dumps(model.model_json_schema(), indent=2) + '\n')
