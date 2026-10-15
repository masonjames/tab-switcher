#!/usr/bin/env python3
"""Attended Local releases. Credentials stay in Keychain; no install or launch."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent.parent
REPO = "masonjames/tab-switcher"
TEAM = "J5K2J3K4H7"
HOST = "com.masonjames.tabswitcher.local"
EXTENSION_ID = "lacnibngddmnlkihkghjddjgkkppcaag"
APP = "Tab Switcher Local.app"


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def tag_version(tag):
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)-mason\.([1-9]\d*)", tag)
    require(match, "Tag must be v<appVersion>-mason.N, for example v3.7.5-mason.1")
    return match[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(stage, state):
    temporary = stage / "state.json.tmp"
    with temporary.open("w") as stream:
        stream.write(json.dumps(state, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(stage / "state.json")
    descriptor = os.open(stage, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage_path(root, tag):
    tag_version(tag)
    path = root / "dist/releases" / tag
    for parent in [path, *path.parents]:
        require(not parent.is_symlink(), f"Refusing symlink staging path: {parent}")
    return path


def acquire_lock(stage):
    stream = (stage / ".lock").open("a")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        raise ReleaseError("Another command is using this release stage; wait for it to finish.")
    return stream


def run(args, cwd, stage=None, check=True):
    args = [str(arg) for arg in args]
    if stage:
        stem = stage / "evidence" / str(uuid.uuid4())
        with (stage / "commands.jsonl").open("a") as stream:
            stream.write(json.dumps({"cwd": str(cwd), "argv": args, "evidence": stem.name}) + "\n")
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if stage:
        stem.with_suffix(".status").write_text(str(result.returncode) + "\n")
        stem.with_suffix(".stdout").write_bytes(result.stdout)
        stem.with_suffix(".stderr").write_bytes(result.stderr)
    require(not check or result.returncode == 0,
            f"Command failed ({result.returncode}): {' '.join(args)}\n"
            f"{result.stderr.decode(errors='replace')[-2000:]}\nPreserved stage: {stage}")
    return result


def output(args, cwd=ROOT, stage=None):
    return run(args, cwd, stage).stdout.decode().strip()


def identity_value(value):
    require(value and re.fullmatch(r"[A-Fa-f0-9]{40}", value),
            "Supply --identity SHA1 or TAB_SWITCHER_SIGN_IDENTITY (40 hex characters).")
    return value.upper()


def host_check():
    require(platform.system() == "Darwin" and platform.machine() == "arm64",
            "This workflow requires a native Apple Silicon macOS shell; Intel/Rosetta is unsupported.")


def clean_source(status):
    require(not status.strip(), "Source must be clean and committed, including untracked files. Commit or preserve changes first.")


def versions(source, tag):
    text = (source / "native-host/Sources/tab-switcher/main.swift").read_text()
    match = re.search(r'let APP_VERSION = "(\d+\.\d+\.\d+)"', text)
    require(match and match[1] == tag_version(tag), "Tag does not match source APP_VERSION.")
    extension = json.loads((source / "manifest.json").read_text())["version"]
    require(isinstance(extension, str) and re.fullmatch(r"\d+(?:\.\d+){0,3}", extension), "Invalid extension version.")
    return match[1], extension


def pairing(source, app, extension, state):
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    local = json.loads((extension / "manifest.json").read_text())
    key = (source / "native-host/local-extension/public-key.txt").read_text().strip()
    digest = hashlib.sha256(base64.b64decode(key, validate=True)).hexdigest()[:32]
    identifier = "".join(chr(97 + int(char, 16)) for char in digest)
    require(identifier == EXTENSION_ID and local.get("key") == key, "Extension public key/ID changed.")
    require(info.get("CFBundleIdentifier") == HOST and info.get("TabSwitcherLocalBuild") is True
            and info.get("TabSwitcherLocalExtensionID") == EXTENSION_ID, "App/extension identity mismatch.")
    require(info.get("CFBundleShortVersionString") == info.get("CFBundleVersion") == state["app_version"]
            == tag_version(state["tag"]), "Generated app version mismatch.")
    require(local.get("version") == state["extension_version"], "Extension version mismatch.")
    require(f'connectNative("{HOST}")' in (extension / "mainsw.js").read_text(), "Extension host mismatch.")
    require(info.get("SUEnableAutomaticChecks") is False and info.get("SUAutomaticallyUpdate") is False,
            "Upstream updates must be disabled.")


def verify_snapshot(stage, state):
    require(sha256(stage / "source.tar") == state["source_archive_sha256"], "Source archive changed.")
    source = stage / "source"
    expected = set()
    with tarfile.open(stage / "source.tar") as archive:
        for member in archive.getmembers():
            path = source / member.name
            require(not member.name.startswith("/") and ".." not in Path(member.name).parts, "Unsafe source archive path.")
            if member.isfile():
                expected.add(member.name)
                require(not path.is_symlink() and path.read_bytes() == archive.extractfile(member).read(), f"Snapshot source changed: {member.name}")
            elif member.issym():
                expected.add(member.name)
                require(path.is_symlink() and os.readlink(path) == member.linkname, "Snapshot symlink changed.")
    generated = {"dist", "native-host/.build-local", "native-host/.swiftpm"}
    actual = set()
    for directory, directories, files in os.walk(source):
        for name in list(directories):
            path = Path(directory) / name
            relative = path.relative_to(source).as_posix()
            if path.is_symlink():
                actual.add(relative)
                directories.remove(name)
            elif relative in generated or name == "__pycache__":
                directories.remove(name)
        actual.update((Path(directory) / name).relative_to(source).as_posix() for name in files)
    require(actual == expected, "Snapshot has additional or missing source files: " + ", ".join(sorted(actual ^ expected)))


def file_manifest(root):
    files = {}
    for path in root.rglob("*"):
        require(not path.is_symlink(), f"Unexpected extension symlink: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = sha256(path)
    return files


def zip_manifest(path):
    files = {}
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            name = entry.filename
            require(not name.startswith("/") and ".." not in Path(name).parts, "Unsafe package path.")
            if not entry.is_dir():
                require(name not in files, "Duplicate package entry: " + name)
                files[name] = hashlib.sha256(archive.read(entry)).hexdigest()
    return files


def validate_payloads(stage, state):
    uploaded = stage / "notary-upload.zip"
    require(sha256(uploaded) == state["archive_sha256"], "Submitted archive changed.")
    original = zip_manifest(uploaded)
    packaged = zip_manifest(stage / "assets" / asset_names(state)[0])
    # Stapler adds this ticket; every pre-existing app/wrapper byte must remain identical.
    ticket = "Tab Switcher Local/" + APP + "/Contents/CodeResources"
    original.pop(ticket, None)
    packaged.pop(ticket, None)
    require(packaged == original, "Final app payload differs from the notarized upload.")
    expected = {"extension-local/" + name: digest for name, digest in state["extension_files"].items()}
    require(zip_manifest(stage / "assets" / asset_names(state)[1]) == expected,
            "Final extension payload differs from the tested build.")


def components(app):
    framework = app / "Contents/Frameworks/Sparkle.framework"
    base = framework / "Versions/B"
    return [base / "XPCServices/Downloader.xpc", base / "XPCServices/Installer.xpc",
            base / "Autoupdate", base / "Updater.app", framework, app]


def verify_app(app, stage, identity):
    for component in components(app):
        run(["codesign", "--verify", "--strict", component], stage, stage)
        detail = run(["codesign", "-d", "--verbose=4", component], stage, stage).stderr.decode()
        require(f"TeamIdentifier={TEAM}" in detail and "Authority=Developer ID Application:" in detail
                and "Timestamp=" in detail and "runtime" in detail, f"Missing Developer ID/team/runtime/timestamp: {component}")
        certificate = stage / "evidence" / ("cert-" + str(uuid.uuid4()) + "-")
        run(["codesign", "-d", f"--extract-certificates={certificate}", component], stage, stage)
        require(hashlib.sha1(Path(str(certificate) + "0").read_bytes()).hexdigest().upper() == identity,
                f"Unexpected signing certificate: {component}")
    # Check every Mach-O, including embedded helpers. Universal Sparkle is fine; Intel-only is not.
    binaries = 0
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink() and "Mach-O" in output(["file", "-b", path], stage, stage):
            binaries += 1
            require("arm64" in output(["lipo", "-archs", path], stage, stage).split(), f"No arm64 slice: {path}")
    require(binaries > 0, "No Mach-O binaries found.")
    require(output(["lipo", "-archs", app / "Contents/MacOS/tab-switcher"], stage, stage) == "arm64",
            "App executable must be arm64 only.")


def zip_parent(source, destination, stage):
    require(not destination.exists(), f"Archive already exists: {destination}; inspect preserved stage.")
    run(["ditto", "-c", "-k", "--keepParent", "--norsrc", "--noextattr", source, destination], stage, stage)


INSTALL = """Tab Switcher Local (Apple Silicon, macOS 14 or later)

