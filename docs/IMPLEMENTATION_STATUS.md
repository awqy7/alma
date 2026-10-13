> Registro histórico das fases iniciais. A compilação Tauri/Linux foi posteriormente concluída. O estado atual da fila, da integração e dos bloqueios está em [AUTOMATIC_REVIEW.md](AUTOMATIC_REVIEW.md) e [PRODUCTION_AUDIT.md](PRODUCTION_AUDIT.md).

# Resultado do ciclo — 2026-10-09

## Atualização: automação real do eproc e execução supervisionada

Implementado o motor de automação real (`engine/browser/eproc/automation.py`)
que preenche e salva cabeçalho, beneficiário e honorários nos subformulários
do eproc via `apply_eproc_plan()`. A execução lê o DOM, navega por `#ifrSubFrm`,
salva cada formulário, recarrega a página e faz releitura de verificação.

A interface (`Operations.tsx`) apresenta tabela comparativa com valores atuais
vs. propostos, exige confirmação explícita do usuário e mostra progresso em
tempo real. Após execução, exibe captura da tela e detalhes dos campos salvos.

O Rust (`runner.rs`) coordena: cria job, verifica sessão e identidade do
processo, chama `APPLY_REAL_PLAN` no worker, grava execução no SQLite e
transiciona para Validated. O endpoint `/api/apply_real_plan` e o comando
Tauri estão registrados.

**Arquivos criados:** `engine/browser/eproc/automation.py`,
`tests/browser/test_real_automation.py`,
`tests/integration/test_real_worker_command.py`.

**Arquivos modificados:** `engine/browser/eproc/{session,adapter,selectors}.py`,
`engine/worker.py`, `crates/alma-core/src/{runner,state,store,preview_server}.rs`,
`apps/desktop/src-tauri/src/main.rs`, `apps/desktop/src/{main,Operations}.tsx`,
`tests/browser/test_preview.py`.

**Validação:** `cargo test -p alma-core` (12 testes), `npm run build`,
`.venv/bin/python -m pytest -q` (**57 testes aprovados**), incluindo 3 testes
de automação real com mock eproc + subform iframe.

**Próximo passo:** testar em sessão autorizada do eproc com RPV real.
GTK/WebKit e Tesseract continuam ausentes; não foi testada janela nativa
nem OCR real.

## Atualização: ensaio com PDFs e interface de conferência

Foi acrescentada uma versão funcional para testar localmente sem Tauri/GTK:
`./testar.sh`, em `http://127.0.0.1:4318`. O novo extrator reconhece rótulos
equivalentes, linhas/tabelas simples e datas com diferentes precisões; mantém
data-base separada da data da proposta. O Rust confere a soma do cenário
relatado e preserva conflitos. O ensaio não se conecta ao eproc, não escreve
no sistema oficial nem persiste PDFs/histórico automaticamente.

Arquivos principais: `engine/extraction/review_candidates.py`,
`engine/documents/inspection.py`, `crates/alma-core/src/inspection.rs`,
`crates/alma-core/src/preview_server.rs`, `apps/desktop/src/main.tsx`,
`apps/desktop/src/Operations.tsx` e `apps/desktop/src/lab.css`.
O parser e o worker existentes foram ampliados; a interface operacional foi
preservada na aba de leitura. A integração nativa ainda depende das bibliotecas
registradas abaixo. Nenhuma função de escrita foi habilitada.

Procedimento revisto, limites e instruções: [PROCEDIMENTO_E_ENSAIO.md](PROCEDIMENTO_E_ENSAIO.md).
Os resultados descritos a seguir são o registro histórico do primeiro ciclo;
esta atualização adiciona testes de layouts variados, ensaio real em Rust,
upload de PDFs pela UI, visualização da fonte, viewport móvel e isolamento HTTP.

Verificação da atualização: **35 testes Python**, **10 testes Rust**, build
TypeScript/Vite aprovado. A UI foi exercitada com Chromium, exemplos gerados
e upload real de PDFs sintéticos; screenshots revisados em desktop e mobile.
O script `testar.sh` inicia a versão local. Esses testes não representam
homologação de uma RPV real nem teste da janela nativa Tauri.

Projeto novo criado em `/home/awqy/alma`, confirmado pelo usuário durante a
auditoria. Git inicializado, sem commit. Nenhum arquivo do recorder foi alterado.
Nenhum dado judicial real foi adicionado ao novo projeto.

## Arquivos, testes, resultados e próxima etapa por fase

