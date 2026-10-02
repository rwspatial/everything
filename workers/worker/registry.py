"""Discover processes in processes/: Python modules with DESCRIPTOR + run(), or folders with descriptor.json + run.R."""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft7Validator

HOME = Path(__file__).resolve().parent.parent
PROCESSES = HOME / "processes"
_SCHEMA = Draft7Validator(json.loads((HOME / "contracts" / "process.v1.schema.json").read_text()))


@dataclass
class Process:
    descriptor: dict
    python_module: str | None = None   # processes.<module>
    r_script: Path | None = None

    @property
    def id(self) -> str:
        return self.descriptor["id"]

    @property
    def timeout(self) -> int:
        return int(self.descriptor.get("resources", {}).get("timeoutSec", 900))


def discover() -> dict[str, Process]:
    found: dict[str, Process] = {}
    sys.path.insert(0, str(HOME))
    for f in sorted(PROCESSES.glob("*.py")):
        if f.name.startswith("_"):
            continue
        mod = importlib.import_module(f"processes.{f.stem}")
        found[mod.DESCRIPTOR["id"]] = Process(mod.DESCRIPTOR, python_module=f"processes.{f.stem}")
    for d in sorted(p for p in PROCESSES.iterdir() if (p / "descriptor.json").is_file()):
        desc = json.loads((d / "descriptor.json").read_text())
        found[desc["id"]] = Process(desc, r_script=d / "run.R")
    for p in found.values():
        errors = sorted(_SCHEMA.iter_errors(p.descriptor), key=lambda e: list(e.path))
        if errors:
            raise SystemExit(f"process {p.id}: descriptor invalid: {errors[0].message} at {list(errors[0].path)}")
    return found
