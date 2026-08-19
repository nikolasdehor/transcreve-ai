---
name: transcreveai-video-intelligence
description: "Use para transformar vídeos em conhecimento: extrair resumo, análise, dossiê e RAG de Reels, YouTube, TikTok, Loom etc. Dispare quando o usuário enviar um link de vídeo, pedir análise/resumo e/ou quiser transformar conteúdo audiovisual em conhecimento consultável no Codex/Claude."
---

# TranscreveAI Video Intelligence

Este é um artefato de skill do projeto (não é instalação global): usa `transcreveai` disponível no ambiente atual.

Use this skill for video-to-knowledge flows only. Prefer this path when the user sends a video URL/file and asks for extraction, summary, analysis, or to answer questions from video content.

## Regra de uso aninhado

- Sempre que outro agente usar o TranscreveAI como capacidade, trate o fluxo como aninhado: isole e identifique `run_id`, `out` e `index-db` quando aplicável, para que o dossiê gerado pertença ao contexto do agente chamador.
- Use **retenção temporária por padrão** quando o agente só precisa extrair, resumir ou responder a partir de YouTube, Reels, TikTok, Loom, arquivo local etc. Use `--out`/`--index-db` isolados, leia os artefatos, responda e limpe arquivos brutos ao final.
- Use **retenção durável** somente quando o usuário pedir salvar, indexar, transformar em conhecimento consultável, auditar depois, ou reutilizar o dossiê.
- Quando a retenção durável for pedida, rode `transcreveai share RUN_ID --json` depois da análise ou use a tool MCP `share_run`. Se o run usou índice isolado, passe o mesmo `--index-db` ou use `transcreveai share --run-dir "$RUN_DIR" --json`. Isso cria `handoff.md`, `manifest.json`, `knowledge.md` e `analysis.json`, e atualiza `catalog.json`/`index.md` na raiz de compartilhamento. Para redescobrir pacotes duráveis depois, use `transcreveai share --catalog --json` ou MCP `shared_catalog`.
- Se o dossiê for preservado ou indexado, informe explicitamente ao agente chamador: `O dossie que voce criou foi salvo para voce como conhecimento.`
- Inclua junto dessa mensagem o caminho do `knowledge.md`, o `run_id` e se o conteúdo foi indexado no índice real do usuário ou em um índice isolado de agente.
- Se a execução foi temporária e limpa, não diga que o dossiê ficou salvo; informe o `run_id`, que a resposta foi baseada nos artefatos gerados, e que os temporários foram removidos.

## Quando disparar

- Mensagem contém link de vídeo (`reel`, `youtube`, `youtu.be`, `tiktok`, `loom`, `vimeo`, `x/twitter`) ou caminho de arquivo de mídia.
- Pedido explícito de `resumir`, `extrair`, `analisar`, `dossiê`, `transformar em conhecimento`, ou `transformar para Codex/Claude`.
- Pedido de consulta posterior sobre vídeos já processados (`perguntar sobre vídeo`, `o que foi dito`, etc.).

## Fluxo obrigatório

0. **Caminho curto quando disponivel**

- Se o cliente tiver a superficie MCP do TranscreveAI instalada, prefira a tool `agent_run` para fluxo completo, `agent_batch` para listas salvas e `sources_probe` para pre-check. Use o CLI como fallback universal.
- Se o MCP ainda nao estiver validado no cliente, confirme a instalacao com `transcreveai-mcp --help` e registre o servidor como comando stdio (`transcreveai-mcp --transport stdio`) antes de depender das tools. Use `transcreve-ai[mcp,rag]` quando `index`/`ask` forem necessarios.
- Prefira `transcreveai agent run "<origem>" --json` quando o objetivo for executar o fluxo completo em CLI.
- Para varias URLs/origens em arquivo `.txt`, `.csv` ou `.json`, prefira `transcreveai agent batch "<arquivo>" --json`. Use `--strict` quando qualquer item com falha deve bloquear a automacao chamadora; leia `success`, `ok_count` e `failed_count` no resumo.
- Use `--question "..."` para fazer probe, analyze, indexacao e pergunta no mesmo comando.
- Quando o video tiver foco em criacao/distribuicao de conteudo, produto, marketing, vendas ou workflows de creator, inclua `--template content` (ou `templates: ["content"]` via MCP). Leia tambem `content.md`/`content.json`/`content.csv`, que separam evidencia extraida de inferencia de produto/conteudo e geram campos para Notion/CSV.
- Quando o video mencionar skills, agentes, prompts, Claude, Codex, automacao ou workflows reutilizaveis, inclua `--template skill` (ou `templates: ["skill"]` via MCP). Leia `skill.md`/`skill.json` antes de sugerir como adicionar o conteudo na ferramenta.
- Quando o usuario pedir para "usar nossa ferramenta", a resposta final deve partir dos campos/arquivos gerados pelo TranscreveAI (`answer`, `knowledge.md`, `analysis.json`). Nao crie um dossie paralelo manual; se faltar qualidade, rerode a ferramenta com provider/visao/indexacao melhores e explique o limite.
- Execute o CLI a partir do repo/app configurado ou confirme o provider efetivo no JSON. O CLI carrega `.env` do cwd e do pacote local, mas variaveis ja exportadas no shell continuam tendo precedencia.
- Para smoke tests, demos ou execucoes automatizadas por agente, prefira um indice isolado:
  `transcreveai --index-db /tmp/transcreveai-agent.db agent run "<origem>" --out /tmp/transcreveai-agent --ai off --provider local --force --json`.
  Isso evita consultar ou bloquear o indice real do usuario e torna a prova repetivel.
