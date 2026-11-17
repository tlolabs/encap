#!/usr/bin/env python3
"""Stage a built AVID adapter with all SwiftPM resources; never download weights."""
import argparse
import hashlib
import json
import re
import os
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import plistlib


def stage_licenses(checkouts: Path, resolved: Path, destination: Path):
    pins = json.loads(resolved.read_text())["pins"]
    checkouts_by_name = {path.name.lower(): path for path in checkouts.iterdir() if path.is_dir()}
    records = []
    for pin in pins:
        identity = pin["identity"]
        checkout = checkouts_by_name.get(identity.lower())
        if checkout is None:
            raise ValueError("Missing pinned SDK checkout for license staging: " + identity)
        revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        if revision != pin["state"]["revision"]:
            raise ValueError("SDK checkout revision differs from frozen resolution: " + identity)
        status = subprocess.check_output(["git", "-C", str(checkout), "-c", "core.fsmonitor=false",
                                          "status", "--porcelain=v1", "--untracked-files=all"], text=True)
        if status.strip():
            raise ValueError("Pinned SDK checkout has modified or untracked inputs: " + identity)
        licenses = []
        for path in sorted(checkout.rglob("*")):
            relative = path.relative_to(checkout)
            if not path.is_file() or any(part.startswith(".") for part in relative.parts):
                continue
            if not re.search(r"license|licence|notice|^copying", path.name, re.IGNORECASE):
                continue
            if path.name in ("license_header_template", "licenseignore") or path.suffix in (".py", ".swift", ".sh"):
                continue
            target = destination / identity / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            licenses.append({"path": (Path(identity) / relative).as_posix(),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if not licenses:
            raise ValueError("No license text found for resolved SDK: " + identity)
        records.append({"identity": identity, "repository": pin["location"], "revision": revision, "files": licenses})
    (destination / "resolved-sdk-licenses.json").write_text(json.dumps({"schema": 1, "dependencies": records}, indent=2) + "\n")
    return records


def code_identity(path):
    # Reuse the application packager's signature-normalized MachO identity.
    import linked_runtime
    return linked_runtime.normalized_code(path)


def native_output(*arguments):
    return subprocess.check_output(list(map(str, arguments)), text=True).strip()


def loader_identity(path):
    dependencies = re.findall(r"^\s+(.+?) \(compatibility version", native_output("/usr/bin/otool", "-L", path), re.M)
    commands = native_output("/usr/bin/otool", "-l", path)
    rpaths = re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.+?) \(offset", commands)
    return {"dependencies": dependencies[1:], "rpaths": rpaths}


def relocate_module(executable, payload):
    """Only the selected Xcode's explicitly required Swift compatibility runtime."""
    swiftc = Path(native_output("/usr/bin/xcrun", "--find", "swiftc")).resolve(strict=True)
    toolchain = swiftc.parents[2]
    if toolchain.suffix != ".xctoolchain":
        raise ValueError("Selected Swift compiler is not from an identified Xcode toolchain")
    runtime_sources = native_output("/usr/bin/xcrun", "swift-stdlib-tool", "--print", "--scan-executable", executable, "--platform", "macosx").splitlines()
    frameworks = payload / "Frameworks"
    frameworks.mkdir()
    notices = payload / "Resources/SwiftRuntimeNotices"
    notices.mkdir()
    records = []
    for source in map(Path, runtime_sources):
        source = source.resolve(strict=True)
        if not source.is_relative_to(toolchain) or not source.name.startswith("libswiftCompatibility") or source.suffix != ".dylib":
            raise ValueError("Unidentified Swift runtime dependency: " + str(source))
        destination = frameworks / source.name
        shutil.copy2(source, destination)
        records.append({"path": destination.relative_to(payload).as_posix(), "source_path": str(source),
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    for target in [executable, *sorted(frameworks.glob("*.dylib"))]:
        identity = loader_identity(target)
        for dependency in identity["dependencies"]:
            name = Path(dependency).name
            if dependency.startswith("@rpath/") and (frameworks / name).is_file():
                replacement = "@loader_path/Frameworks/" + name if target == executable else "@loader_path/" + name
                subprocess.run(["/usr/bin/install_name_tool", "-change", dependency, replacement, str(target)], check=True)
            elif not dependency.startswith(("/System/Library/", "/usr/lib/")):
                raise ValueError("Unprovided native module dependency: " + dependency)
        for rpath in identity["rpaths"]:
            if rpath != "/usr/lib/swift":
                subprocess.run(["/usr/bin/install_name_tool", "-delete_rpath", rpath, str(target)], check=True)
        install_id = "@rpath/EnCAPTranscription.framework/Versions/A/EnCAPTranscription" if target == executable else "@rpath/" + target.name
        subprocess.run(["/usr/bin/install_name_tool", "-id", install_id, str(target)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(target)], check=True)
        final = loader_identity(target)
        if any(value != "/usr/lib/swift" for value in final["rpaths"]) or any(
            not value.startswith(("/System/Library/", "/usr/lib/", "@loader_path/")) for value in final["dependencies"]):
            raise ValueError("Module still depends on a developer loader path")
    # Preserve the installed vendor's actual compiler/runtime notices and identity.
    # Apple exposes no exact matching source Git revision here; do not invent one.
    xcode = toolchain.parents[2]
    acknowledgment = xcode / "Resources/Acknowledgments.pdf"
    if not acknowledgment.is_file():
        raise ValueError("Selected Xcode runtime acknowledgment is missing")
    shutil.copy2(acknowledgment, notices / "Xcode-Acknowledgments.pdf")
    shutil.copy2(toolchain / "ToolchainInfo.plist", notices / "ToolchainInfo.plist")
    (notices / "SOURCE-IDENTITY.txt").write_text(
        "Apple Swift runtime supplied by the selected Xcode toolchain.\n" + native_output(swiftc, "--version") +
        "\nExact matching runtime source Git revision is not exposed by this installed toolchain.\n"
        "Corresponding runtime source is not bundled; this remains a distribution limitation.\n")
    return {"compiler_version": native_output(swiftc, "--version"), "toolchain": str(toolchain),
            "source_identity": "Installed Apple compiler build and exact runtime file digest; no invented upstream source revision",
            "corresponding_source": "unavailable from installed toolchain; distribution prerequisite remains unresolved",
            "notices_sha256": hashlib.sha256(acknowledgment.read_bytes()).hexdigest(), "libraries": records}


def framework_payload(directory):
    if directory.name != "EnCAPTranscription.framework":
        raise ValueError("Destination must be named EnCAPTranscription.framework")
    return directory / "Versions/A"


def stage(binary_directory: Path, destination: Path, checkouts=None, resolved=None):
    binary_directory = binary_directory.resolve(strict=True)
    if destination.is_symlink():
        raise ValueError("Refusing a linked staging destination")
    destination = destination.resolve()
    framework_payload(destination)
    library = binary_directory / "libEnCAPTranscription.dylib"
    if not library.is_file() or library.is_symlink():
        raise ValueError("Built libEnCAPTranscription.dylib is missing or linked")
    resources = sorted(binary_directory.glob("*.bundle"))
    if not any(p.name == "models.json" for bundle in resources for p in bundle.rglob("models.json")):
        raise ValueError("Shared AVID catalog resource is missing; do not ship this linked module")
    if not any(p.suffix == ".metallib" for bundle in resources for p in bundle.rglob("*.metallib")):
        raise ValueError("MLX Metal resources are missing; use the swiftbuild build system")
    for resource in resources:
        if resource.is_symlink() or any(p.is_symlink() for p in resource.rglob("*")):
            raise ValueError("Linked Swift resource path is not an owned build product")
    metadata_destination = destination.parent / "EnCAPTranscription-metadata"
    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = metadata_destination / "encap-transcription-resources.json"
    if (destination.exists() or metadata_destination.exists()) and not marker.is_file():
        raise ValueError("Refusing to replace an unowned staging directory")
    if marker.is_file() and json.loads(marker.read_text()).get("scope") != "encap_linked_transcription_staging":
        raise ValueError("Refusing to replace an unowned staging directory")
    with tempfile.TemporaryDirectory(prefix=".encap-avid-stage-", dir=destination.parent) as temporary:
        temporary = Path(temporary)
        framework = temporary / "EnCAPTranscription.framework"
        payload = framework_payload(framework)
        resource_root = payload / "Resources"
        resource_root.mkdir(parents=True)
        executable = payload / "EnCAPTranscription"
        shutil.copy2(library, executable)
        for resource in resources:
            shutil.copytree(resource, resource_root / resource.name)
        if checkouts is not None and resolved is not None:
            stage_licenses(checkouts, resolved, resource_root / "AVIDTranscriptionLicenses")
        (resource_root / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "EnCAPTranscription", "CFBundleIdentifier": "com.tlolabs.encap.transcription",
            "CFBundleName": "EnCAPTranscription", "CFBundlePackageType": "FMWK", "CFBundleVersion": "2.0.13",
            "CFBundleShortVersionString": "2.0.13", "CFBundleSupportedPlatforms": ["MacOSX"], "LSMinimumSystemVersion": "14.0"}))
        runtime = relocate_module(executable, payload)
        for bundle in sorted(resource_root.glob("*.bundle")):
            subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True)
        (framework / "Versions/Current").symlink_to("A")
        for name in ("EnCAPTranscription", "Resources", "Frameworks"):
            (framework / name).symlink_to("Versions/Current/" + name)
        metadata = temporary / "EnCAPTranscription-metadata"
        metadata.mkdir()
        report = {"schema": 1, "scope": "encap_linked_transcription_staging", "layout": "macos-versioned-framework-v1",
            "platform": "macos-arm64", "minimum_macos": "14.0", "model_weights_bundled": False, "abi_version": 1, "schema_version": 1,
            "source_commit": "dd112d497b68df6786f49a71b3611f7f32f090e9",
            "snapshot_sha256": "76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3",
            "source_manifest_sha256": "7dcb2311c335a8b06fb91e160ee8441337a02ddb17b8b03fb14c1f3a0f110a27",
            "swift_runtime": runtime,
            "library_code_sha256": {p.relative_to(payload).as_posix(): code_identity(p) for p in [executable, *sorted((payload / "Frameworks").glob("*.dylib"))]},
            "files": [{"path": p.relative_to(payload).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "size": p.stat().st_size}
                      for p in sorted(payload.rglob("*")) if p.is_file()]}
        (metadata / "encap-transcription-resources.json").write_text(json.dumps(report, indent=2) + "\n")
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(framework)], check=True)
        bind_signature(framework, metadata)
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(framework)], check=True)
        environment = dict(os.environ, PATH="")
        for key in ("DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "PACKAGE_RESOURCE_BUNDLE_PATH", "PACKAGE_RESOURCE_BUNDLE_URL"):
            environment.pop(key, None)
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe-library", str(executable)], check=True,
                       stdout=subprocess.DEVNULL, env=environment)
        previous = []
        try:
            for final in (destination, metadata_destination):
                if final.exists():
                    backup = temporary / ("previous-" + final.name)
                    final.rename(backup); previous.append((final, backup))
            framework.rename(destination)
            metadata.rename(metadata_destination)
        except BaseException:
            for final, backup in reversed(previous):
                if final.exists():
                    shutil.rmtree(final)
                backup.rename(final)
            raise
    return report


