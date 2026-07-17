from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
import csv
import json
import os
from pathlib import Path
import re
import shutil
import signal
import time
from typing import Any

from agent_factory.local_inference.implementation import LlamaImplementationBuild
from agent_factory.local_inference.node_control import InferenceOperatorAnalysisOptions
from agent_factory.model_pool.schema import LlamaCppInferenceConfig, LocalModelArtifact, ModelPoolProfile
from agent_factory.paths import factory_artifact_path


_GRAPH_NODE_PATTERN = re.compile(
    r"node\s+#\d+\s+\((?P<operation>[^)]+)\).*?\[(?P<backend>[^\]]+)\]",
    re.IGNORECASE,
)
_GRAPH_SPLIT_PATTERN = re.compile(
    r"##\s+SPLIT\s+#\d+\s*:\s*(?P<backend>\S+)",
    re.IGNORECASE,
)


async def run_llama_operator_analysis(
    *,
    profile: ModelPoolProfile,
    artifact: LocalModelArtifact,
    build: LlamaImplementationBuild,
    analysis_id: str,
    options: InferenceOperatorAnalysisOptions,
) -> dict[str, Any]:
    profiler = shutil.which("rocprofv3")
    if profiler is None:
        raise RuntimeError("rocprofv3 is unavailable on the inference node")
    benchmark_binary = Path(build.benchmark_binary_path).expanduser().resolve()
    if not benchmark_binary.is_file() or not os.access(benchmark_binary, os.X_OK):
        raise RuntimeError(
            f"active llama.cpp build does not provide an executable llama-bench: {benchmark_binary}"
        )
    model_path = artifact.resolved_path()
    if not model_path.is_file():
        raise RuntimeError(f"llama.cpp model file is unavailable: {model_path}")
    inference = profile.inference
    if not isinstance(inference, LlamaCppInferenceConfig):
        raise ValueError("operator analysis requires llama.cpp inference settings")

    analysis_root = factory_artifact_path(
        "benchmark",
        "operator-analysis",
        _safe_analysis_id(analysis_id),
    )
    analysis_root.mkdir(parents=True, exist_ok=False)
    phases = [
        await _run_phase(
            phase="prefill",
            profiler=profiler,
            benchmark_binary=benchmark_binary,
            model_path=model_path,
            inference=inference,
            prompt_tokens=options.prefill_tokens,
            generation_tokens=0,
            repetitions=options.repetitions,
            top_kernels=options.top_kernels,
            output_root=analysis_root,
        ),
        await _run_phase(
            phase="decode",
            profiler=profiler,
            benchmark_binary=benchmark_binary,
            model_path=model_path,
            inference=inference,
            prompt_tokens=0,
            generation_tokens=options.decode_tokens,
            repetitions=options.repetitions,
            top_kernels=options.top_kernels,
            output_root=analysis_root,
        ),
    ]
    return {
        "profiler": "rocprofv3",
        "phases": phases,
        "warnings": [
            warning
            for phase in phases
            for warning in phase.get("warnings", [])
        ],
    }


async def _run_phase(
    *,
    phase: str,
    profiler: str,
    benchmark_binary: Path,
    model_path: Path,
    inference: LlamaCppInferenceConfig,
    prompt_tokens: int,
    generation_tokens: int,
    repetitions: int,
    top_kernels: int,
    output_root: Path,
) -> dict[str, Any]:
    phase_root = output_root / phase
    profiler_root = phase_root / "rocprof"
    profiler_root.mkdir(parents=True)
    benchmark_command = [
        str(benchmark_binary),
        "-m",
        str(model_path),
        "-p",
        str(prompt_tokens),
        "-n",
        str(generation_tokens),
        "-r",
        str(repetitions),
        "-ngl",
        str(inference.gpu_layers),
        "-ctk",
        inference.cache_type_k,
        "-ctv",
        inference.cache_type_v,
        "-fa",
        "on" if inference.flash_attention else "off",
        "-o",
        "json",
        "--no-warmup",
    ]
    command = [
        profiler,
        "--kernel-trace",
        "--stats",
        "--output-format",
        "csv",
        "--output-directory",
        str(profiler_root),
        "--",
        *benchmark_command,
    ]
    environment = dict(os.environ)
    environment["GGML_SCHED_DEBUG"] = "2"
    custom_kernel_events_path = phase_root / "custom-kernel-events.jsonl"
    environment["AGENTFACTORY_KERNEL_TRACE_OUTPUT"] = str(custom_kernel_events_path)
    started = time.perf_counter()
    process = await asyncio.create_subprocess_exec(
        *command,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=3600,
        )
    except BaseException:
        await _terminate_process_group(process)
        raise
    elapsed_seconds = time.perf_counter() - started
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    (phase_root / "stdout.jsonl").write_text(stdout, encoding="utf-8")
    (phase_root / "stderr.log").write_text(stderr, encoding="utf-8")
    (phase_root / "command.json").write_text(
        json.dumps(benchmark_command, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if process.returncode != 0:
        detail = _last_nonempty_line(stderr) or _last_nonempty_line(stdout)
        raise RuntimeError(
            f"{phase} operator analysis exited with code {process.returncode}: {detail}"
        )

    top_kernel_rows, profiler_warnings = _read_kernel_stats(profiler_root, top_kernels)
    return {
        "phase": phase,
        "elapsed_seconds": elapsed_seconds,
        "benchmark_rows": _read_json_rows(stdout),
        "top_kernels": top_kernel_rows,
        "graph_operators": _read_graph_operators(stderr),
        "custom_kernels": _read_custom_kernel_events(custom_kernel_events_path),
        "artifact_directory": str(phase_root),
        "warnings": profiler_warnings,
    }


def _read_custom_kernel_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    counters: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "selected_count": 0,
            "dispatch_count": 0,
            "fallback_count": 0,
            "fallback_reasons": Counter(),
        }
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kernel_id = str(event.get("kernel_id") or "").strip()
        event_type = str(event.get("event") or "").strip().lower()
        if not kernel_id or event_type not in {"selected", "dispatch", "fallback"}:
            continue
        counters[kernel_id][f"{event_type}_count"] += 1
        if event_type == "fallback":
            reason = str(event.get("fallback_reason") or "unspecified").strip() or "unspecified"
            counters[kernel_id]["fallback_reasons"][reason] += 1
    return [
        {
            "kernel_id": kernel_id,
            "selected_count": values["selected_count"],
            "dispatch_count": values["dispatch_count"],
            "fallback_count": values["fallback_count"],
            "fallback_reasons": dict(values["fallback_reasons"]),
        }
        for kernel_id, values in sorted(counters.items())
    ]


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=20.0)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()


