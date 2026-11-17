#!/usr/bin/env python3
"""Qualify the actual packaged AVID adapter through the EnCap engine.

Uses a private synthetic fixture and installed verified local model. Acquisition
is explicit (--install-model); neither source audio nor transcripts are uploaded.
An unavailable platform is recorded separately from successful inference.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import tempfile

PHRASE = "Hello. This is a local transcription test. Every word should have a start and an end time."


def command(engine, *arguments, timeout=1800):
    env = dict(os.environ, PATH="")
    # Exercise packaged discovery; overrides must not substitute a developer
    # helper or media tools for the packaged executables under qualification.
    for key in ("ENCAP_AVID_TRANSCRIBER", "ENCAP_AVID_TRANSCRIPTION_LIBRARY", "ENCAP_FFMPEG", "ENCAP_FFPROBE"):
        env.pop(key, None)
    prefix = [str(item) for item in engine] if isinstance(engine, (tuple, list)) else [str(engine)]
    result = subprocess.run([*prefix, *map(str, arguments)], env=env,
                            capture_output=True, timeout=timeout)
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"{arguments[0]} did not return one JSON value: {result.stderr[-2000:]!r}") from error
    if result.returncode or isinstance(value, dict) and "error" in value:
        raise ValueError(f"{arguments[0]} failed: {value}; {result.stderr[-2000:]!r}")
    return value


def linked_module(engine):
    engine = Path(engine[0] if isinstance(engine, (tuple, list)) else engine)
    return next((p.resolve() for p in (
        engine.parent / "../Frameworks/EnCAPTranscription.framework/Versions/A/EnCAPTranscription",
        engine.parent / "EnCAPTranscription.framework/Versions/A/EnCAPTranscription",
    ) if p.is_file()), None)


def qualify(engine, model, install_model=False):
    status = command(engine, "transcription-status", timeout=120)
    if not isinstance(status, dict) or not isinstance(status.get("available"), bool):
        raise ValueError("Transcription status did not return a typed availability result")
    if not status["available"]:
        return {"status": "unavailable", "reason": status.get("reason") or "Shared runtime is unavailable; a shared-engine port or an explicit owner support-policy decision is required.",
                "model": model}
    module = linked_module(engine)
    if module is None:
        raise ValueError("Transcription is advertised as available without the packaged linked library")
    command(engine, "providers", timeout=120)
    models = command(engine, "models", timeout=120)
    item = next((item for item in models if item["id"] == model), None)
    if not item:
        raise ValueError(f"Qualification model {model!r} is absent from the shared catalog")
    if not item.get("installed"):
        if not install_model:
            return {"status": "not_run", "reason": f"Shared model {model} is not installed. Provision the shared cache or explicitly pass --install-model for an anonymous pinned download.", "model": model}
        command(engine, "install-model", model, timeout=7200)
    if platform.system() != "Darwin":
        raise ValueError("The packaged Apple linked module requires native macOS qualification")
    with tempfile.TemporaryDirectory(prefix="encap-avid-qualification-") as directory:
        temporary = Path(directory)
        source = temporary / "input"
        source.mkdir()
        speech = source / "speech.aiff"
        subprocess.run(["/usr/bin/say", "-v", "Samantha", "-r", "170", "-o", str(speech), PHRASE],
                       check=True, capture_output=True, timeout=120)
        fixture_sha = hashlib.sha256(speech.read_bytes()).hexdigest()
        project = command(engine, "inspect", source)
        payload = temporary / "payload.json"
        payload.write_text(json.dumps(project))
        original_payload = payload.read_bytes()
        segments = command(engine, "transcribe", payload, model, "--word-timestamps", "--language", "en")
        if not isinstance(segments, list) or not segments:
            raise ValueError("Real inference produced no transcript segments")
        text = " ".join(segment["text"] for segment in segments).lower()
        if not all(word in text for word in ("local", "transcription", "test", "word")):
            raise ValueError(f"Unexpected synthetic speech recognition: {text}")
        word_count = 0
        for segment in segments:
            start, end = segment.get("start_time_seconds"), segment.get("end_time_seconds")
            if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (start, end)) or end < start:
                raise ValueError("Real inference returned invalid segment timing")
            for word in segment.get("words", []):
                start, end = word.get("start_time_seconds"), word.get("end_time_seconds")
                if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (start, end)) or end < start:
                    raise ValueError("Real inference returned invalid word timing")
                word_count += 1
        if word_count < 10:
            raise ValueError("Timed qualification model did not return real word timestamps")
        if payload.read_bytes() != original_payload or hashlib.sha256(speech.read_bytes()).hexdigest() != fixture_sha:
            raise ValueError("Transcription changed its input project or source audio")
        project["transcript_segments"] = segments
        payload.write_text(json.dumps(project))
        for output_format in ("txt", "srt"):
            output = temporary / ("transcript." + output_format)
            command(engine, "export-transcript", payload, output, output_format)
            if "transcription" not in output.read_text().lower():
                raise ValueError(f"{output_format} export lost the real transcript text")
        return {"status": "passed", "scope": "packaged_offline_transcription_smoke", "model": model,
                "fixture": "locally synthesized English speech; not an accuracy benchmark",
                "fixture_sha256": fixture_sha, "segments": len(segments), "timed_words": word_count,
                "checks": ["packaged runtime discovery with empty PATH", "installed verified model", "local recognition",
                           "word timing", "TXT and SRT export", "input project and audio unchanged"],
                "limits": ["one short synthetic English fixture", "not a multilingual or long-form benchmark",
                           "other models, native UI and cancellation need separate verification"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    executable = parser.add_mutually_exclusive_group(required=True)
    executable.add_argument("--engine", type=Path, help="optional diagnostic command-line client")
    executable.add_argument("--application", type=Path, help="native app linked-operation diagnostics")
    parser.add_argument("--model", default=os.environ.get("ENCAP_QUALIFICATION_MODEL", "parakeet-tdt-v3"))
    parser.add_argument("--install-model", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = (args.application or args.engine).resolve(strict=True)
    diagnostic = [engine, "--linked-operation"] if args.application else engine
    runtime_files = {}
    app_layout = engine.parent.name == "MacOS" and (engine.parent.parent / "Info.plist").is_file()
    runtime_root = engine.parent.parent if app_layout else engine.parent
    module = linked_module(engine)
    if module is not None:
        for item in sorted(module.parent.rglob("*")):
            if item.is_file():
                runtime_files[item.relative_to(runtime_root).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
        metadata = runtime_root / "Resources/EnCAPTranscription" if app_layout else engine.parent / "EnCAPTranscription-metadata"
        if metadata.is_dir():
            for item in sorted(metadata.rglob("*")):
                if item.is_file():
                    runtime_files[item.relative_to(runtime_root).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system(), platform.system().lower())
    machine = {"aarch64": "arm64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    label = "intel" if system == "macos" and machine == "x86_64" else "x64" if machine == "x86_64" else machine
    report = {"schema": 1, "target": system + "-" + label, "runtime_files": runtime_files, ("application_sha256" if args.application else "engine_sha256"): hashlib.sha256(engine.read_bytes()).hexdigest(),
              "native_environment": {"system": platform.system(), "machine": platform.machine(), "version": platform.platform()}}
    try:
        report.update(qualify(diagnostic, args.model, args.install_model))
    except Exception as error:
        report.update(status="failed", error=str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
