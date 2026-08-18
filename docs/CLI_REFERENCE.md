# CLI Reference

## Comandos disponiveis

| Comando | Descricao |
|---|---|
| `transcreveai analyze SOURCE` | Analisa um link ou arquivo de video |
| `transcreveai sources probe SOURCE` | Inspeciona o tipo da fonte |
| `transcreveai agent run SOURCE` | Executa o workflow de agente: probe, analyze e opcionalmente index/ask |
| `transcreveai agent batch SOURCES_FILE` | Executa o workflow de agente para uma lista `.txt`, `.csv` ou `.json` |
| `transcreveai index [RUN_ID\|--all]` | Indexa runs para busca semantica (RAG) |
| `transcreveai ask PERGUNTA` | Faz uma pergunta sobre os videos indexados |
| `transcreveai serve` | Inicia o servidor web com API e SPA |
| `transcreveai runs list` | Lista o historico de runs |
| `transcreveai runs show RUN_ID` | Exibe detalhes de um run |
| `transcreveai runs rm RUN_ID` | Remove um run do indice |
| `transcreveai share RUN_ID` | Empacota um run como handoff duravel para agentes |
| `transcreveai share --catalog` | Lista pacotes de conhecimento compartilhado |
| `transcreveai-mcp` | Inicia o servidor MCP opcional para agentes |

---

## Flag global

```bash
transcreveai [--index-db PATH] COMANDO
```

| Flag | Descricao | Default |
|---|---|---|
| `--index-db PATH` | Path do banco SQLite de indice. Sobreescreve `VIDEO_KB_INDEX_DB`. | `~/.transcreveai/index.db` |

---

## `transcreveai agent run`

Executa o caminho curto para agentes: faz `sources probe`, roda a analise e pode indexar o run e responder uma pergunta no mesmo comando.

```bash
transcreveai agent run SOURCE [opcoes]
```

### Exemplos

```bash
# Probe + analise + resposta estruturada em JSON
transcreveai agent run "https://youtu.be/..." --ai auto --language pt --json

# Analise e indexacao para RAG
transcreveai agent run "https://youtu.be/..." --index --provider local

# Analise, indexacao automatica e pergunta restrita ao run gerado
transcreveai agent run "https://youtu.be/..." \
  --question "quais ferramentas, passos e riscos aparecem no video?" \
  --top-k 8

# Pacote Creator Remix / Content Intelligence
transcreveai agent run "https://www.instagram.com/reel/..." \
  --template content \
  --json

# Pacote de skill/workflow reutilizavel
transcreveai agent run "https://www.instagram.com/reel/..." \
  --template skill \
  --json

# Gerar os dois pacotes no mesmo run
transcreveai agent run "https://www.instagram.com/reel/..." \
  --template content \
  --template skill \
  --json
```

### Opcoes principais

| Flag | Descricao | Default |
|---|---|---|
| `--json` | Emite resultado estruturado para agentes | `false` |
| `--index` | Indexa o run apos a analise | `false` |
| `--index-force` | Reindexa mesmo se ja houver embeddings | `false` |
| `--question TEXT` | Faz uma pergunta apos analisar; implica indexacao | - |
| `--top-k N` | Numero de trechos usados no RAG | `5` |
| `--ai {auto,off,full}` | Modo de IA repassado ao pipeline | `auto` |
| `--provider NOME` | Provider de IA/embedding | `openai` |
| `--cookies-browser BROWSER` | Browser para cookies do yt-dlp | - |
| `--template {content,skill}` | Gera artefatos extras. `content` escreve `content.md`, `content.json` e `content.csv`; `skill` escreve `skill.md` e `skill.json`. Pode ser usado mais de uma vez. | - |
| `--force` | Reprocessa mesmo que a origem ja exista no indice | `false` |

Se o probe retornar `unknown`, o comando imprime o resultado e encerra com codigo `1`.
Quando o run completa, a saida JSON inclui `share_command`,
`share_run_dir_command` e `share_catalog_command` para preservar e redescobrir
o dossie depois, sem copiar artefatos automaticamente.

---

## `transcreveai agent batch`

Executa `agent run` para uma lista salva de origens. O arquivo pode ser:

- `.txt`: uma origem por linha; linhas vazias e comentarios com `#` sao ignorados.
- `.csv`: usa a coluna `source`, `url` ou `link`; se nao houver header reconhecido, usa a primeira coluna.
- `.json`: aceita lista de strings, lista de objetos com `source`/`url`/`link`, ou objeto com `sources`/`urls`.

```bash
transcreveai agent batch SOURCES_FILE [opcoes]
```

### Exemplos

```bash
# Processar lista e gerar resumo batch
transcreveai agent batch ./sources.txt --ai auto --language pt --json

# Gerar Creator Remix e skill draft para cada item
transcreveai agent batch ./sources.csv \
  --template content \
  --template skill \
  --strict \
  --json

# Smoke test isolado, sem custo de IA
transcreveai --index-db /tmp/transcreveai-batch.db agent batch ./sources.json \
  --out /tmp/transcreveai-batch \
  --provider local \
  --ai off \
  --force \
  --limit 3 \
  --json
```

### Opcoes principais

| Flag | Descricao | Default |
|---|---|---|
| `--json` | Emite resumo estruturado do batch | `false` |
| `--out PATH` | Diretorio de saida do batch | `outputs-batch` |
| `--limit N` | Limita a quantidade de origens processadas (`0` = sem limite) | `0` |
| `--fail-fast` | Para no primeiro erro inesperado | `false` |
| `--strict` | Retorna exit code `1` se qualquer item falhar, mesmo continuando o batch | `false` |
| `--frame-interval N` | Intervalo entre frames por run | `5.0` |
| `--max-frames N` | Maximo de frames locais por run (`0` = sem limite) | `80` |
| `--frame-strategy MODO` | `slides` detecta troca de tela, `interval` amostra por tempo, `auto` usa slides em video longo | `auto` |
| `--visual-limit N` | Maximo de frames enviados para visao por IA em cada run | `30` |
| `--template {content,skill}` | Gera os mesmos templates do `agent run` para cada run | - |
| `--index` | Indexa cada run apos a analise | `false` |
| `--question TEXT` | Faz a mesma pergunta para cada run; implica indexacao | - |
| `--provider NOME` | Provider de IA/embedding | `openai` |
| `--ai {auto,off,full}` | Modo de IA repassado a cada run | `auto` |
| `--vision-model MODEL` | Modelo de visao/sintese repassado a cada run | - |
| `--transcribe-model MODEL` | Modelo de transcricao repassado a cada run | - |
| `--language LANG` | Idioma do audio, ex: `pt`, `en` | - |
| `--tesseract-lang LANG` | String de idioma OCR | `por+eng` |
| `--cookies-browser BROWSER` | Browser para cookies do yt-dlp | - |
| `--cookies FILE` | Arquivo `cookies.txt` para yt-dlp | - |
| `--storage NOME` | Backend de armazenamento | `filesystem` |
| `--force` | Reprocessa origens ja conhecidas | `false` |

O comando grava `batch.json` e `batch.md` no diretorio de saida. O resumo inclui
`success`, `total`, `ok`, `failed`, `ok_count` e `failed_count`; `ok` e
`failed` sao mantidos como contadores por compatibilidade. Cada item inclui
`ok`, `run_id`, `analysis_path`, `markdown_path` e, quando houver templates,
`template_paths` com os caminhos gerados.

---

## `transcreveai-mcp`

Inicia a superficie MCP opcional do TranscreveAI. Instale o extra antes:

```bash
pip install 'transcreve-ai[mcp,rag]'
transcreveai-mcp
```

Por padrao, o transporte e `stdio`, adequado para clientes MCP locais. Para um endpoint HTTP:

```bash
transcreveai-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Registro generico em clientes MCP:

```json
{
  "mcpServers": {
    "transcreveai": {
      "command": "transcreveai-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

Valide a instalacao com `transcreveai-mcp --help`. Use `[mcp,rag]` quando o
cliente tambem for chamar `index`/`ask`; para apenas `sources_probe`, `analyze`,
`agent_run` e `agent_batch`, `[mcp]` basta.

Tools expostas:

| Tool | Descricao |
|---|---|
| `sources_probe` | Classifica uma URL/caminho antes de baixar |
| `analyze` | Roda a analise e retorna paths dos artefatos |
| `agent_run` | Executa probe, analise, indexacao opcional e pergunta opcional |
| `agent_batch` | Executa `agent_run` em uma lista `.txt`, `.csv` ou `.json` |
| `index` | Indexa um run ou todos os runs para RAG |
| `ask` | Consulta runs indexados, com `search_only` quando necessario |
| `runs_list` | Lista runs do indice SQLite |
| `runs_show` | Retorna detalhes de um run especifico |
| `share_run` | Gera `handoff.md`, `manifest.json` e catalogo para um run local indexado |
| `shared_catalog` | Lista pacotes duraveis criados por `share_run` |

As tools capturam stdout/stderr do pipeline e devolvem esses logs no campo
`logs`, para preservar o protocolo MCP quando o transporte e `stdio`.
As tools `analyze`, `agent_run` e `agent_batch` aceitam
`templates: ["content", "skill"]`. `content` gera `content.md`,
`content.json` e `content.csv`; `skill` gera `skill.md` e `skill.json`.
`agent_batch` tambem aceita `frame_interval`, `max_frames`, `visual_limit`,
`vision_model`, `transcribe_model`, `tesseract_lang`, `video_format`,
`provider`, `ai`, `language`, `cookies_browser`, `cookies`, `storage`, `limit`
e `fail_fast` para controlar cada run da lista.

---

## `transcreveai analyze`

Analisa um link ou arquivo de video e grava um dossie multimodal.

```bash
transcreveai analyze SOURCE [opcoes]
```

### Argumento

- `SOURCE`: URL ou caminho local do video.

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--out PATH` | Diretorio de saida | `outputs` |
| `--frame-interval N` | Intervalo entre frames em segundos | `5.0` |
| `--max-frames N` | Maximo de frames locais (`0` = sem limite) | `80` |
| `--frame-strategy MODO` | `slides` detecta troca de tela, `interval` amostra por tempo, `auto` usa slides em video longo | `auto` |
| `--visual-limit N` | Maximo de frames enviados para visao por IA | `30` |
| `--ai {auto,off,full}` | Modo de uso da IA. `auto` usa IA se a chave do provider estiver definida | `auto` |
| `--vision-model MODEL` | Modelo de visao/sintese | - |
| `--transcribe-model MODEL` | Modelo de transcricao | - |
| `--language LANG` | Idioma do audio, ex: `pt`, `en` | - |
| `--tesseract-lang LANG` | String de idioma OCR | `por+eng` |
| `--cookies-browser BROWSER` | Browser para cookies do yt-dlp, ex: `chrome` | - |
| `--cookies FILE` | Arquivo `cookies.txt` para yt-dlp | - |
| `--format SELECTOR` | Seletor de formato yt-dlp | `bv*+ba/b` |
| `--provider NOME` | Provider de IA: `openai`, `local`, `gemini`, `anthropic` ou externo via entry_points. Sobreescreve `VIDEO_KB_PROVIDER`. | `openai` |
| `--storage NOME` | Backend de armazenamento: `filesystem`, `obsidian`, `notion`, `supabase`, `s3`. Sobreescreve `VIDEO_KB_STORAGE`. | `filesystem` |
| `--template {content,skill}` | Gera artefatos extras: `content.md`/`content.json`/`content.csv` e/ou `skill.md`/`skill.json` | - |
| `--force` | Ignora dedupe: reprocessa mesmo que o `source_hash` ja exista no indice | `false` |

### Comportamento de dedupe

Ao analisar uma fonte, o pipeline calcula um SHA-256 da URL ou do arquivo. Se um run com o mesmo hash ja existir no indice com `status != "failed"`, o pipeline exibe uma mensagem e encerra sem reprocessar. Use `--force` para sobrescrever.

### Exemplos

```bash
# Analise basica com IA automatica
transcreveai analyze "https://www.instagram.com/reel/..." --ai auto --language pt

# Arquivo local sem IA
transcreveai analyze ./video.mp4 --ai off --frame-interval 3 --max-frames 60

# Com cookies de browser para plataformas que exigem login
transcreveai analyze "https://www.instagram.com/reel/..." --cookies-browser chrome --ai auto

# Provider Google Gemini
transcreveai analyze "https://youtu.be/..." --provider gemini --language pt

# Provider offline/gratuito (requer pip install transcreve-ai[local])
transcreveai analyze ./video.mp4 --provider local --ai auto

# Provider Anthropic (requer pip install transcreve-ai[anthropic])
transcreveai analyze "https://youtu.be/..." --provider anthropic --ai auto

# Definir provider via variavel de ambiente
VIDEO_KB_PROVIDER=gemini transcreveai analyze "https://youtu.be/..." --ai auto

# Exportar para vault do Obsidian (requer pip install transcreve-ai[obsidian])
VIDEO_KB_OBSIDIAN_VAULT=~/ObsidianVault transcreveai analyze "https://youtu.be/..." --storage obsidian

# Exportar para Notion (requer pip install transcreve-ai[notion])
transcreveai analyze "https://youtu.be/..." --storage notion

# Upload para S3 (requer pip install transcreve-ai[s3])
transcreveai analyze "https://youtu.be/..." --storage s3

# Forcando reprocessamento de source ja indexada
transcreveai analyze "https://youtu.be/..." --force

# Banco de indice customizado
transcreveai --index-db ~/projetos/meu.db analyze "https://youtu.be/..."
```

---

## `transcreveai sources probe`

Inspeciona uma entrada para identificar como ela sera tratada pelo downloader e quais avisos sao esperados.

```bash
transcreveai sources probe SOURCE [opcoes]
```

### Argumento

- `SOURCE`: URL ou caminho local do video.

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--json` | Emite JSON no stdout com o resultado do probe. | `false` |

### Exemplos

```bash
transcreveai sources probe "https://www.youtube.com/watch?v=abc123"
transcreveai sources probe "https://www.instagram.com/reel/abc123/" --json
transcreveai sources probe ./meu_video.mp4
```

### API equivalente (quando rodando `transcreveai serve`)

Com o servidor web ativo, o pre-check também está disponível como:

`POST /api/sources/probe`

Por segurança, o endpoint web aceita apenas URLs `http://` ou `https://`. Para
arquivos locais, use o CLI `transcreveai sources probe ./arquivo.mp4` ou o fluxo
de upload da API, evitando expor caminhos absolutos do servidor.

Payload:

```json
{
  "source": "URL_DA_FONTE"
}
```

Retorno (exemplo):

```json
{
  "source": "URL_DA_FONTE",
  "kind": "youtube",
  "adapter": "youtube",
  "is_url": true,
  "canonical": "https://www.youtube.com/watch?v=abc123",
  "requires_cookies": false,
  "notes": ["..."]
}
```

Erros esperados:
- `422` com `{"error":"validation", ...}` quando `source` estiver ausente, não for texto ou vier vazio.
- `422` quando `source` não for uma URL `http(s)`.
- `200` com `SourceProbeResponse` quando válido.

Exemplo com curl:

```bash
curl -X POST http://127.0.0.1:8000/api/sources/probe \
  -H "Content-Type: application/json" \
  -d '{"source":"https://www.youtube.com/watch?v=abc123"}'
```

Use esse endpoint para validar fonte/adapter/cookies antes de submeter `POST /api/jobs`, evitando custo desnecessário e jobs que falham no início.

Campos retornados (JSON):

- `source`: entrada original.
- `kind`: categoria (`youtube`, `instagram_reel`, `tiktok`, `x_twitter`, `vimeo`, `loom`, `direct_media_url`, `generic_yt_dlp_url`, `local_file`, `unknown`).
- `adapter`: adapter sugerido.
- `is_url`: se foi tratado como URL.
- `canonical`: representação canonical da origem.
- `requires_cookies`: se geralmente exige autenticacao via cookies.
- `notes`: observacoes sobre fallback e dicas de diagnostico.

---

## `transcreveai index`

Indexa um ou todos os runs para busca semantica. Requer o extra `[rag]`:

```bash
pip install 'transcreve-ai[rag]'
```

```bash
transcreveai index [RUN_ID | --all] [opcoes]
```

### Argumentos

- `RUN_ID`: ID do run a indexar (posicional, omitir quando `--all` for passado).

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--all` | Indexa todos os runs ainda nao indexados | `false` |
| `--provider NOME` | Provider de embedding: `openai`, `local` ou `gemini`. Sobreescreve `VIDEO_KB_PROVIDER`. | `openai` |
| `--force` | Reindexar mesmo que o run ja tenha embeddings | `false` |

O `--index-db` global tambem e respeitado.

### Comportamento

- Pula runs cujo `analysis_path` nao existe no disco.
- Pula runs ja indexados a menos que `--force` seja passado.
- Com `--force`, apaga os embeddings anteriores e regenera todos os chunks.
- Levanta erro se o provider atual gerar vetores com dimensao diferente da ja armazenada para o mesmo run (use `--force` para resolver).

### Modelos de embedding por provider

| Provider | Modelo | Offline |
|---|---|:---:|
| `openai` | `text-embedding-3-small` | Nao |
| `local` | `all-MiniLM-L6-v2` | Sim |
| `gemini` | `text-embedding-004` | Nao |

### Exemplos

```bash
# Indexar um run especifico
transcreveai index 20260601T060803Z-youtu-be-abc123

# Indexar todos os runs nao indexados (provider padrao)
transcreveai index --all

# Indexar tudo com provider offline
transcreveai index --all --provider local

# Forcar reindexacao com provider diferente
transcreveai index 20260601T060803Z-youtu-be-abc123 --provider gemini --force

# Com banco de indice customizado
transcreveai --index-db ~/projetos/meu.db index --all

# Definir provider via variavel de ambiente
VIDEO_KB_PROVIDER=local transcreveai index --all
```

---

## `transcreveai ask`

Faz uma pergunta sobre os videos indexados usando RAG. Requer o extra `[rag]`:

```bash
pip install 'transcreve-ai[rag]'
```

```bash
transcreveai ask PERGUNTA [opcoes]
```

### Argumento

- `PERGUNTA`: Texto da pergunta em linguagem natural (posicional).

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--provider NOME` | Provider de embedding e sintese: `openai`, `local` ou `gemini`. Sobreescreve `VIDEO_KB_PROVIDER`. | `openai` |
| `--top-k N` | Numero de trechos de contexto a recuperar | `5` |
| `--run-id ID` | Limita a busca a um run especifico; pode ser repetido | todos |
| `--search-only` | Exibe apenas os trechos recuperados, sem chamar LLM para sintese | `false` |

O `--index-db` global tambem e respeitado.

### Comportamento

- Vetoriza a pergunta com o provider escolhido.
- Busca os `top-k` chunks mais similares por cosseno no SQLite.
- Se `--search-only`: imprime os trechos com score, tipo e capitulo (quando disponivel) e encerra.
- Caso contrario: monta prompt com os trechos como contexto e chama o LLM do provider para gerar resposta.
- A resposta e instruida a citar os videos usados e a dizer explicitamente quando a informacao nao esta nos videos indexados.

### Saida padrao (RAG completo)

```
Pergunta: o que foi dito sobre autenticacao?

Resposta:
No video "Como usar TranscreveAI" foi mencionado que...

Fontes:
  [1] Como usar TranscreveAI (20260601T060803Z-youtu-be-abc123) - score: 87.3%
  [2] Aula de Python (20260531T120000Z-video-mp4) - score: 74.1%
```

### Saida com `--search-only`

```
Top 3 trechos para: "autenticacao"

[1] Como usar TranscreveAI (summary) - score: 87.3%
    O video demonstra o fluxo de autenticacao via OAuth2...
    Capitulo em: 3:42

[2] Aula de Python (transcript) - score: 74.1%
    ...implementacao do middleware de autenticacao JWT...
```

### Exemplos

```bash
# Pergunta simples (RAG completo, provider padrao)
transcreveai ask "o que foi dito sobre autenticacao?"

# Busca sem sintese (inspecionar chunks indexados)
transcreveai ask "autenticacao" --search-only

# Limitar a dois runs
transcreveai ask "quais ferramentas foram mostradas?" \
  --run-id 20260601T060803Z-youtu-be-abc123 \
  --run-id 20260531T120000Z-video-mp4

# Usar provider offline
transcreveai ask "resumo dos capitulos" --provider local

# Mais contexto (10 trechos)
transcreveai ask "fluxo de deploy" --top-k 10

# Com banco de indice customizado
transcreveai --index-db ~/projetos/meu.db ask "qual e a arquitetura?"

# Definir provider via variavel de ambiente
VIDEO_KB_PROVIDER=gemini transcreveai ask "o que foi discutido?"
```

---

## `transcreveai runs list`

Lista runs registrados no indice, ordenados do mais recente para o mais antigo.

```bash
transcreveai runs list [opcoes]
```

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--limit N` | Numero maximo de entradas retornadas | `20` |
| `--json` | Saida em JSON array (integravel com `jq`, scripts, etc.) | `false` |
| `--out PATH` | Filtrar apenas runs com `output_dir` igual ao valor informado | - |

### Saida padrao (tabela)

```
ID                                       STATUS     TITULO                               CRIADO EM
----------------------------------------------------------------------------------------------------
20260601T060803Z-youtu-be-abc123         completed  Como usar TranscreveAI               2026-06-01T06:08:03+00:00
20260531T120000Z-video-mp4               completed  Aula de Python                        2026-05-31T12:00:00+00:00
```

### Saida JSON (`--json`)

```json
[
  {
    "id": "20260601T060803Z-youtu-be-abc123",
    "source": "https://youtu.be/abc123",
    "source_hash": "e3b0c44...",
    "title": "Como usar TranscreveAI",
    "provider": "openai",
    "ai_mode": "auto",
    "status": "completed",
    "created_at": "2026-06-01T06:08:03+00:00",
    "finished_at": "2026-06-01T06:12:47+00:00",
    "output_dir": "outputs/20260601T060803Z-youtu-be-abc123",
    "analysis_path": "outputs/20260601T060803Z-youtu-be-abc123/analysis.json",
    "markdown_path": "outputs/20260601T060803Z-youtu-be-abc123/knowledge.md",
    "duration_seconds": 312.0,
    "warnings_count": 0,
    "storage_backend": "filesystem"
  }
]
```

### Exemplos

```bash
transcreveai runs list
transcreveai runs list --limit 50
transcreveai runs list --json
transcreveai runs list --json | jq '.[].title'
transcreveai runs list --out outputs/20260601T060803Z-youtu-be-abc123
```

---

## `transcreveai runs show`

Exibe todos os campos de um run especifico.

```bash
transcreveai runs show RUN_ID [opcoes]
```

### Argumento

- `RUN_ID`: ID exato do run (coluna `id` no indice).

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--json` | Saida em JSON bruto | `false` |

### Exemplos

```bash
transcreveai runs show 20260601T060803Z-youtu-be-abc123
transcreveai runs show 20260601T060803Z-youtu-be-abc123 --json
```

---

## `transcreveai runs rm`

Remove um run do indice SQLite. Opcionalmente apaga tambem o diretorio de saida do disco.

```bash
transcreveai runs rm RUN_ID [opcoes]
```

### Argumento

- `RUN_ID`: ID exato do run a remover.

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--purge` | Tambem deleta o `output_dir` do filesystem (`rm -rf`) | `false` |
| `--force` | Nao pede confirmacao interativa | `false` |

Por padrao, o comando pede confirmacao antes de remover. Use `--force` para scripts e automacoes.

### Exemplos

```bash
# Remove do indice (pede confirmacao)
transcreveai runs rm 20260601T060803Z-youtu-be-abc123

# Remove do indice sem confirmacao
transcreveai runs rm 20260601T060803Z-youtu-be-abc123 --force

# Remove do indice e apaga o diretorio de saida do disco
transcreveai runs rm 20260601T060803Z-youtu-be-abc123 --purge

# Remove tudo sem confirmacao (uso em scripts)
transcreveai runs rm 20260601T060803Z-youtu-be-abc123 --purge --force
```

---

## `transcreveai share`

Empacota um run existente como conhecimento compartilhavel para agentes. O
comando copia `knowledge.md`, `analysis.json` e templates gerados para um
diretorio duravel, escreve `handoff.md` + `manifest.json`, sanitiza URLs
sensiveis nos artefatos compartilhados e atualiza `catalog.json` + `index.md`
na raiz de compartilhamento.

```bash
transcreveai share RUN_ID [opcoes]
```

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--run-dir PATH` | Usa uma pasta de run contendo `analysis.json` e `knowledge.md` sem consultar o indice | - |
| `--out DIR` | Diretorio de destino | `~/.transcreveai/shared-knowledge` |
| `--query TEXT` | Filtra `--catalog` por termo em run, titulo, origem ou resumo | - |
| `--json` | Saida JSON com paths do pacote | `false` |

### Exemplos

```bash
transcreveai share 20260601T060803Z-youtu-be-abc123
transcreveai share 20260601T060803Z-youtu-be-abc123 --out ~/handoffs --json
transcreveai share --run-dir outputs/20260601T060803Z-youtu-be-abc123 --json
transcreveai share --catalog --json
transcreveai share --catalog --query whatsapp --json
```

O pacote gerado e intencionalmente simples: `handoff.md` para leitura por
Codex/Claude Code, `manifest.json` para automacoes, copias sanitizadas dos
artefatos de evidencia e um catalogo raiz para descoberta posterior.

---

## `transcreveai serve`

Inicia o servidor web TranscreveAI. Requer o extra `web` instalado:

```bash
pip install 'transcreve-ai[web]'
```

```bash
transcreveai serve [opcoes]
```

### Opcoes

| Flag | Descricao | Default |
|---|---|---|
| `--host HOST` | Endereco de bind do servidor | `127.0.0.1` |
| `--port PORT` | Porta do servidor | `8000` |
| `--out DIR` | Diretorio de saida dos jobs processados | `outputs` |
| `--reload` | Hot-reload para desenvolvimento (nao usar em producao) | `false` |

O `--index-db` global tambem e respeitado:

```bash
transcreveai --index-db ~/meu.db serve --port 8080
```

Para smoke tests de UI/API e demos de agente, prefira um banco temporario para
nao misturar a prova com o historico real do usuario:

```bash
transcreveai --index-db /tmp/transcreveai-e2e.db serve \
  --host 127.0.0.1 \
  --port 8000 \
  --out /tmp/transcreveai-e2e
```

### Comportamento

- Sobe uma aplicacao FastAPI com a API REST em `/api/*` e docs Swagger em `/api/docs`.
- Se `frontend/dist/` existir, serve a SPA em `/`. Caso contrario, apenas a API fica disponivel.
- Processa jobs de forma serial (um por vez) em background com asyncio.

### Exemplos

```bash
# Inicio basico
transcreveai serve

# Exposto na rede local, porta alternativa
transcreveai serve --host 0.0.0.0 --port 8080

# Com banco de indice customizado
transcreveai --index-db ~/projetos/meu.db serve

# Desenvolvimento com hot-reload (backend)
transcreveai serve --reload

# Construir e servir o frontend em producao
cd frontend && pnpm build
transcreveai serve
```

---

## Variaveis de ambiente

### Providers de IA

| Variavel | Descricao |
|---|---|
| `VIDEO_KB_PROVIDER` | Provider padrao quando `--provider` nao e passado |
| `OPENAI_API_KEY` | Chave para o provider `openai` |
| `GEMINI_API_KEY` | Chave para o provider `gemini` (aceita `GOOGLE_API_KEY` como fallback) |
| `ANTHROPIC_API_KEY` | Chave para o provider `anthropic` |
| `VIDEO_KB_LOCAL_WHISPER_MODEL` | Modelo faster-whisper para o provider `local` (default: `base`) |

### Storage e indice

| Variavel | Descricao | Default |
|---|---|---|
| `VIDEO_KB_INDEX_DB` | Path do banco SQLite de indice | `~/.transcreveai/index.db` |
| `VIDEO_KB_STORAGE` | Backend de storage padrao | `filesystem` |
| `VIDEO_KB_OBSIDIAN_VAULT` | Caminho absoluto da vault Obsidian | - |
| `VIDEO_KB_OBSIDIAN_SUBDIR` | Subpasta dentro da vault | `transcreve-ai` |
| `NOTION_API_KEY` | Token de integracao interna do Notion | - |
| `NOTION_DATABASE_ID` | UUID do banco de dados Notion destino | - |
| `VIDEO_KB_S3_BUCKET` | Nome do bucket S3 | - |
| `VIDEO_KB_S3_PREFIX` | Prefixo/pasta dentro do bucket (opcional) | - |
| `AWS_DEFAULT_REGION` | Regiao AWS | `us-east-1` |
| `AWS_ENDPOINT_URL` | Endpoint S3-compatible: Minio, LocalStack, etc. | - |
| `SUPABASE_URL` | URL do projeto Supabase (fase futura) | - |
| `SUPABASE_KEY` | Chave anon/service Supabase (fase futura) | - |