def _read_json_rows(output: str) -> list[dict[str, Any]]:
    text = output.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [payload] if isinstance(payload, dict) else []


def _read_graph_operators(stderr: str) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    split_backend = ""
    for line in stderr.splitlines():
        split_match = _GRAPH_SPLIT_PATTERN.search(line)
        if split_match:
            split_backend = split_match.group("backend").strip()
        node_match = _GRAPH_NODE_PATTERN.search(line)
        if not node_match:
            continue
        operation = node_match.group("operation").strip()
        backend_field = node_match.group("backend").strip()
        backend = (backend_field.split(maxsplit=1)[0] if backend_field else split_backend) or "unknown"
        counts[(operation, backend)] += 1
    return [
        {"operation": operation, "backend": backend, "count": count}
        for (operation, backend), count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _read_kernel_stats(root: Path, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    csv_paths = sorted(root.rglob("*.csv"))
    aggregate_rows: list[tuple[str, int, float]] = []
    trace_rows: list[tuple[str, int, float]] = []
    for path in csv_paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                normalized = {_normalize_header(key): value for key, value in row.items() if key}
                name = _first_text(
                    normalized,
                    "kernelname",
                    "kernel",
                    "function",
                    "name",
                )
                if not name:
                    continue
                calls = _first_number(normalized, "calls", "callcount", "count")
                total_ns = _duration_ns(normalized)
                if total_ns is not None and calls is not None:
                    aggregate_rows.append((name, max(0, int(calls)), max(0.0, total_ns)))
                    continue
                start = _first_number(normalized, "starttimestamp", "start", "begints")
                end = _first_number(normalized, "endtimestamp", "end", "endts")
                if start is not None and end is not None and end >= start:
                    trace_rows.append((name, 1, end - start))

    source_rows = aggregate_rows if aggregate_rows else trace_rows
    if not source_rows:
        return [], [
            "rocprofv3 completed but no recognizable kernel timing rows were found; "
            f"inspect CSV artifacts under {root}"
        ]
    totals: defaultdict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for name, calls, duration_ns in source_rows:
        totals[name][0] += calls
        totals[name][1] += duration_ns
    all_duration = sum(values[1] for values in totals.values())
    ranked = sorted(totals.items(), key=lambda item: item[1][1], reverse=True)[:limit]
    return [
        {
            "name": name,
            "calls": int(values[0]),
            "total_duration_ns": values[1],
            "average_duration_ns": values[1] / values[0] if values[0] else 0.0,
            "duration_percent": values[1] / all_duration * 100 if all_duration else 0.0,
        }
        for name, values in ranked
    ], []


def _duration_ns(row: dict[str, str]) -> float | None:
    for key, scale in (
        ("totaldurationns", 1.0),
        ("totalduration", 1.0),
        ("durationns", 1.0),
        ("duration", 1.0),
        ("totaldurationus", 1_000.0),
        ("totaldurationms", 1_000_000.0),
    ):
        value = _first_number(row, key)
        if value is not None:
            return value * scale
    return None


def _first_text(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _first_number(row: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        value = str(row.get(key) or "").strip().replace(",", "")
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _safe_analysis_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", normalized):
        raise ValueError("analysis_id must be a 32-character lowercase hexadecimal identifier")
    return normalized


def _last_nonempty_line(value: str) -> str:
    return next((line.strip() for line in reversed(value.splitlines()) if line.strip()), "")
