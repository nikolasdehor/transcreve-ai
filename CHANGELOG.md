# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
versionamento conforme [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [1.0.0] - 2026-08-18

Primeira versão publicada. O TranscreveAI transforma vídeo em dossiê
multimodal consultável: transcrição, frames com OCR, síntese e busca semântica,
tudo local, com servidor MCP para agentes.

### Adicionado

- Escolha de frames por troca de tela (`--frame-strategy auto|slides|interval`).
  Amostrar de N em N segundos é cego para o conteúdo: numa palestra de uma hora
  com teto de 80 frames sai um frame a cada 45s, o que repete slide e perde
  slide. O modo `slides` deixa a própria imagem decidir onde olhar, com corte de
  cena adaptado à distribuição do vídeo.
- Reconhecimento de código mostrado na tela, com a indentação reconstruída a
  partir das coordenadas do OCR e a coluna de números de linha do editor
  descartada. Sai em bloco cercado no `knowledge.md`.
- Capítulos ilustrados: cada capítulo traz o frame que estava na tela naquele
  ponto e o código lido ali, em vez de as imagens viverem num anexo no fim.
- Frames em PNG no modo `slides`, porque o JPEG borra texto fino e arruína o
  OCR de código.
- Redação de segredos no código lido da tela, para que chave de API, token ou
  URL assinada exibidos no vídeo não sejam persistidos nem publicados.

### Segurança

- `FrameObservation.code` passa por redação antes de ir para o `analysis.json`
  e antes de ser renderizado no Markdown.
- A detecção de cena roda com timeout, então um ffmpeg travado não segura a CLI
  nem o servidor MCP indefinidamente.

### Limites conhecidos

- O tesseract perde o underscore em fonte de editor, então `fetch_users` sai
  como `fetch users`. Para código fiel, o caminho é o modelo de visão com
  prompt de transcrição literal, o que custa API.
- O recuo reconstruído é proporcional, não exato: quatro espaços podem virar
  cinco. A hierarquia entre níveis se mantém.

[1.0.0]: https://github.com/DeHor-Labs/transcreve-ai/releases/tag/v1.0.0