| Fase | Arquivos criados | Verificação / resultado | Próxima etapa |
|---|---|---|---|
| 0 — Audit | CURRENT_STATE.md, DISCOVERY.md, .gitignore | `npm test` do recorder passou; stack e logs inventariados sem valores pessoais | Preservar recorder como material de descoberta |
| 1 — Contracts | engine/ipc/contracts.py, docs/contracts/*, crates/alma-core/src/{contracts,error_code,state}.rs | Contratos usados por subprocessos reais; estados inválidos rejeitados em teste | Expandir contratos de cada seção durante descoberta |
| 2 — Worker | engine/worker.py, crates/alma-core/src/worker.rs | PING/RESULT/ERROR, JSON inválido, limite de linha, timeout e morte de worker testados; comandos iniciais implementados | Validar navegador dedicado no ambiente autorizado |
| 3 — Adapter | engine/browser/eproc/{session,adapter,selectors,diagnostics}.py | Leitura DOM, download sintético, sessão expirada, seletor ausente testados | Navegação e índice de documentos reais: DISCOVERY_REQUIRED |
| 4 — Documents | engine/documents/{parser,resolver}.py | SHA-256, texto nativo, fallback, PDF inválido/ilegível testados | Tabelas estruturadas e OCR nativo ainda não validados |
| 5 — Facts | engine/extraction/{normalizers,facts}.py | BRL, datas, CPF/CNPJ, percentual, booleanos, evidência e escopo testados | Associar documentos anteriores à RPV por regras explícitas de beneficiário/período |
| 6 — Reconciliation | rules/rules.json, crates/alma-core/src/reconciliation.rs | Todos os cinco resultados, precisão decimal e separação de escopo testados | Ampliar cobertura de campos mapeados |
| 7 — SQLite / execução | crates/alma-core/src/{store,runner,governor}.rs | WAL, persistência, recuperação, identidade, idempotência e commit atômico testados | Métricas CPU/RAM, filas/pools independentes e lote ainda pendentes |
| 8 — UI | apps/desktop/* | React/TypeScript/Zustand/Tailwind compilaram; comandos/eventos Tauri ligados ao núcleo no código | Compilação e execução nativa bloqueadas pelas bibliotecas do sistema |
| 9 — One RPV | tests/integration/test_e2e.py | Rust → Python → Chromium → DOM → download → PDF → fatos → reconciliação → SQLite passou com fixtures | Executar uma RPV real somente após descoberta autorizada |

Os arquivos acima foram criados no projeto novo; não houve substituição de
implementação anterior. README, contratos, motor e testes receberam ajustes
incrementais conforme os testes revelaram problemas.

## Verificações executadas

- Recorder existente: `npm test`, aprovado.
- Núcleo Rust: `cargo test`, **8 testes aprovados**.
- Worker/documentos/browser/integração: `.venv/bin/python -m pytest -q`,
  **24 testes aprovados**.
- Frontend: `npm run build`, TypeScript e Vite aprovados.
- Formatação Rust: `cargo fmt --all` e rustfmt no launcher Tauri.
- Desktop: `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml`,
  **bloqueado** na biblioteca nativa GLib; GTK/WebKit também não constam no
  pkg-config. `sudo -n apt-get install ...` foi autorizado, mas falhou por exigir
  autenticação interativa. Não foi declarado que Tauri iniciou.
- OCR real: **não executado**, Tesseract ausente; o fallback opcional está
  implementado, mas não é aceito como decisão automática sem confiança validada.
- eproc real: **não executado**, nenhuma sessão autorizada foi fornecida.

Testes de navegador e IPC tiveram falhas de sandbox na primeira execução;
passaram fora dele com autorização. O primeiro build Rust encontrou uma
conversão usize/SQLite incompatível, corrigida antes dos resultados acima.

## Evidência do ponta a ponta

Cada cenário abre um servidor loopback independente e inicia o binário Rust.
Rust inicia o worker por stdin/stdout JSONL. Playwright lê a RPV sintética e
baixa o PDF gerado no próprio teste. Nenhum valor extraído é injetado no Rust.

| eproc sintético | PDF sintético | Resultado de total_value |
|---|---|---|
| R$ 8.957,93 | R$ 8.957,93 | VALIDATED |
| R$ 8.957,93 | R$ 8.957,94 | DIVERGENT |
| R$ 8.957,93 | R$ 8.957,93 + página ilegível | NOT_VERIFIABLE |

Os testes reabrem SQLite e verificam relatório, página, evento, SHA-256,
quantidade de fatos e estado persistido. IRPF 330 × 370 e fontes conflitantes
são cobertos pelo teste Rust, mas **não** foi inventado seletor IRPF para fingir
essa cobertura no eproc real.

## Definition of Done solicitada

**Ainda não atingida.** O ciclo de percepção/reconciliação/auditoria existe e
foi exercitado com componentes reais em fixture. Os itens 1, 15 e 16 dependem
da execução nativa Tauri, ainda bloqueada. A leitura completa de beneficiários,
honorários e documentos e a fase 9 no ambiente real continuam pendentes.

A UI explicita cobertura desconhecida e não mostra métricas fabricadas de
economia, throughput ou RPVs integralmente validadas. A execução de lotes não
foi habilitada antes da validação de uma RPV real.

## Próxima etapa concreta

1. Instalar as bibliotecas nativas com autenticação local (comando no README).
2. Compilar/iniciar o Tauri e verificar os eventos na UI.
3. Abrir sessão autorizada em perfil dedicado e mapear os pontos de
   DISCOVERY.md, sem acionar Salvar, Intimar Partes ou finalizar/transmitir.
4. Expandir os testes sintéticos com a estrutura observada, validar uma RPV
   inteira e só então considerar 5, 10 e lote.
