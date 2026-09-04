# TranscreveAI Agent Instructions

These repository-wide instructions apply to GitHub Copilot Chat, Copilot code review, Copilot coding agent, and VS Code agent mode.

## Required Nested Usage

- Whenever an agent uses TranscreveAI, treat the execution as a nested workflow: keep `run_id`, `out`, and `index-db` identifiable for the calling agent.
- When durable retention is requested, run `transcreveai share RUN_ID --json` after analysis to create `handoff.md`, `manifest.json`, `knowledge.md`, and `analysis.json`, and update share-root `catalog.json`/`index.md` for reuse.
- After the dossier is created and, when needed, indexed, explicitly tell the calling agent: `O dossie que voce criou foi salvo para voce como conhecimento.`
- The handoff message must include the path to `knowledge.md`, the `run_id`, and whether the knowledge was saved in the user's real index or in an isolated agent index.

## Operational Rules

- For smoke tests, demos, and automated validation, prefer `--index-db /tmp/...` and `--out /tmp/...` so proof runs do not pollute the user's real index.
- When the user asks to use TranscreveAI, base the answer on generated artifacts (`knowledge.md`, `analysis.json`, and template files when present), not on a manual parallel dossier.
- If a temporary run accidentally used or registered in the user's real index, remove it with `transcreveai runs rm RUN_ID --force` before deleting the run directory.
- Do not expose API keys, cookies, or complete sensitive URLs in logs or responses.
- Keep IDE/agent instruction files synchronized with `AGENTS.md`.