- Para execuções temporárias reais, use um diretório dedicado e descartável:
  `TMP=$(mktemp -d "${TMPDIR:-/tmp}/transcreveai-agent.XXXXXX")`
  `transcreveai --index-db "$TMP/index.db" agent run "<origem>" --out "$TMP/runs" --json`
  Depois de ler `knowledge.md`, `analysis.json` e templates necessários, execute `rm -rf "$TMP"`.
- Se a execução temporária tiver usado o índice real por engano, remova o run antes de apagar a pasta: `transcreveai runs rm RUN_ID --force`.
- Se precisar controlar cada etapa, siga o fluxo manual abaixo.

1. **Probe da origem**

- `transcreveai sources probe "<origem>" [--json]`
- Se usar `--json`, capture `kind`, `adapter`, `requires_cookies`, `notes`.
- Se não usar `--json`, leia a mensagem humana do comando e mapeie os sinais de restrição.
- Se estiver em fluxo agente via API web, use também:
  - `POST /api/sources/probe` com JSON `{"source":"<origem>"}` (ou equivalente via cliente HTTP interno).
  - Só avance para envio do job se o `source` vier normalizado e os sinais de risco estiverem claros.

2. **Escolha de execução**

- Se `requires_cookies=true` para a origem, tente:
  - `transcreveai analyze "<origem>" --cookies-browser chrome --ai auto ...`
  - ou `--cookies /caminho/para/cookies.txt` (somente se o usuário autorizou e arquivo está seguro localmente).
- Se não houver necessidade de IA (privacidade/baixo custo), use `--ai off`.
- Se o usuário quiser máxima riqueza de contexto, use `--ai auto` (padrão) e `--provider` adequado.
- Para fontes já locais e sem necessidade de modelos, combine `--provider local`.
- Para reduzir custo de prova/ajuste, rode primeira passada com `--ai off` e, se necessário, reavalie com `--ai auto`.

3. **Executar análise**

- `transcreveai analyze "<origem>" --out outputs [opções]`
- Opções úteis: `--language pt|en`, `--frame-interval`, `--max-frames`, `--visual-limit`, `--provider`.
- Para fontes repetidas e reprocessamento forçado: `--force`.

4. **Ler evidências e normalizar saída**

- Sempre leia `knowledge.md` e `analysis.json` gerados no diretório de saída informado pelo CLI.
- Se `--template content` foi usado, leia `content.md`, `content.json` e, quando relevante, `content.csv` antes de responder sobre copy, distribuição, backlog, Notion/CSV, hooks ou roteiros.
- Se `--template skill` foi usado, leia `skill.md` e `skill.json` antes de responder sobre virar skill, MCP, CLI, prompt operacional, automacao ou melhoria de ferramenta.
- Extraia: fonte, resumo, capítulos, timeline, entidades/ferramentas, afirmações e trechos de evidence.
- Se o usuário pediu “para Codex/Claude”, forneça uma versão compacta com fontes e limites de confiança (sem inventar conteúdo ausente).

5. **Indexação e perguntas**

- Se precisa consulta estruturada posterior, rode:
  - `transcreveai index <run_id>` para um run específico ou `transcreveai index --all`.
- Para checar retrieval sem LLM: `transcreveai ask "..." --search-only`.
- Para resposta completa: `transcreveai ask "..."`.
- Use `--run-id` para restringir o escopo quando o usuário indicar contexto específico.

## Saídas esperadas

- CLI prints path do diretório de execução (`OK:`) e os arquivos `knowledge.md`/`analysis.json`.
- Templates opcionais:
  - `content`: `content.md`, `content.json`, `content.csv`.
  - `skill`: `skill.md`, `skill.json`.
- Batch prints/grava `batch.md` e `batch.json`, com `template_paths` por item quando templates forem usados.
- Se necessário, confirme run com `transcreveai runs list --json` e repita com `--run-id` em `ask/index`.
- Em fluxos web, registre o `run` retornado por `/api/jobs` (ou equivalente) antes de chamar `ask`/`index`; isso evita consultar o dossier errado.

## Custos, privacidade e segurança

- `--ai off` = mínimo custo; `--ai auto/full` pode gerar chamadas de LLM.
- Em validacoes e demos, combine `--index-db`, `--out /tmp/...`, `--ai off`, `--provider local` e `--force` para evitar custo, estado global e dedupe acidental.
- Não compartilhe chaves de API nem conteúdo bruto de `cookies` em chat.
- `cookies-browser`/`cookies.txt` devem ser usados apenas com arquivos de origem do usuário, curtos no escopo e sem exportação adicional.
- Evite logar URLs sensíveis completas; cite IDs e caminhos locais quando possível.
- Se for necessário reter artefatos, sinalize onde estão gravados e como remover (`runs rm --purge`) quando apropriado.
- Se não for necessário reter artefatos, limpe a pasta temporária ao final para não ocupar espaço no dispositivo.

## Exemplos

```bash
transcreveai sources probe "https://www.instagram.com/reel/..." --json
transcreveai analyze "https://www.instagram.com/reel/..." --ai auto --language pt --template content --template skill
transcreveai agent batch ./sources.txt --template content --template skill --json
transcreveai index --all --provider local
transcreveai ask "o que foi mostrado no vídeo?" --search-only
curl -X POST http://127.0.0.1:8000/api/sources/probe \
  -H "Content-Type: application/json" \
  -d '{"source":"https://www.instagram.com/reel/..."}'
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
