---
name: transcreveai-video-intelligence
description: Use to turn video URLs or media files into evidence-backed knowledge dossiers with TranscreveAI. Trigger on Reels, YouTube, TikTok, Loom, Vimeo, X/Twitter video links, local media files, video summaries, dossier requests, RAG over video runs, or requests to use TranscreveAI.
---

# TranscreveAI Video Intelligence

Use this skill when the user sends a video URL/file or asks Codex to extract, summarize, analyze, index, or ask questions about video content with TranscreveAI.

## Tooling Preference

- Prefer the TranscreveAI MCP tools when available:
  - `sources_probe` for source pre-checks.
  - `agent_run` for the full probe/analyze/index/ask workflow.
  - `agent_batch` for saved lists of sources.
  - `index`, `ask`, `runs_list`, `runs_show`, and `shared_catalog` for retrieval.
- If the MCP tools are not available in the current Codex thread, use the CLI.
- CLI command preference:
  - First try `transcreveai`.
  - If it is not on PATH, use the plugin wrapper at `./scripts/transcreveai` from the installed plugin root.
- MCP server command for local registration:
  - `bash ./scripts/transcreveai-mcp --transport stdio` from the installed plugin root.
- The plugin wrappers add `/opt/homebrew/bin` and `/usr/local/bin` to PATH so Homebrew FFmpeg/Tesseract installs are visible to Codex-launched processes.
- If TranscreveAI is not installed globally, the wrappers create a venv under `~/.cache/transcreveai-codex-plugin` and install `transcreve-ai[mcp,rag]` from pinned commit `7490586e86b57eefae377dc6839e9476f89ffd8d` of `https://github.com/DeHor-Labs/transcreve-ai.git`.

## Required Nested Handoff

Whenever TranscreveAI is used as a nested capability for another agent or workflow:

- Keep `run_id`, `out`, and `index-db` identifiable for the caller.
- Use temporary retention by default when the caller only needs extraction, summary, or an answer from YouTube, Reels, TikTok, local media, and similar sources.
- Preserve artifacts or index in the user's real knowledge base only when the caller/user asks to save, index, audit later, or reuse the dossier.
- When durable reuse is requested, run `transcreveai share RUN_ID --json` or call MCP `share_run` after analysis. If the run used an isolated index, pass the same `--index-db` or use `transcreveai share --run-dir "$RUN_DIR" --json`. It writes `handoff.md`, `manifest.json`, `knowledge.md`, and `analysis.json`, and updates share-root `catalog.json`/`index.md`. To rediscover durable packets later, use `transcreveai share --catalog --json` or MCP `shared_catalog`.
- If the dossier is preserved or indexed, explicitly say:
  `O dossie que voce criou foi salvo para voce como conhecimento.`
- Include the path to `knowledge.md`, the `run_id`, and whether the knowledge was saved in the user's real index or in an isolated agent index.
- If the run was temporary and cleaned up, do not claim it was saved; report the `run_id`, that the answer was based on generated artifacts, and that temporary files were removed.

## Safe Defaults

- For smoke tests, demos, and automated validation, isolate state:
  - `--index-db /tmp/transcreveai-agent.db`
  - `--out /tmp/transcreveai-agent`
  - `--ai off`
  - `--provider local`
  - `--force`
- For temporary production-like agent runs, create a dedicated temp directory:
  `TMP=$(mktemp -d "${TMPDIR:-/tmp}/transcreveai-agent.XXXXXX")`,
  use `--index-db "$TMP/index.db"` and `--out "$TMP/runs"`, read the generated artifacts, then `rm -rf "$TMP"`.
- If a temporary run used the real index, remove it with `transcreveai runs rm RUN_ID --force` before deleting files.
- Do not expose API keys, cookie contents, or complete sensitive URLs in logs or final answers.
- Use `--cookies-browser chrome` only for user-owned browser state and only when needed for sources such as Instagram.
- Base final answers on generated artifacts, especially `knowledge.md`, `analysis.json`, and template files. Do not create a parallel manual dossier and pretend it came from TranscreveAI.
- If analysis fails before artifacts are written, check whether `ffmpeg`, `ffprobe`, and `tesseract` are visible in PATH before treating it as a TranscreveAI bug.

## Recommended Agent Flow

1. Probe the source:

```bash
transcreveai sources probe "SOURCE" --json
```

Read `kind`, `adapter`, `requires_cookies`, and `notes`. If cookies are required, prefer `--cookies-browser chrome` for user-owned sources.

2. Run the agent workflow:

```bash
TMP=$(mktemp -d "${TMPDIR:-/tmp}/transcreveai-agent.XXXXXX")
transcreveai --index-db "$TMP/index.db" agent run "SOURCE" --out "$TMP/runs" --json
```

For an isolated no-cost smoke:

```bash
transcreveai --index-db /tmp/transcreveai-agent.db agent run "SOURCE" \
  --out /tmp/transcreveai-agent \
  --ai off \
  --provider local \
  --force \
  --json
```

3. Add templates when useful:

- Use `--template content` for creator, marketing, product, sales, distribution, or content workflow videos.
- Use `--template skill` for videos about agents, prompts, skills, Claude, Codex, automations, or reusable workflows.
- Read generated `content.md`/`content.json`/`content.csv` and `skill.md`/`skill.json` before answering about those artifacts.

4. Read the evidence:

- Always inspect `knowledge.md`.
- Inspect `analysis.json` for structured metadata, source, paths, transcript quality, and run details.
- If the user asks a question over the run, index and query:

```bash
transcreveai index RUN_ID
transcreveai ask "QUESTION" --run-id RUN_ID --top-k 8
```

5. Report compactly:

- Summarize what the video actually supports.
- Separate evidence from inference when making product, business, or technical recommendations.
- Cite artifact paths only when the dossier is preserved. For temporary runs that are cleaned up, cite the `run_id` and cleanup status instead.
- State limitations when transcript, OCR, visual context, or source access was weak.
- Unless the user asked to preserve/index the dossier, remove the temp directory after reading the artifacts and mention that temporary files were removed.

## Batch Flow

For multiple URLs or files:

```bash
transcreveai agent batch ./sources.txt \
  --template content \
  --template skill \
  --strict \
  --json
```

Use `--strict` when any failed item should block the caller. Read `success`, `ok_count`, `failed_count`, `batch.md`, `batch.json`, and per-run `template_paths`.

## Expected Artifacts

- `knowledge.md`: human-readable dossier.
- `analysis.json`: structured run metadata and analysis.
- Optional `content.md`, `content.json`, `content.csv`.
- Optional `skill.md`, `skill.json`.
- Optional `batch.md`, `batch.json` for batch runs.

## Example Starter Commands

```bash
transcreveai sources probe "https://www.instagram.com/reel/..." --json
transcreveai agent run "https://www.instagram.com/reel/..." --template content --template skill --json
transcreveai agent batch ./sources.txt --template content --template skill --json
transcreveai ask "What decisions does this video support?" --run-id RUN_ID --top-k 8
```

### Palestra tecnica, aula ou tutorial longo

Use `--frame-strategy slides`: os frames saem na troca de tela em vez de a cada
N segundos, entao nenhum slide se perde nem aparece repetido. O padrao `auto` ja
liga isso sozinho quando o video e longo demais para o intervalo cobrir.

```bash
transcreveai analyze "<url>" --ai auto --frame-strategy slides
```

Codigo mostrado na tela e reconhecido e sai em bloco cercado no `knowledge.md`,
com a indentacao reconstruida a partir da posicao do texto na imagem. Em
`slides` os frames sao gravados em PNG: o JPEG borra texto fino e arruina o OCR
de codigo.
