"""Fresh-interpreter reload of an artifact.

Limits are BEST EFFORT and this is NOT A SANDBOX: a timeout kills the child,
POSIX ``RLIMIT_CPU`` / ``RLIMIT_AS`` are applied where the platform honours
them (``RLIMIT_AS`` is ignored on some systems, e.g. macOS), and nothing
restricts filesystem, network or syscalls. Loading a model executes its code.
"""

import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple, Protocol

logger = logging.getLogger(__name__)

_BOOTSTRAP = (
    "import json, sys\n"
    "spec = json.load(sys.stdin)\n"
    "sys.path[:0] = spec['sys_path']\n"
    "from forecast_interface.conformance._reload_entry import main\n"
    "main(spec)\n"
)
_STDERR_TAIL = 2000


class ReloadKind(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    LOAD_ERROR = "load_error"
    PREDICT_ERROR = "predict_error"
    BAD_OUTPUT = "bad_output"


class SubprocessLimits(NamedTuple):
    timeout: timedelta
    cpu_seconds: int | None = None
    address_space_bytes: int | None = None


class ReloadOutcome(NamedTuple):
    kind: ReloadKind
    result: dict[str, Any] | None = None
    detail: str = ""
    stderr: str = ""


class ReloadRunner(Protocol):
    def __call__(
        self,
        *,
        fixtures_spec: str,
        artifact: bytes,
        seed: int,
        limits: SubprocessLimits,
    ) -> ReloadOutcome: ...


def _apply_limits(limits: SubprocessLimits) -> None:
    try:
        import resource
    except ImportError:
        return
    cpu = limits.cpu_seconds or math.ceil(limits.timeout.total_seconds()) + 1
    for kind, value in (
        (resource.RLIMIT_CPU, cpu),
        (getattr(resource, "RLIMIT_AS", None), limits.address_space_bytes),
    ):
        if kind is None or value is None:
            continue
        try:
            resource.setrlimit(kind, (value, value))
        except (ValueError, OSError):
            pass


def run_fresh_reload(
    *, fixtures_spec: str, artifact: bytes, seed: int, limits: SubprocessLimits
) -> ReloadOutcome:
    with tempfile.TemporaryDirectory(prefix="fi-conformance-") as tmp:
        artifact_path = Path(tmp) / "artifact.bin"
        result_path = Path(tmp) / "result.json"
        artifact_path.write_bytes(artifact)
        spec = {
            "fixtures_spec": fixtures_spec,
            "artifact_path": str(artifact_path),
            "result_path": str(result_path),
            "seed": seed,
            "sys_path": [os.getcwd() if p == "" else p for p in sys.path],
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _BOOTSTRAP],
                input=json.dumps(spec),
                capture_output=True,
                text=True,
                timeout=limits.timeout.total_seconds(),
                preexec_fn=(lambda: _apply_limits(limits))
                if os.name == "posix"
                else None,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = (
                exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
            )
            return ReloadOutcome(
                ReloadKind.TIMEOUT,
                detail=f"timed out after {limits.timeout.total_seconds():g}s",
                stderr=(stderr or "")[-_STDERR_TAIL:],
            )
        stderr_tail = proc.stderr[-_STDERR_TAIL:]
        if proc.returncode != 0 or not result_path.exists():
            return ReloadOutcome(
                ReloadKind.CRASHED,
                detail=f"interpreter exited with code {proc.returncode}",
                stderr=stderr_tail,
            )
        try:
            payload = json.loads(result_path.read_text())
            kind = ReloadKind(payload["status"])
        except (ValueError, KeyError) as exc:
            return ReloadOutcome(
                ReloadKind.BAD_OUTPUT, detail=str(exc), stderr=stderr_tail
            )
        return ReloadOutcome(
            kind,
            result=payload.get("result"),
            detail=payload.get("error", ""),
            stderr=stderr_tail,
        )
