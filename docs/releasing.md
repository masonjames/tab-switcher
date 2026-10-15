# Mason's signed Local releases

`native-host/release-local.py` is an attended Apple Silicon workflow for
**masonjames/tab-switcher** only. It never installs or launches the app. Prepare
and resume can sign and contact Apple's notary service; only `publish` contacts
GitHub and publishes a release. Run commands from the repository root on native
arm64 macOS with Xcode command-line tools, Python 3.9+, Bun and `gh` available.
SwiftPM needs network access for the exact Sparkle pin. No npm/yarn is needed.

## One-time operator setup

Use the existing 1Password Personal item titled
**Tab Switcher Local — Apple signing and notarization** for the account reference.
The signing private key stays in Keychain. Do not export it or put credentials
in source, release state, shell arguments, environment variables, or logs.
The SHA1 signing identifier is public certificate metadata, not a credential.

Use a **Developer ID Application** identity for team **J5K2J3K4H7**. Discover its
current SHA1 each year (do not copy an old fingerprint):

```sh
security find-identity -v -p codesigning
```

Use the Developer ID Application **G2** chain for new certificates. If the
intermediate is missing, obtain **Developer ID - G2** from [Apple PKI](https://www.apple.com/certificateauthority/)
and import that public intermediate into Keychain using default/system trust;
do not set Always Trust to mask a broken chain. See Apple's [Developer ID
intermediate guidance](https://developer.apple.com/support/developer-id-intermediate-certificate/).
A valid identity needs both the certificate and its private key in Keychain.

Configure the notary profile interactively in a normal terminal:

```sh
xcrun notarytool store-credentials TabSwitcher
```

Follow its prompts for account, team J5K2J3K4H7 and app-specific password.
Do not use `--password`, shell substitution from 1Password, or environment
variables for secrets. The CLI subsequently uses only `--keychain-profile`.
Use existing `gh` authentication; `gh auth status` should show access to the fork.
This document does not authorize certificate/account/credential changes.

## Version and prepare

App and extension versions are independent: currently app **3.7.5** and extension
**3.7.4**. For an app bump, update `APP_VERSION` in
`native-host/Sources/tab-switcher/main.swift` and both app version fields in
`native-host/build-local.sh`. Change `manifest.json` only when an extension bump
is intended. Preserve the checked-in Local public key. The paired ID must remain
`lacnibngddmnlkihkghjddjgkkppcaag`, host `com.masonjames.tabswitcher.local`.

Commit reviewed source changes before preparing (including this workflow).
The checkout must have no tracked changes or untracked files. Choose the next
unused `v<appVersion>-mason.N` tag. The examples use `v3.7.5-mason.4`; choose a
new tag for later source changes. No local Git tag is required.

```sh
python3 native-host/release-local.py --help
python3 -m unittest discover -s tests -p 'test_release_local.py' -v
python3 native-host/release-local.py prepare v3.7.5-mason.4 --identity YOUR_CURRENT_40_HEX_SHA1
```

Alternatively set `TAB_SWITCHER_SIGN_IDENTITY` to that public SHA1. Optional
`--profile NAME` defaults to `TabSwitcher`; `--wait-seconds 1..60` defaults to 60.
Intel hosts and Rosetta shells are rejected before staging.

Prepare creates ignored `dist/releases/TAG/` and refuses an existing stage. It
archives the exact committed HEAD into `source.tar`, extracts `source/`, and runs
`bash native-host/build-local.sh`, `swift test`, `bun test tests`, and the Python release tests there, with
snapshot-local Swift caches. It leaves root `dist/extension-local` (potentially
live in Chrome), root app output and installed applications untouched.

The app wrapper contains the app, project `LICENSE.txt`, the license from the
Sparkle checkout matching `Package.resolved`, and `INSTALL.md`. The extension
ZIP includes the project license. The six signing targets are Downloader.xpc,
Installer.xpc, Autoupdate, Updater.app, Sparkle.framework and the app, in that
order, using the explicit SHA1, hardened runtime and secure timestamp. No
upstream entitlement file is applied. Each signature, leaf certificate SHA1,
team, timestamp, runtime and Mach-O arm64 compatibility is checked.

## Resume and review

```sh
python3 native-host/release-local.py resume v3.7.5-mason.4
cat dist/releases/v3.7.5-mason.4/state.json
cat dist/releases/v3.7.5-mason.4/notarization-log.json
cat dist/releases/v3.7.5-mason.4/assets/SHA256SUMS.txt
```

Each wait is at most 60 seconds; a timeout leaves Apple's job running. Resume
again later. Upload intent and the SHA256 of `notary-upload.zip` are persisted
**before** submission. Raw submit JSON/stderr and command output are retained.
A failed/interrupted upload may already have reached Apple. The workflow never
automatically submits again after intent is recorded. Reconcile with:

```sh
xcrun notarytool history --keychain-profile TabSwitcher --output-format json
xcrun notarytool info SUBMISSION_UUID --keychain-profile TabSwitcher --output-format json
xcrun notarytool log SUBMISSION_UUID --keychain-profile TabSwitcher
python3 native-host/release-local.py resume v3.7.5-mason.4 --submission-id SUBMISSION_UUID
```

Use the profile chosen at prepare if customized. A supplied or recovered ID is
accepted only when Apple's completed log has the matching job ID, status
`Accepted` and the exact uploaded archive `sha256`. Name/time alone is not proof.
If history cannot reconcile an ambiguous upload, stop for manual investigation;
do not edit state to force a retry. Invalid notarization needs investigation and
a new committed fix/tag. Failed stages are preserved. An interrupted initial
archive extraction or partial signing archive may require a new tag/stage;
there is no automatic destructive reset.

Ready means Accepted, stapled, then repackaged with
`ditto -c -k --keepParent --norsrc --noextattr`. The final ZIP is extracted into a
fresh evidence directory and checked for signatures, ticket, Gatekeeper,
architecture, licenses and extension pairing. `assets/` contains exactly the
versioned macos-arm64 app ZIP, paired extension ZIP, `INSTALL.md`, and
`SHA256SUMS.txt` (hashes of the other three assets). `state.json` records hash and
size for all four assets, original source SHA, source archive hash, versions,
identity, Sparkle pin and submission ID. `commands.jsonl` and `evidence/` stay
outside assets. Source inventories reject added inputs outside the known build/cache directories.
Final app contents must match the notarized upload byte-for-byte except for the
stapled ticket; extension contents must match the file hashes captured before
submission. Do not modify staged source, wrapper or assets.

The generated installation guide describes normal first launch, Accessibility,
permanent unpacked extension placement and possible Accessibility regranting
after updates. These packaging checks do **not** establish physical keyboard,
login, browser, clipboard or UI behavior. Perform attended acceptance separately.

## Explicit publication

Review the state, evidence and installation instructions first. Then:

```sh
python3 native-host/release-local.py publish v3.7.5-mason.4
```

Publication rechecks local hashes, source snapshot, Accepted log and extracted
packages before using `gh`. The recorded source commit must exist remotely in
`masonjames/tab-switcher`; push reviewed source separately if necessary. An
existing remote tag, including an annotated tag, must resolve to that exact SHA.
The command creates a draft targeted at that SHA, or reconciles an existing
draft only when tag, target SHA and generated description match exactly. It
uploads missing assets without clobbering, downloads every asset into evidence,
and checks all hashes and sizes before publishing as latest. It then verifies
the final release, remote tag and latest release ID.

After a failed upload, rerun the same publish command: a matching draft can be
resumed. A wrong existing asset, unrelated/edited draft, conflicting tag or
published release is refused; inspect it manually, never blindly overwrite.
If publication itself returned ambiguously, inspect GitHub first. A published
release is immutable to this workflow, including reruns; it will refuse further
mutations. Prepare/resume never publish.

Offline Python tests simulate dangerous service paths only. They use no network
and do not prove real signing, notary acceptance, GitHub publication or UI behavior.