Extract the app ZIP and move Tab Switcher Local.app to Applications. Keep the
LICENSE.txt and Sparkle-LICENSE.txt with your copy. Disable the original Tab
Switcher extension in every browser/profile and quit its original companion.
Open Local normally, grant Accessibility when prompted, and enable your browser
in Local settings. Local updates can require removing/regranting Accessibility.

Extract the paired extension ZIP to a permanent folder. In your Chromium
browser's extensions page, enable Developer mode, choose Load unpacked, and
select extension-local (the folder containing manifest.json). For an existing
Local extension, retain/update its permanent directory and reload it. The public
key preserves ID lacnibngddmnlkihkghjddjgkkppcaag. The native host is
com.masonjames.tabswitcher.local. First launch and browser/Accessibility setup
are attended steps; packaging checks do not prove physical keyboard/UI behavior.
Upstream automatic app updates are disabled; install future Local releases manually.
"""


def build_and_sign(stage, state):
    source = stage / "source"
    run(["bash", "native-host/build-local.sh"], source, stage)
    cache = source / "native-host/.build-local"
    env_args = ["env", f"TMPDIR={cache / 'tmp'}", f"CLANG_MODULE_CACHE_PATH={cache / 'module-cache'}"]
    run([*env_args, "swift", "test", "--package-path", source / "native-host", "--disable-sandbox",
         "--force-resolved-versions", "--cache-path", cache / "cache", "--scratch-path", cache,
         "-Xswiftc", "-module-cache-path", "-Xswiftc", cache / "module-cache"], source, stage)
    run(["bun", "test", "tests"], source, stage)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_release_local.py"], source, stage)
    verify_snapshot(stage, state)
    wrapper = stage / "Tab Switcher Local"
    wrapper.mkdir(exist_ok=True)
    app = wrapper / APP
    run(["ditto", source / "dist" / APP, app], stage, stage)
    extension = source / "dist/extension-local"
    pairing(source, app, extension, state)
    shutil.copyfile(source / "LICENSE", wrapper / "LICENSE.txt")
    pin = next(p for p in json.loads((source / "native-host/Package.resolved").read_text())["pins"] if p["identity"] == "sparkle")
    checkout = cache / "checkouts/Sparkle"
    require(output(["git", "rev-parse", "HEAD"], checkout, stage) == pin["state"]["revision"], "Sparkle license checkout does not match pin.")
    shutil.copyfile(checkout / "LICENSE", wrapper / "Sparkle-LICENSE.txt")
    (wrapper / "INSTALL.md").write_text(INSTALL)
    shutil.copyfile(source / "LICENSE", extension / "LICENSE.txt")
    available = output(["security", "find-identity", "-v", "-p", "codesigning"], stage, stage)
    require(any(state["identity"] in line and '"Developer ID Application:' in line
                and f"({TEAM})" in line for line in available.splitlines()), "Identity must be a valid Developer ID Application for team " + TEAM)
    for component in components(app):
        run(["codesign", "--force", "--sign", state["identity"], "--options", "runtime", "--timestamp", component], stage, stage)
    verify_app(app, stage, state["identity"])
    archive = stage / "notary-upload.zip"
    zip_parent(wrapper, archive, stage)
    state.update(phase="signed", archive_sha256=sha256(archive), sparkle=pin,
                 extension_files=file_manifest(extension))
    save(stage, state)


def validate_accepted(log, state, submission_id):
    require(log.get("jobId", "").lower() == submission_id.lower() and log.get("status") == "Accepted"
            and log.get("sha256", "").lower() == state["archive_sha256"],
            "Notarization log must be Accepted and match both submission ID and submitted archive sha256. Do not use another submission.")


def submit(stage, state):
    require(state["phase"] == "signed", "Upload intent already exists. Reconcile via notarytool history and resume --submission-id UUID; never resubmit blindly.")
    require(sha256(stage / "notary-upload.zip") == state["archive_sha256"], "Submitted archive changed.")
    state["phase"] = "submission-intent"
    save(stage, state)  # Durable before any service request, including ambiguous failures.
    response = run(["xcrun", "notarytool", "submit", stage / "notary-upload.zip", "--no-wait",
                    "--keychain-profile", state["profile"], "--output-format", "json"], stage, stage, check=False)
    (stage / "submission-response.json").write_bytes(response.stdout)
    (stage / "submission-response.stderr").write_bytes(response.stderr)
    require(response.returncode == 0, "Upload outcome ambiguous. Use notarytool history; resume with --submission-id UUID. No automatic resubmission.")
    data = json.loads(response.stdout)
    state.update(submission_id=str(uuid.UUID(data["id"])), phase="submitted")
    save(stage, state)


def asset_names(state):
    return [f"Tab-Switcher-Local-{state['tag']}-macos-arm64.zip",
            f"Tab-Switcher-Local-{state['tag']}-extension.zip", "INSTALL.md", "SHA256SUMS.txt"]


def validate_assets(stage, state):
    names = asset_names(state)
    require(state.get("phase") == "ready" and set(state.get("assets", {})) == set(names), "Stage is not ready or asset manifest is incomplete.")
    require(set(p.name for p in (stage / "assets").iterdir()) == set(names), "Unexpected release assets.")
    for name, record in state["assets"].items():
        path = stage / "assets" / name
        require(path.is_file() and not path.is_symlink() and sha256(path) == record["sha256"]
                and path.stat().st_size == record["size"], f"Asset changed: {name}; publication refused.")


def extracted_check(stage, state, archive):
    destination = stage / "evidence" / ("extract-" + str(uuid.uuid4()))
    destination.mkdir()
    run(["ditto", "-x", "-k", archive, destination], stage, stage)
    app = destination / "Tab Switcher Local" / APP
    verify_app(app, stage, state["identity"])
    run(["xcrun", "stapler", "validate", app], stage, stage)
    run(["spctl", "--assess", "--type", "execute", "--verbose=4", app], stage, stage)
    return app


def package_check(stage, state):
    validate_payloads(stage, state)
    assets = stage / "assets"
    app = extracted_check(stage, state, assets / asset_names(state)[0])
    destination = stage / "evidence" / ("extension-" + str(uuid.uuid4()))
    destination.mkdir()
    run(["ditto", "-x", "-k", assets / asset_names(state)[1], destination], stage, stage)
    extension = destination / "extension-local"
    pairing(stage / "source", app, extension, state)
    expected = stage / "source/dist/extension-local"
    def contents(directory):
        return {str(path.relative_to(directory)): sha256(path) for path in directory.rglob("*") if path.is_file()}
    require(contents(extension) == contents(expected), "Extracted extension does not match verified build.")
    for license_path in [app.parent / "LICENSE.txt", destination / "extension-local/LICENSE.txt"]:
        require(license_path.read_bytes() == (stage / "source/LICENSE").read_bytes(), "Missing/changed project license.")
    require((app.parent / "Sparkle-LICENSE.txt").read_bytes() ==
            (stage / "source/native-host/.build-local/checkouts/Sparkle/LICENSE").read_bytes(), "Sparkle license changed.")
    require((app.parent / "INSTALL.md").read_text() == INSTALL, "Packaged installation guide changed.")


def finish(stage, state, submission_id, wait_seconds):
    require(sha256(stage / "notary-upload.zip") == state["archive_sha256"], "Submitted archive changed.")
    if submission_id:
        require(not state.get("submission_id") or state["submission_id"] == submission_id, "Submission ID conflicts with recorded upload.")
    identifier = submission_id or state.get("submission_id")
    require(identifier, "Submission outcome unknown. Run notarytool history --keychain-profile PROFILE, then resume --submission-id UUID. No resubmission will occur.")
    run(["xcrun", "notarytool", "wait", identifier, "--timeout", str(wait_seconds) + "s",
         "--keychain-profile", state["profile"], "--output-format", "json"], stage, stage)
    raw = run(["xcrun", "notarytool", "log", identifier, "--keychain-profile", state["profile"]], stage, stage).stdout
    (stage / "notarization-log.json").write_bytes(raw)
    validate_accepted(json.loads(raw), state, identifier)
    state.update(submission_id=identifier, phase="accepted")
    save(stage, state)
    app = stage / "Tab Switcher Local" / APP
    run(["xcrun", "stapler", "staple", app], stage, stage)
    run(["xcrun", "stapler", "validate", app], stage, stage)
    assets = stage / "assets"
    assets.mkdir(exist_ok=True)
    names = asset_names(state)
    # Retry after partial packaging only if existing ZIP passes extraction checks below.
    if not (assets / names[0]).exists():
        zip_parent(app.parent, assets / names[0], stage)
    if not (assets / names[1]).exists():
        zip_parent(stage / "source/dist/extension-local", assets / names[1], stage)
    package_check(stage, state)
    (assets / "INSTALL.md").write_text(INSTALL)
    (assets / "SHA256SUMS.txt").write_text("".join(f"{sha256(assets / name)}  {name}\n" for name in names[:-1]))
    state.update(phase="ready", assets={name: {"sha256": sha256(assets / name), "size": (assets / name).stat().st_size} for name in names})
    save(stage, state)
    print(f"Locally validated: {assets}. Review state.json and evidence; publish is separate.")


def api(stage, endpoint, method="GET", data=None):
    args = ["gh", "api", f"repos/{REPO}/{endpoint}", "--method", method]
    if data is None:
        return json.loads(output(args, stage, stage))
    packet = stage / "evidence" / (str(uuid.uuid4()) + ".json")
    packet.write_text(json.dumps(data))
    return json.loads(output([*args, "--input", packet], stage, stage))


def remote_tag(stage, tag):
    result = run(["gh", "api", f"repos/{REPO}/git/ref/tags/{tag}"], stage, stage, check=False)
    if result.returncode:
        require(b"404" in result.stderr, "Cannot inspect remote tag; check gh auth/network.")
        return None
    obj = json.loads(result.stdout)["object"]
    for _ in range(8):
        if obj["type"] == "commit":
            return obj["sha"]
        require(obj["type"] == "tag", "Unexpected remote tag type.")
        obj = api(stage, "git/tags/" + obj["sha"])["object"]
    raise ReleaseError("Remote tag nesting exceeds limit.")


def validate_remote_source(source_sha, remote_commit, tag_sha):
    require(remote_commit == source_sha, "Source commit is not available in fork.")
    require(tag_sha in (None, source_sha), "Remote tag points to a different source commit.")


def validate_draft(release, state, marker):
    require(release["draft"], "Release is already published. Refusing all mutations; inspect remote release manually.")
    require(release["tag_name"] == state["tag"] and release["target_commitish"] == state["source_sha"]
            and release.get("body") == marker and not release.get("prerelease"), "Existing draft/source does not match this stage. Refusing mutation.")


def publish(stage, state):
    validate_assets(stage, state)  # Must happen before any network/mutation.
    validate_accepted(json.loads((stage / "notarization-log.json").read_text()), state, state["submission_id"])
    package_check(stage, state)
    validate_remote_source(state["source_sha"], api(stage, "commits/" + state["source_sha"])["sha"], remote_tag(stage, state["tag"]))
    marker = (f"Tab Switcher Local {state['tag']} — signed and notarized\n\n"
              f"Source: {state['source_sha']}\nApp: {state['app_version']}; extension: {state['extension_version']}\n\n"
              "Download both ZIPs: macos-arm64 contains the app; extension contains the paired Chrome extension. "
              "See INSTALL.md for setup and SHA256SUMS.txt for checksums. Apple Silicon, macOS 14+.\n\n"
              "Apple notarization accepted; ticket stapled; extracted package passed Gatekeeper. "
              "Normal first-open confirmation, Accessibility permission and unpacked-extension setup still apply. "
              "Physical shortcut and login behavior require attended testing.")
    result = run(["gh", "api", f"repos/{REPO}/releases/tags/{state['tag']}"], stage, stage, check=False)
    if result.returncode == 0:
        release = json.loads(result.stdout)
        validate_draft(release, state, marker)
    else:
        require(b"404" in result.stderr, "Cannot inspect remote release; check gh auth/network.")
        release = api(stage, "releases", "POST", {"tag_name": state["tag"], "target_commitish": state["source_sha"], "name": state["tag"], "body": marker, "draft": True, "prerelease": False})
        validate_draft(release, state, marker)
    require(remote_tag(stage, state["tag"]) in (None, state["source_sha"]), "Remote tag changed.")
    remote_assets = api(stage, f"releases/{release['id']}/assets?per_page=100")
    require(len(remote_assets) <= len(state["assets"]) and len({a["name"] for a in remote_assets}) == len(remote_assets)
            and all(a["name"] in state["assets"] for a in remote_assets), "Unexpected/duplicate draft assets; reconcile manually.")
    for name in state["assets"]:
        if name not in {a["name"] for a in remote_assets}:
            run(["gh", "release", "upload", state["tag"], stage / "assets" / name, "--repo", REPO], stage, stage)
    # Always download and hash; works with GitHub instances lacking asset digest.
    downloaded = stage / "evidence" / ("remote-" + str(uuid.uuid4()))
    downloaded.mkdir()
    run(["gh", "release", "download", state["tag"], "--repo", REPO, "--dir", downloaded], stage, stage)
    require(set(p.name for p in downloaded.iterdir()) == set(state["assets"]), "Remote asset set mismatch; draft preserved.")
    for name, record in state["assets"].items():
        require(sha256(downloaded / name) == record["sha256"] and (downloaded / name).stat().st_size == record["size"], f"Remote asset mismatch: {name}; draft preserved, do not clobber.")
    validate_assets(stage, state)
    validate_draft(api(stage, f"releases/{release['id']}"), state, marker)
    require(remote_tag(stage, state["tag"]) in (None, state["source_sha"]), "Remote tag changed before publication.")
    api(stage, f"releases/{release['id']}", "PATCH", {"draft": False, "make_latest": "true"})
    final = api(stage, f"releases/{release['id']}")
    require(not final["draft"] and final["tag_name"] == state["tag"] and remote_tag(stage, state["tag"]) == state["source_sha"]
            and api(stage, "releases/latest")["id"] == release["id"], "Final release/tag/latest verification failed; inspect GitHub before any retry.")
    state["published_url"] = final["html_url"]
    save(stage, state)
    print(final["html_url"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Snapshot, verify, sign, submit, and wait (never publish)")
    prepare.add_argument("tag")
    prepare.add_argument("--identity", default=os.environ.get("TAB_SWITCHER_SIGN_IDENTITY"))
    prepare.add_argument("--profile", default="TabSwitcher")
    prepare.add_argument("--wait-seconds", type=int, default=60)
    resume = commands.add_parser("resume", help="Resume recorded stage; ambiguous uploads require reconciliation")
    resume.add_argument("tag")
    resume.add_argument("--submission-id", type=str)
    resume.add_argument("--wait-seconds", type=int, default=60)
    commands.add_parser("publish", help="Validate and publish to masonjames/tab-switcher as latest").add_argument("tag")
    args = parser.parse_args(argv)
    lock = None
    try:
        stage = stage_path(ROOT, args.tag)
        if hasattr(args, "wait_seconds"):
            require(1 <= args.wait_seconds <= 60, "--wait-seconds must be between 1 and 60; resume again if pending.")
        identifier = str(uuid.UUID(args.submission_id)) if getattr(args, "submission_id", None) else None
        host_check()
        if args.command == "prepare":
            identity = identity_value(args.identity)
            require(args.profile and not args.profile.startswith("-"), "Invalid Keychain profile.")
            clean_source(output(["git", "status", "--porcelain", "--untracked-files=all"]))
            require(not stage.exists(), f"Stage already exists: {stage}. Use resume; never overwrite.")
            app_version, extension_version = versions(ROOT, args.tag)
            source_sha = output(["git", "rev-parse", "HEAD"])
            stage.mkdir(parents=True)
            lock = acquire_lock(stage)
            (stage / "evidence").mkdir()
            state = dict(schema=1, tag=args.tag, source_sha=source_sha, app_version=app_version,
                         extension_version=extension_version, identity=identity, team=TEAM, profile=args.profile, phase="preparing")
            save(stage, state)
            archive = stage / "source.tar"
            run(["git", "archive", "--format=tar", "--output", archive, source_sha], ROOT, stage)
            state["source_archive_sha256"] = sha256(archive)
            save(stage, state)
            (stage / "source").mkdir()
            run(["tar", "-xf", archive, "-C", stage / "source"], stage, stage)
            require(versions(stage / "source", args.tag) == (app_version, extension_version), "Snapshot version mismatch.")
        else:
            lock = acquire_lock(stage)
            state = json.loads((stage / "state.json").read_text())
            require(state.get("schema") == 1 and state.get("tag") == args.tag and state.get("team") == TEAM
                    and re.fullmatch(r"[0-9a-f]{40}", state.get("source_sha", "")), "Invalid release state.")
            identity_value(state["identity"])
            require(versions(stage / "source", args.tag) == (state["app_version"], state["extension_version"]), "Snapshot version changed.")
        require(state["phase"] in {"preparing", "signed", "submission-intent", "submitted", "accepted", "ready"}, "Unknown release phase.")
        require(not identifier or state["phase"] in {"submission-intent", "submitted", "accepted"}, "--submission-id is only for an upload already attempted.")
        for directory in ["source", "evidence", "assets", "Tab Switcher Local"]:
            require(not (stage / directory).is_symlink(), "Refusing symlink stage directory: " + directory)
        verify_snapshot(stage, state)
        if args.command == "publish":
            publish(stage, state)
        elif state["phase"] == "ready":
            validate_assets(stage, state)
            print(f"Already locally validated: {stage / 'assets'}; publish remains explicit.")
        else:
            if state["phase"] == "preparing":
                require(not (stage / "notary-upload.zip").exists(), "Partial build/sign archive exists; inspect stage, preserve it and prepare a new tag if necessary.")
                build_and_sign(stage, state)
            if state["phase"] == "signed":
                submit(stage, state)
            finish(stage, state, identifier, args.wait_seconds)
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, StopIteration, TypeError, zipfile.BadZipFile) as error:
        print(f"Release stopped: {error}\nWork is preserved. Inspect state/evidence and use resume; do not delete or resubmit blindly.", file=sys.stderr)
        return 1
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
