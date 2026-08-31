# TranscreveAI

O TranscreveAI transforma URLs públicas ou arquivos autorizados em transcrição, OCR, observações visuais e dossiês com referências às evidências processadas.

## Recursos

- Sondagem da fonte antes da análise.
- Extração de áudio, frames, transcrição e texto visível.
- Artefatos estruturados, incluindo `analysis.json` e `knowledge.md`.
- Execuções temporárias ou preservadas conforme a escolha do usuário.

## Caso técnico do próprio produto

**Problema:** um agente pode resumir um vídeo sem registrar fonte, frames ou decisões de processamento.

**Implementação:** cada execução mantém `run_id`, artefatos estruturados e referências a transcrição, OCR e evidências visuais.

**Prova pública:** o [repositório](https://github.com/DeHor-Labs/transcreve-ai) publica código, testes e documentação da CLI. Este é um caso do próprio produto, sem cliente ou ganho atribuído.

## Links

- [Código e documentação](https://github.com/DeHor-Labs/transcreve-ai)
- [Suporte](https://transcreve-ai-site.vercel.app/support.html)
- [Aviso de Privacidade](https://transcreve-ai-site.vercel.app/privacidade.html)
- [Termos de Uso](https://transcreve-ai-site.vercel.app/termos.html)
