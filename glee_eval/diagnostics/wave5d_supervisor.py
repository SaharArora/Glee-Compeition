"""Fail-closed external supervisor for the offline Wave 5D Model-A campaign.

The supervisor is intentionally outside the fitted-model process.  It limits
per-process address space before ``exec``, independently polls aggregate RSS and
thread count for the complete child process tree, uses a monotonic deadline,
and owns termination.  Every terminal path produces one atomic certificate and
there is deliberately no restart loop.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import math
import os
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


GIB = 1024 ** 3
DEFAULT_MAX_RSS_BYTES = 7 * GIB
DEFAULT_MAX_WORKER_THREADS = 6
DEFAULT_POLL_SECONDS = 0.20
DEFAULT_GRACE_SECONDS = 30.0
CERTIFICATE_SCHEMA = "glee.wave5d.external_supervisor.v1"


@dataclass(frozen=True)
class ProcessSample:
    rss_bytes: int
    worker_threads: int
    process_count: int
    pids: tuple[int, ...]


class MonitorUnavailable(RuntimeError):
    """Raised when independent resource inspection cannot be completed."""


def _linux_children(pid: int) -> list[int]:
    children: list[int] = []
    path = Path(f"/proc/{pid}/task/{pid}/children")
    try:
        raw = path.read_text(encoding="ascii")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return children
    for value in raw.split():
        try:
            children.append(int(value))
        except ValueError:
            raise MonitorUnavailable("non-integer PID in Linux children list")
    return children


def _linux_task(pid: int) -> tuple[int, int]:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except FileNotFoundError as exc:
        raise ProcessLookupError(pid) from exc
    fields: dict[str, str] = {}
    for line in status.splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            fields[name] = value.strip()
    if "VmRSS" not in fields or "Threads" not in fields:
        raise MonitorUnavailable(f"Linux task fields unavailable for PID {pid}")
    rss_kib = int(fields["VmRSS"].split()[0])
    return rss_kib * 1024, int(fields["Threads"])


class _DarwinTaskInfo(ctypes.Structure):
    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("total_user", ctypes.c_uint64),
        ("total_system", ctypes.c_uint64),
        ("threads_user", ctypes.c_uint64),
        ("threads_system", ctypes.c_uint64),
        ("policy", ctypes.c_int32),
        ("faults", ctypes.c_int32),
        ("pageins", ctypes.c_int32),
        ("cow_faults", ctypes.c_int32),
        ("messages_sent", ctypes.c_int32),
        ("messages_received", ctypes.c_int32),
        ("syscalls_mach", ctypes.c_int32),
        ("syscalls_unix", ctypes.c_int32),
        ("csw", ctypes.c_int32),
        ("threadnum", ctypes.c_int32),
        ("numrunning", ctypes.c_int32),
        ("priority", ctypes.c_int32),
    ]


class _DarwinInspector:
    PROC_PIDTASKINFO = 4

    def __init__(self) -> None:
        library = ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib"
        self.lib = ctypes.CDLL(library)
        self.lib.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.lib.proc_pidinfo.restype = ctypes.c_int
        self.lib.proc_listchildpids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_listchildpids.restype = ctypes.c_int

    def children(self, pid: int) -> list[int]:
        capacity = 128
        while capacity <= 65536:
            values = (ctypes.c_int * capacity)()
            used_bytes = int(self.lib.proc_listchildpids(pid, values, ctypes.sizeof(values)))
            if used_bytes < 0:
                raise MonitorUnavailable(f"proc_listchildpids failed for PID {pid}")
            count = used_bytes // ctypes.sizeof(ctypes.c_int)
            if count < capacity:
                return [int(values[index]) for index in range(count) if int(values[index]) > 0]
            capacity *= 2
        raise MonitorUnavailable("Darwin descendant list exceeded fixed safety bound")

    def task(self, pid: int) -> tuple[int, int]:
        info = _DarwinTaskInfo()
        used = int(self.lib.proc_pidinfo(
            pid,
            self.PROC_PIDTASKINFO,
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ))
        if used != ctypes.sizeof(info):
            raise ProcessLookupError(pid)
        return int(info.resident_size), int(info.threadnum)


def inspect_process_tree(root_pid: int) -> ProcessSample:
    """Return aggregate current RSS and threads for ``root_pid`` descendants."""

    system = platform.system()
    darwin = _DarwinInspector() if system == "Darwin" else None
    if system not in {"Darwin", "Linux"}:
        raise MonitorUnavailable(f"unsupported monitoring platform: {system}")
    pending = [int(root_pid)]
    seen: set[int] = set()
    rss = 0
    threads = 0
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            children = darwin.children(pid) if darwin else _linux_children(pid)
            task_rss, task_threads = darwin.task(pid) if darwin else _linux_task(pid)
        except ProcessLookupError:
            continue
        rss += task_rss
        threads += task_threads
        pending.extend(children)
    if not seen or threads <= 0:
        raise MonitorUnavailable(f"no inspectable task at PID {root_pid}")
    return ProcessSample(rss_bytes=rss, worker_threads=threads, process_count=len(seen), pids=tuple(sorted(seen)))


def _atomic_certificate(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _child_limits(max_rss_bytes: int, max_worker_threads: int, deadline_seconds: float) -> Callable[[], None]:
    # RLIMIT_AS is a per-process backstop.  The independent poller enforces the
    # stricter aggregate RSS limit over the entire process tree.
    address_space = max(int(max_rss_bytes) + GIB, int(max_rss_bytes) * 2)

    def apply() -> None:
        # Darwin exposes RLIMIT_AS/RSS but rejects useful finite values on the
        # supported runner.  Aggregate libproc polling is the mandatory memory
        # mechanism there.  Linux receives both the polling guard and a kernel
        # address-space backstop.
        if platform.system() == "Linux":
            resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
        cpu_budget = max(1, int(math.ceil(deadline_seconds * max_worker_threads)))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_budget, cpu_budget + 1))
        if platform.system() == "Linux" and hasattr(resource, "RLIMIT_RSS"):
            try:
                resource.setrlimit(resource.RLIMIT_RSS, (int(max_rss_bytes), int(max_rss_bytes)))
            except (OSError, ValueError):
                # RLIMIT_RSS is advisory/unsupported on some kernels; aggregate
                # polling remains mandatory and fail-closed.
                pass
    return apply


def _terminate_group(process: subprocess.Popen[Any], grace_seconds: float) -> tuple[bool, int | None]:
    term_sent = False
    kill_sent = False
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            term_sent = True
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + max(0.0, float(grace_seconds))
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            kill_sent = True
        except ProcessLookupError:
            pass
    try:
        return term_sent or kill_sent, process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        return True, None


def supervise(
    command: Sequence[str],
    *,
    certificate_path: str | Path,
    deadline_seconds: float,
    max_rss_bytes: int = DEFAULT_MAX_RSS_BYTES,
    max_worker_threads: int = DEFAULT_MAX_WORKER_THREADS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    artifact_root: str | Path | None = None,
    max_artifact_bytes: int | None = None,
    not_after_wall_time_ns: int | None = None,
    monitor: Callable[[int], ProcessSample] = inspect_process_tree,
) -> dict[str, Any]:
    """Run one command once and atomically certify success or termination."""

    if not command or not str(command[0]):
        raise ValueError("supervisor requires a nonempty command")
    if deadline_seconds <= 0 or max_rss_bytes <= 0 or max_worker_threads <= 0:
        raise ValueError("deadline and resource limits must be positive")
    if poll_seconds <= 0 or grace_seconds < 0:
        raise ValueError("poll interval must be positive and grace nonnegative")
    if (artifact_root is None) != (max_artifact_bytes is None):
        raise ValueError("artifact root and byte limit must be specified together")
    destination = Path(certificate_path)
    if destination.exists():
        raise FileExistsError(f"termination certificate already exists: {destination}")

    started_monotonic = time.monotonic()
    started_wall_ns = time.time_ns()
    absolute_remaining = (
        (int(not_after_wall_time_ns) - started_wall_ns) / 1e9
        if not_after_wall_time_ns is not None else float(deadline_seconds)
    )
    if absolute_remaining <= 0:
        certificate = {
            "schema": CERTIFICATE_SCHEMA,
            "status": "failed",
            "termination_reason": "absolute_safe_shutdown_boundary_already_reached",
            "command_sha256": hashlib.sha256(
                json.dumps([str(value) for value in command], separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "child_pid": None,
            "child_exit_code": None,
            "started_wall_time_ns": started_wall_ns,
            "elapsed_monotonic_seconds": time.monotonic() - started_monotonic,
            "limits": {
                "aggregate_rss_bytes": int(max_rss_bytes),
                "worker_threads": int(max_worker_threads),
                "deadline_seconds": float(deadline_seconds),
                "effective_monotonic_deadline_seconds": 0.0,
                "not_after_wall_time_ns": int(not_after_wall_time_ns),
                "poll_seconds": float(poll_seconds),
                "sigterm_grace_seconds": float(grace_seconds),
                "automatic_restarts": 0,
                "artifact_root": str(Path(artifact_root).resolve()) if artifact_root is not None else None,
                "artifact_bytes": int(max_artifact_bytes) if max_artifact_bytes is not None else None,
            },
            "observed": {
                "peak_aggregate_rss_bytes": 0,
                "peak_worker_threads": 0,
                "peak_process_count": 0,
                "peak_artifact_bytes": 0,
            },
            "termination_signal_sent": False,
            "monitor_error": None,
        }
        _atomic_certificate(destination, certificate)
        return certificate
    effective_deadline_seconds = min(float(deadline_seconds), absolute_remaining)
    env = os.environ.copy()
    for variable in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
    ):
        env[variable] = str(max_worker_threads)
    env["PYTHONHASHSEED"] = "0"
    env["WAVE5D_EXTERNAL_SUPERVISOR_ACTIVE"] = "1"
    process = subprocess.Popen(
        [str(value) for value in command],
        stdin=subprocess.DEVNULL,
        env=env,
        preexec_fn=_child_limits(max_rss_bytes, max_worker_threads, effective_deadline_seconds),
        start_new_session=True,
    )
    peak_rss = 0
    peak_threads = 0
    peak_processes = 0
    peak_artifact_bytes = 0
    termination_reason: str | None = None
    monitor_error: str | None = None
    exit_code: int | None = None
    terminated = False
    try:
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                break
            elapsed = time.monotonic() - started_monotonic
            if elapsed >= effective_deadline_seconds:
                termination_reason = "monotonic_deadline_exceeded"
                break
            try:
                sample = monitor(process.pid)
            except (MonitorUnavailable, OSError, ValueError) as exc:
                exit_code = process.poll()
                if exit_code is not None:
                    break
                termination_reason = "independent_monitor_unavailable"
                monitor_error = f"{type(exc).__name__}: {exc}"
                break
            peak_rss = max(peak_rss, sample.rss_bytes)
            peak_threads = max(peak_threads, sample.worker_threads)
            peak_processes = max(peak_processes, sample.process_count)
            if sample.rss_bytes > max_rss_bytes:
                termination_reason = "aggregate_rss_limit_exceeded"
                break
            if sample.worker_threads > max_worker_threads:
                termination_reason = "worker_thread_limit_exceeded"
                break
            if artifact_root is not None and max_artifact_bytes is not None:
                root = Path(artifact_root)
                try:
                    current_artifacts = sum(item.stat().st_size for item in root.rglob("*") if item.is_file()) if root.exists() else 0
                except OSError as exc:
                    termination_reason = "artifact_monitor_unavailable"
                    monitor_error = f"{type(exc).__name__}: {exc}"
                    break
                peak_artifact_bytes = max(peak_artifact_bytes, current_artifacts)
                if current_artifacts > max_artifact_bytes:
                    termination_reason = "artifact_byte_limit_exceeded"
                    break
            time.sleep(min(poll_seconds, max(0.0, effective_deadline_seconds - elapsed)))
        if termination_reason is not None:
            terminated, exit_code = _terminate_group(process, grace_seconds)
        elif exit_code is None:
            exit_code = process.wait()
    except BaseException:
        termination_reason = termination_reason or "supervisor_exception"
        terminated, exit_code = _terminate_group(process, grace_seconds)
        raise
    finally:
        elapsed = time.monotonic() - started_monotonic
        status = "success" if termination_reason is None and exit_code == 0 else "failed"
        if termination_reason is None and exit_code != 0:
            termination_reason = "child_nonzero_exit"
        certificate = {
            "schema": CERTIFICATE_SCHEMA,
            "status": status,
            "termination_reason": termination_reason,
            "command_sha256": hashlib.sha256(
                json.dumps([str(value) for value in command], separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "child_pid": process.pid,
            "child_exit_code": exit_code,
            "started_wall_time_ns": started_wall_ns,
            "elapsed_monotonic_seconds": elapsed,
            "limits": {
                "aggregate_rss_bytes": int(max_rss_bytes),
                "worker_threads": int(max_worker_threads),
                "deadline_seconds": float(deadline_seconds),
                "effective_monotonic_deadline_seconds": effective_deadline_seconds,
                "not_after_wall_time_ns": int(not_after_wall_time_ns) if not_after_wall_time_ns is not None else None,
                "poll_seconds": float(poll_seconds),
                "sigterm_grace_seconds": float(grace_seconds),
                "automatic_restarts": 0,
                "artifact_root": str(Path(artifact_root).resolve()) if artifact_root is not None else None,
                "artifact_bytes": int(max_artifact_bytes) if max_artifact_bytes is not None else None,
            },
            "observed": {
                "peak_aggregate_rss_bytes": peak_rss,
                "peak_worker_threads": peak_threads,
                "peak_process_count": peak_processes,
                "peak_artifact_bytes": peak_artifact_bytes,
            },
            "termination_signal_sent": terminated,
            "monitor_error": monitor_error,
        }
        _atomic_certificate(destination, certificate)
    return certificate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--deadline-seconds", required=True, type=float)
    parser.add_argument("--max-rss-bytes", type=int, default=DEFAULT_MAX_RSS_BYTES)
    parser.add_argument("--max-worker-threads", type=int, default=DEFAULT_MAX_WORKER_THREADS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--grace-seconds", type=float, default=DEFAULT_GRACE_SECONDS)
    parser.add_argument("--artifact-root")
    parser.add_argument("--max-artifact-bytes", type=int)
    parser.add_argument("--not-after-wall-time-ns", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    result = supervise(
        command,
        certificate_path=args.certificate,
        deadline_seconds=args.deadline_seconds,
        max_rss_bytes=args.max_rss_bytes,
        max_worker_threads=args.max_worker_threads,
        poll_seconds=args.poll_seconds,
        grace_seconds=args.grace_seconds,
        artifact_root=args.artifact_root,
        max_artifact_bytes=args.max_artifact_bytes,
        not_after_wall_time_ns=args.not_after_wall_time_ns,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
