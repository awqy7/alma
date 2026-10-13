# Auditoria — 2026-10-08

Workspace examinada: `/home/awqy`. Não foi encontrado repositório ALMA,
Cargo.toml ou tauri.conf.json. Caminho solicitado ao usuário; núcleo iniciado
em diretório novo `alma`, sem mover ou sobrescrever os projetos existentes.

## Base existente

`../eproc-recorder`: Node/Playwright, recorder.js, chrome-login.js,
lib/{privacy,analyzer,chrome-manual,dom.browser,injector.browser}.js,
tests/{integration,driver}.js e páginas sintéticas em test-site.
É um gravador, não um motor de reconciliação. Há relatórios privados locais;
nenhum relatório ou documento judicial foi copiado para este projeto.
O comando git status informou que o recorder não é um repositório Git.
Não foram localizadas instruções AGENTS.md aplicáveis ao novo diretório.

## Ambiente

- Node 22.22.1; Python 3.14.4.
- Rust/Cargo ausentes do PATH.
- GTK 3/WebKitGTK 4.1 ausentes no pkg-config.
- Tesseract ausente do PATH.
- Playwright disponível no Python global; demais dependências isoladas em .venv.
- Teste original: `npm test`; primeira tentativa bloqueada por EPERM ao
  abrir servidor loopback no sandbox. Reexecução autorizada solicitada.

## Decisões

Preservar recorder integralmente. Começar pelos contratos e worker executável;
SQLite pertence exclusivamente ao Rust. Valores monetários atravessam IPC como
strings decimais. Nunca retornar êxito sintético para comandos não mapeados.
Navegação, identidade da sessão, índice de eventos e associação de beneficiários
exigem descoberta por DOM autorizado antes de habilitação no eproc real.

## Limites de validação

Sem sessão eproc fornecida. Fixtures não comprovam compatibilidade com produção.
Ausência do toolchain nativo impede declarar Tauri iniciado até sua instalação.
