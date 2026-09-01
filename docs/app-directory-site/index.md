# TranscreveAI

O TranscreveAI transforma URLs públicas ou arquivos autorizados em transcrição, OCR, observações visuais e dossiês com referências às evidências processadas.

## Recursos

- Sondagem da fonte antes da análise.
- Extração de áudio, frames, transcrição e texto visível.
- Artefatos estruturados, incluindo `analysis.json` e `knowledge.md`.
- `analyze` e a análise MCP gravam em `outputs/` e tentam indexar por padrão; `--no-index` ou `no_index=true` desativam embeddings, sem apagar as saídas.
- Fluxos temporários podem direcionar saída e índice a caminhos isolados e removê-los depois da resposta.
- `transcreveai share` ou `share_run` cria `manifest.json` e o pacote durável somente ao compartilhar.

## Caso técnico do próprio produto

**Problema:** um agente pode resumir um vídeo sem registrar fonte, frames ou decisões de processamento.

**Implementação:** cada execução mantém `run_id`, artefatos estruturados e referências a transcrição, OCR e evidências visuais.

**Prova pública:** o [repositório](https://github.com/DeHor-Labs/transcreve-ai) publica código, testes e documentação da CLI. Este é um caso do próprio produto, sem cliente ou ganho atribuído.

## Links

- [Código e documentação](https://github.com/DeHor-Labs/transcreve-ai)
- [Suporte](https://transcreve-ai-site.vercel.app/support.html)
- [Aviso de Privacidade](https://transcreve-ai-site.vercel.app/privacidade.html)
- [Termos de Uso](https://transcreve-ai-site.vercel.app/termos.html)
