"""Entry point executed inside the fresh interpreter (see ``_subprocess``)."""

import importlib
import json
import random
from pathlib import Path
from typing import Any

from forecast_interface.conformance._canonical import canonical
from forecast_interface.conformance.fixtures import Fixtures


def _load_fixtures(spec: str) -> Fixtures:
    module_name, _, attr = spec.partition(":")
    factory = getattr(importlib.import_module(module_name), attr)
    fixtures = factory()
    if not isinstance(fixtures, Fixtures):
        raise TypeError(f"{spec} did not return an object implementing Fixtures")
    return fixtures


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload))


def main(spec: dict[str, Any]) -> None:
    out = Path(spec["result_path"])
    try:
        fixtures = _load_fixtures(spec["fixtures_spec"])
        model = fixtures.model_factory()
        artifact = model.deserialize_artifact(Path(spec["artifact_path"]).read_bytes())
        inputs, issue = fixtures.predict_inputs()
    except Exception as exc:
        _write(out, {"status": "load_error", "error": f"{type(exc).__name__}: {exc}"})
        return
    try:
        result = model.predict(
            artifact,
            inputs=inputs,
            issue_datetime=issue,
            rng=random.Random(spec["seed"]),
        )
    except Exception as exc:
        _write(
            out, {"status": "predict_error", "error": f"{type(exc).__name__}: {exc}"}
        )
        return
    _write(out, {"status": "ok", "result": canonical(result)})
