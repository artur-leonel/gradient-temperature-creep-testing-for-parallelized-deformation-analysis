from __future__ import annotations

import contextlib
import io
import os
import traceback
from dataclasses import dataclass

from src.config import Paths
from src.pipeline import workflow


@dataclass(frozen=True)
class RunResult:
    return_code: int
    stdout: str
    stderr: str


@contextlib.contextmanager
def _chdir(target: str):
    old = os.getcwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(old)


def run_workflow(paths: Paths) -> RunResult:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    return_code = 0
    with _chdir(str(paths.project_root)):
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            try:
                workflow.main()
            except SystemExit as exc:
                return_code = int(exc.code) if isinstance(exc.code, int) else 1
            except Exception:
                return_code = 1
                traceback.print_exc(file=stderr_buffer)
    return RunResult(
        return_code=return_code,
        stdout=stdout_buffer.getvalue(),
        stderr=stderr_buffer.getvalue(),
    )
