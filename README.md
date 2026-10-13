# ALMA

**Leitura automática após login:** na aba Revisar no eproc, configure o localizador, abra o navegador e faça login. A ALMA inicia a fila em leitura, uma RPV por vez, com retomada e auditoria. [Uso e limites](docs/AUTOMATIC_REVIEW.md). Integração ainda não homologada em sessão judicial.

**Novo: ensaio funcional com seus PDFs, sem acessar o eproc.** Execute
`./testar.sh` e abra `http://127.0.0.1:4318`. Use arquivos locais ou os sete
cenários fictícios processados pelo motor. [Procedimento, reconhecimento e
modos de uso](docs/PROCEDIMENTO_E_ENSAIO.md).

Núcleo local de conferência documental de RPVs. Projeto novo, independente do
`eproc-recorder`, que foi preservado. Sem LLM, cloud ou escrita no eproc.

**Estado atual:** núcleo executável, demonstração com leitura/DOM/salvamentos
fictícios/releitura/auditoria e aplicativo Tauri aberto no Ubuntu.
A demonstração é isolada: não altera processos oficiais.
Não é ainda uma RPV inteira validada em produção. A integração completa com o
eproc depende dos pontos documentados em [DISCOVERY.md](docs/DISCOVERY.md).

A regra confirmada de data-base e os limites do plano supervisionado estão em
[RECORDED_SPEC.md](docs/RECORDED_SPEC.md).

## Executar os testes

Requer Python 3.11+, Rust e um navegador Playwright. No ambiente atual as
dependências Python e Rust do núcleo já estão instaladas.

```bash
cd /home/awqy/alma
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m playwright install chromium
~/.cargo/bin/cargo test
.venv/bin/python -m pytest -q
```

Os testes integrados iniciam um servidor **loopback**, Chromium, o binário Rust
e o subprocesso Python. O servidor serve HTML/PDF sintéticos gerados para cada
teste. São conferidos relatório, evidência e auditoria SQLite. Não usam eproc,
credenciais nem dados judiciais reais. Ambientes com sandbox precisam permitir
servidor local e subprocessos para esses testes.

## Worker JSONL

```bash
.venv/bin/python -m engine.worker
```

Enviar uma linha por comando:

```json
{"version":1,"id":"00000000-0000-4000-8000-000000000001","type":"COMMAND","name":"PING","payload":{}}
```

Comandos: PING, CONNECT, CHECK_SESSION, DISCOVER_PROCESSES, OPEN_LOCALIZER,
LIST_PROCESSES, OPEN_PROCESS, LIST_REQUISITIONS, OPEN_REQUISITION, READ_PROCESS, READ_REQUISITION,
INDEX_DOCUMENTS, DOWNLOAD_DOCUMENT, PARSE_DOCUMENT, CLOSE_PROCESS,
START_DIAGNOSTICS e STOP_DIAGNOSTICS. Logs não usam stdout.
Sem sessão, a leitura falha com REAUTH_REQUIRED. Navegação não mapeada falha
com DISCOVERY_REQUIRED. `--fixture-mode` é exclusivo para testes loopback.

## Desktop de desenvolvimento

```bash
cd apps/desktop
npm ci
npm run build
PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev
```

No desktop o frontend usa IPC Tauri; no ensaio usa HTTP loopback para Rust. Nunca chama Python diretamente. `npm run dev`
sozinho não inicia o motor e mostra essa limitação, sem fabricar dados.

Historicamente, a compilação nativa ficou bloqueada por dependências ausentes.
Em 09/10 ela foi concluída usando headers extraídos em sysroot local, sem
instalar pacotes no sistema. Em outra máquina de desenvolvimento Ubuntu,
as dependências podem ser instaladas pelo procedimento abaixo.
A instalação foi autorizada, mas `sudo -n` respondeu que exige autenticação.
Executar no terminal local, sem compartilhar a senha:

```bash
sudo apt-get install libwebkit2gtk-4.1-dev libgtk-3-dev libxdo-dev libssl-dev librsvg2-dev
```

Referência: [pré-requisitos oficiais Tauri 2](https://v2.tauri.app/start/prerequisites/).
O empacotamento usa motor congelado e Chromium incluído. O pacote Ubuntu foi
gerado nesta máquina; o Windows tem geração automatizada preparada e ainda
precisa ser compilado/testado no Windows. Ver [WINDOWS.md](docs/WINDOWS.md) e
[PRODUCTION_AUDIT.md](docs/PRODUCTION_AUDIT.md).

## Regras e limites

- Valores monetários são strings no IPC, `Decimal` no Python e `rust_decimal`
  no Rust. Igualdade exata; nenhuma tolerância inventada.
- A leitura da seção principal usa seletores observados nos logs. Beneficiários
  e honorários ainda têm cobertura `unknown`; não são tratados como inexistentes.
- Documentos sem escopo comprovado, páginas ilegíveis e OCR de baixa confiança
  não produzem VALIDATED. Fontes conflitantes são preservadas para revisão.
- O parser reconhece linhas explicitamente rotuladas. Inicialmente exige
  identificadores explícitos de processo e requisição para comprovar escopo.
  Documentos anteriores à RPV geralmente precisarão de regras de associação
  por beneficiário/período, ainda não habilitadas.
- PyMuPDF primeiro; pdfplumber para fallback de texto; OCR opcional. Extração
  estruturada de tabelas ainda não habilitada. OCR requer
  `pip install -e '.[ocr]'`, Tesseract e idioma português. Não foi validado nesta
  máquina porque o binário nativo está ausente.
- Um worker serial: no máximo um job de navegador e um PDF/OCR por vez.
  Há timeout, backoff e circuit breaker. Pools independentes, métricas CPU/RAM
  continuam pendentes; a fila automática de leitura está implementada e testada localmente, aguardando homologação.
- Rust é o único escritor da auditoria. SQLite WAL guarda snapshot, fatos,
  relatório, fontes e estados. Reinício pausa jobs interrompidos; retomada
  relê e confirma a mesma RPV. Estado VALIDATED significa término do pipeline,
  não que todos os campos tenham sido validados; consulte cada status/cobertura.
- Perfil dedicado em diretório de dados do usuário, criado por `platformdirs`.
  Nenhuma captura de senha, cookies ou armazenamento do navegador.
- Diagnóstico opt-in registra apenas metadados com URL reduzida à origem;
  caminho, query e fragmento são omitidos. HAR está desabilitado.

Auditoria inicial: [CURRENT_STATE.md](docs/CURRENT_STATE.md).
Resultados por fase: [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).
