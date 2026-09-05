# TranscreveAI Agent Instructions

This file mirrors `AGENTS.md` for Claude Code and Claude-compatible IDE integrations.

## Required Nested Usage

- Whenever an agent uses TranscreveAI, treat the execution as a nested workflow: keep `run_id`, `out`, and `index-db` identifiable for the calling agent.
- Use temporary retention by default when the agent only needs to extract, summarize, or answer from YouTube, Reels, TikTok, local media, or similar sources. Use isolated `--out`/`--index-db`, read the generated artifacts, answer, and clean the raw run files.
- Preserve artifacts or index in the user's real knowledge base only when the user asks to save, index, audit later, or reuse the dossier.
- When durable retention is requested, run `transcreveai share RUN_ID --json` after analysis. If the run used an isolated index, pass the same `--index-db` or use `transcreveai share --run-dir "$RUN_DIR" --json`. The package includes `handoff.md`, `manifest.json`, `knowledge.md`, and `analysis.json`, and updates share-root `catalog.json`/`index.md` so another agent can discover and resume without loose paths.
- If the dossier is preserved or indexed, explicitly tell the calling agent: `O dossie que voce criou foi salvo para voce como conhecimento.`
- The preservation handoff must include the path to `knowledge.md`, the `run_id`, and whether the knowledge was saved in the user's real index or in an isolated agent index.
- If the dossier was temporary and cleaned up, do not claim it was saved; report the `run_id`, that the answer was based on generated artifacts, and that temporary files were removed.

## Operational Rules

- For smoke tests, demos, and automated validation, prefer `--index-db /tmp/...` and `--out /tmp/...` so proof runs do not pollute the user's real index.
- When the user asks to use TranscreveAI, base the answer on generated artifacts (`knowledge.md`, `analysis.json`, and template files when present), not on a manual parallel dossier.
- For temporary runs, create a dedicated temp directory, use `--out "$TMP/runs"` and `--index-db "$TMP/index.db"`, read the artifacts, then remove the temp directory.
- If a temporary run accidentally used the user's real index or had to register a run in it, remove that run with `transcreveai runs rm RUN_ID --force` before deleting the run folder.
- Do not expose API keys, cookies, or complete sensitive URLs in logs or responses.
- Keep IDE/agent instruction files synchronized with `AGENTS.md`.