def bind_signature(directory: Path, metadata_directory=None):
    """Bind signed code externally so the framework resource seal stays intact."""
    payload = framework_payload(directory)
    metadata_directory = Path(metadata_directory) if metadata_directory else directory.parent / "EnCAPTranscription-metadata"
    receipt_path = metadata_directory / "encap-transcription-resources.json"
    original = receipt_path.read_bytes()
    report = json.loads(original)
    if report.get("schema") != 1 or report.get("layout") != "macos-versioned-framework-v1":
        raise ValueError("Unexpected transcription build receipt")
    expected = {entry["path"]: entry for entry in report["files"]}
    actual = {p.relative_to(payload).as_posix(): p for p in payload.rglob("*") if p.is_file()}
    code_paths = set(report["library_code_sha256"])
    def signable(name):
        return name in code_paths or "_CodeSignature" in Path(name).parts
    for name, path in actual.items():
        if path.is_symlink() or not path.resolve().is_relative_to(payload.resolve()):
            raise ValueError("Linked or escaping transcription payload")
        if name not in expected and not signable(name):
            raise ValueError("Unexpected transcription file during signature binding: " + name)
        if not signable(name) and (hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]["sha256"] or path.stat().st_size != expected[name]["size"]):
            raise ValueError("Transcription resource changed while signing: " + name)
    if set(expected) - set(actual):
        raise ValueError("Transcription resource removed while signing")
    for name, expected_code in report["library_code_sha256"].items():
        if name not in actual or code_identity(actual[name]) != expected_code:
            raise ValueError("Transcription code differs from the source build: " + name)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(actual[name])], check=True)
    signed = {"schema": 1, "original_receipt_sha256": hashlib.sha256(original).hexdigest(),
              "library_code_sha256": report["library_code_sha256"],
              "files": {name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
                        for name, path in sorted(actual.items()) if signable(name)}}
    (metadata_directory / "encap-transcription-signed.json").write_text(json.dumps(signed, indent=2) + "\n")
    return signed


