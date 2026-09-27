---
name: align-upstream
description: Align ok-ww-automator with updated ok-wuthering-waves and ok-script APIs, diagnose upstream compatibility failures, and maintain the upstream doctor contracts. Use for this repository's upstream upgrades or regressions.
---

# Align Automator with upstream

Work in `ok-ww-automator`; keep sibling upstream checkouts unchanged unless the user specifically requests an update. Read `AGENTS.md` and [maintenance.md](../../../docs/maintenance.md). Use the shared parent `.venv`, never create an environment inside the project.

Establish what is actually running: record sibling Git revisions, upstream's `requirements.txt` pin, and `ok-script`'s installed version/path in the shared interpreter. The sibling `ok-script` checkout is a review source; it is not necessarily the installed package. Verify the latest remote default-branch HEAD using `git ls-remote <url> HEAD`; do not call an old local checkout “latest.” Preserve local edits and commits; never use `reset --hard` to update.

Run the doctor before changing code:

```powershell
..\.venv\Scripts\python.exe -m ok_ww_automator.doctor --check-remote --strict
..\.venv\Scripts\python.exe -m ok_ww_automator.doctor --source-only --ok-script-root ..\ok-script --strict
```

On non-Windows hosts use `PYTHONPATH=src python3 -m ok_ww_automator.doctor --source-only --ok-script-root ../ok-script`. This verifies source only, not the Windows installation.

The contract inventory is `src/ok_ww_automator/upstream_contracts.json`. `FAIL` identifies missing APIs or incompatible call/configuration shapes; `WARN` requests a review of changed behavior or unverified remote state. `MANUAL` identifies assumptions a source scan cannot prove. Inspect the actual upstream implementation and the consuming adapter before changing either. Fingerprints are review prompts, not compatibility proofs: never bulk-refresh them merely to make the doctor green. Update a baseline hash/revision only after reviewing its diff and adapting consumers as needed. Preserve a meaningful reason for every fragile assumption and add new dependencies to the inventory.

Prefer removing coupling or using public APIs to adding version gates, monkey patches, or new upstream imports. Preserve these boundaries:

- One OK runtime per child process; keep upstream cwd and import context active while driving it. Globals, named mutexes, relative configs and asset paths make account reuse unsafe.
- Scheduler owns shutdown and process cleanup. Persisted GUI “Exit After Task” settings must not interrupt headless measurement/reporting.
- Task completion, translated errors and Garden completion logs refer to the current attempt. Missing OCR or payloads are not successful measurements.
- Timeouts must cover native startup/teardown and stop the child process tree. Never retry a five-to-one merge when submission may already have succeeded.
- Live integrations and game UI checks are separate from offline source compatibility; report them unverified if they were not exercised. Do not launch the game, spend stamina, submit merges, or send messages merely to validate an upgrade without authorization for those effects.

Keep tests that reproduce wrong decisions, data loss, unsafe retries, false success, lost diagnostics, and broken process isolation. Remove assertions of incidental call order, source text, repeated defaults, or trivial dataclass storage when they protect no meaningful contract. Run `python -m unittest discover -s tests` using the shared Python. Request an independent agent review of changed adapters and doctor coverage when available.

If launcher code or its bundled external contracts change, follow the local build and offscreen smoke procedure in maintenance.md. Source-only task changes generally do not require rebuilding. Commit coherent fixes with their regressions. Push commits or a release tag only within the user's requested scope; never move an existing tag. Report exact reviewed revisions, validation performed, unresolved manual checks, and whether a launcher rebuild was necessary.