def probe_library(path: Path):
    """Read-only native module/resource smoke; no model download or inference."""
    import ctypes
    library = ctypes.CDLL(str(path.resolve(strict=True)))
    library.encap_transcription_abi_version.restype = ctypes.c_uint32
    if library.encap_transcription_abi_version() != 1:
        raise ValueError("Unsupported linked transcription ABI")
    library.encap_transcription_token_create.restype = ctypes.c_uint64
    library.encap_transcription_execute.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    library.encap_transcription_execute.restype = ctypes.c_uint64
    library.encap_transcription_result_size.argtypes = [ctypes.c_uint64]
    library.encap_transcription_result_size.restype = ctypes.c_size_t
    library.encap_transcription_result_copy.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
    library.encap_transcription_release.argtypes = [ctypes.c_uint64]
    token = library.encap_transcription_token_create()
    result = 0
    try:
        if not token:
            raise ValueError("Invalid linked transcription token")
        with tempfile.TemporaryDirectory(prefix="encap-linked-model-smoke-") as cache:
            request = json.dumps({"schema_version": 1, "arguments": ["models", "--cache", cache]}).encode()
            result = library.encap_transcription_execute(token, request, len(request), None, None)
            size = library.encap_transcription_result_size(result)
            if not result or not 0 < size <= 4 * 1024 * 1024:
                raise ValueError("Invalid linked transcription smoke result")
            buffer = ctypes.create_string_buffer(size)
            if library.encap_transcription_result_copy(result, buffer, size) != 1:
                raise ValueError("Unable to copy linked transcription smoke result")
            response = json.loads(buffer.raw)
            if response.get("schema_version") != 1 or response.get("ok") is not True:
                raise ValueError("Linked transcription smoke failed: " + str(response))
            models = response["result"]
            if len(models) != 5 or not any(model["id"] == "whisper-large-v3" for model in models):
                raise ValueError("Linked transcription shared catalog is incomplete")
    finally:
        if result:
            library.encap_transcription_release(result)
        if token:
            library.encap_transcription_release(token)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--bind-signature":
        parser = argparse.ArgumentParser()
        parser.add_argument("--bind-signature", type=Path, required=True)
        parser.add_argument("--metadata-directory", type=Path)
        args = parser.parse_args()
        bind_signature(args.bind_signature.resolve(strict=True), args.metadata_directory)
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--probe-library":
        probe_library(Path(sys.argv[2]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-directory", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--checkouts", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    args = parser.parse_args()
    stage(args.binary_directory, args.destination, args.checkouts, args.resolved)
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
