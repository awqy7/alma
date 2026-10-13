# Verificação crítica — 09/10/2026

## Conclusão verificável

A ALMA possui componentes operacionais e uma demonstração integrada. **Ainda
não possui um executor homologado de alterações no eproc.** Empacotar o programa
ou demonstrar preenchimento em servidor local não muda essa conclusão.

O usuário confirmou não haver sessão eproc disponível agora. Não houve login,
download autenticado, salvamento ou intimação no ambiente judicial nesta etapa.
O desenvolvimento das duas modalidades está autorizado; a indisponibilidade
de sessão impede somente comprovar e habilitar o fluxo oficial pendente.

## Evidência examinada

Código Rust/Python/React, testes existentes, contratos, SQLite, empacotamento e
snapshots DOM do recorder de 08/10. Os snapshots reais permanecem fora do Git.
Foram examinados nomes de campos, tipos, opções e nomes de parâmetros de links;
não foram copiados valores de partes, tokens, hashes de autenticação ou documentos.

A descrição do vídeo, isoladamente, não dá escopo de formulário, resultado de
POST, identidade de item ou garantia de salvamento. Os snapshots complementam
parte desse mapeamento, mas representam observação histórica, não homologação.

## Achados e melhorias aplicadas

| Área | Achado | Alteração / situação |
|---|---|---|
| Empacotamento | Release dependia do checkout e `.venv` | Runtime próprio, Chromium incluído, caminho instalado explícito e teste fora do checkout |
| Desktop Linux | Apenas build web havia sido validado | Tauri nativo compilado, `.deb` gerado e janela aberta no Ubuntu 26.04 x64 |
| Processo | Edição tem campo visível `txtNumProcessoView` e campo oculto `txtNumProcesso` | Prioridade explícita para o valor visível e fallback observado |
| Requerido | Cadastro usa select; edição usa input | Resolver aceita as duas formas e lê o tipo correto |
| Sessão | Referência fixa à aba inicial; marcadores duplicados ocultos | Busca de RPV nas abas do contexto, ambiguidade bloqueada; marcador autenticado precisa estar visível |
| Diálogos | Não havia política explícita para alertas | Apenas aviso informativo observado é aceito; confirmação inesperada é cancelada e bloqueia rotina |
| Navegação | Métodos eram somente DISCOVERY_REQUIRED | Localizador → lista → processo → RPV pelos links existentes no DOM, sem montar endpoint |
| Limites de navegação | Risco de seguir link incorreto | Origem e ação permitidas verificadas; processos vinculados pelo número; nenhuma cor de link define conclusão |
| Documentos | Índice real inexistente | Índice a partir de links observados da página do processo e identidade coincidente; URLs ficam no worker |
| Download documental | Havia bloqueio integral | Leitura GET do link já indexado, pela sessão autorizada; PDF direto e HTML suportados. Redirects/login interrompem; visualizador embutido não mapeado continua bloqueado |
| Demonstração | Só conferência de documentos | Pipeline executa leitura, regra Rust, DOM, três POSTs locais, reload e comparação do resultado salvo |
| Isolamento demo | Risco de confundir simulação com execução oficial | Servidor próprio loopback, browser separado sem perfil real, indicador DEMO, zero alterações oficiais |
| Auditoria demo | Sem registro de execução | Banco separado escrito pelo Rust; RUNNING/COMPLETED/FAILED/INTERRUPTED; captura final e resultado |
| Interface | Não explicitava toda a cobertura do modo real | Modo real identificado como leitura parcial; campos de fila/processo e bloqueios visíveis |

A navegação foi testada com páginas sintéticas e os nomes observados no DOM.
O download usa os links exatos do índice e não constrói endpoints. Os testes locais exercitam cookie sintético, origem, identidade, HTML/PDF, login, redirect e 429. Nenhum download em sessão judicial real foi realizado.
O formulário de apresentação é **simplificado**: demonstra componentes e ações,
mas não reproduz integralmente modais, máscaras, alertas e regras do eproc.
IDs exclusivos da demonstração, como `txtValorTotalBenefi`, não são seletores
oficiais e não foram adicionados ao registry do eproc.

## Bloqueios para alterar uma RPV real

1. **Sessão e alvo de homologação.** Confirmar unidade, perfil, processo, status
   e requisição/rascunho corretos. Capturar apenas metadados técnicos necessários.
2. **Documentos autenticados.** Validar proposta HTML, PDF direto, visualizador,
   redirects e expiração. Comprovar o vínculo ao processo e ao beneficiário.
3. **Leitura completa antes da escrita.** Beneficiários, honorários e deduções
   precisam de identidade e cobertura conhecida. Hoje o core ainda informa
   `unknown` nessas seções; não presume que estão vazias.
4. **Regras por cenário.** A data-base foi confirmada: mês/ano da proposta.
   Composição da devolução, juros, IRPF, destaque, natureza e beneficiários não
   podem ser generalizados de um caso. Condições fora do padrão devem bloquear.
5. **Plano imutável e aprovação específica.** Congelar snapshot, documentos,
   hashes, versão de regra e valores propostos. Mostrar antes/depois e exigir
   confirmação do plano antes de sua primeira execução oficial.
6. **Executor de escrita e journal.** Persistir intenção ANTES do clique; após
   salvar, obter identidade/estado do item e reler a lista. Timeout depois de
   um POST significa resultado desconhecido, não autorização para repetir.
7. **Recuperação idempotente.** Ao retomar, verificar o item existente. Não criar
   outro beneficiário/honorário por ter perdido uma resposta. A idempotência
   atual dos relatórios de leitura não resolve idempotência de gravação oficial.
8. **Homologação dos casos adversos.** Alerta inesperado, aba trocada, sessão
   expirada entre preencher e salvar, DOM alterado, dois beneficiários, dois
   peritos, documento substituído, interrupção após cada salvamento e mudança
   manual por outro funcionário.

Sem os itens acima, habilitar um botão “modo real” que apenas chama `click()`
seria uma falha de engenharia. Os seletores observados reduzem o trabalho de
mapeamento, mas não comprovam todas as precondições e pós-condições.

## Critérios para a primeira execução oficial

- Uma única RPV de homologação, sem lote.
- Antes/depois de cada campo, com fonte e regra registradas.
- Confirmação de salvamento pela reabertura/leitura do item, não só por alerta.
- Nenhum salvamento repetido após resultado desconhecido.
- Interrupção testada em cada fronteira de gravação.
- Funcionário consegue identificar o que foi executado e o que ficou pendente.
- Intimar, finalizar e transmitir continuam separados e desabilitados.

## Limitações restantes além do salvamento

OCR não está incluído no pacote de teste; PDF sem texto exige revisão. Extração
por rótulos/tabelas simples não cobre toda variação de petições. Associação de
múltiplos beneficiários e precedência de documentos ainda precisam de regras.
Pools CPU/RAM, lote institucional e métricas de economia não foram homologados.
O servidor HTTP de ensaio é local e serial; o desktop usa Tauri IPC.

O instalador Windows ainda requer compilação e teste em Windows. O Linux aqui
foi compilado no Ubuntu 26.04; compatibilidade com versões anteriores não foi
comprovada. Uma janela aberta não é prova de todos os fluxos de WebView2/GTK.

## Incremento: aquisição e relatório integrado

- `engine/browser/eproc/documents.py`: aquisição pela sessão existente, apenas do link indexado. Nenhum cookie é exportado, nenhuma URL autenticada vai para auditoria. Redirecionamento não é seguido; login e resposta inválida não viram documento.
- `engine/worker.py`: identifica HTML/PDF, preserva bytes e SHA-256, extrai candidatos com evento e posição. Documento HTML tem localização DOM e página nula, nunca página inventada.
- `runner.rs`: agrega a percepção, executa a regra Rust, confronta a soma com o cabeçalho lido e persiste `document_review` no mesmo relatório SQLite. A classificação aritmética não valida a composição jurídica.
- Antes da persistência, releitura da RPV detecta mudança de identidade ou cabeçalho (`SNAPSHOT_CHANGED`). Não cobre modificações nos itens ainda não lidos.
- `Operations.tsx`: apresenta valores, datas, soma, origem, evento, trecho e hash; impede mudança de modo durante a operação.
- Teste integrado obtém proposta HTML + pedido AJG PDF por Chromium, calcula 2.790,00 em Rust, detecta divergência contra 2.400,00 e verifica relatório persistido. Outro caso altera o cabeçalho durante a leitura e verifica que nenhum relatório é persistido.

**Escopo ainda pendente:** leitura completa dos itens continua pendente; o executor experimental acrescentado pelo usuário ainda não satisfaz as precondições de salvamento oficial. A demonstração executa salvamentos somente em seu servidor sintético. Não foi declarada homologação nem habilitada escrita oficial.

## Fila automática e alterações do usuário

A contribuição do usuário acrescentou leitura tabular preliminar, HTTP local para sessão e um executor experimental de preenchimento. Esses arquivos foram preservados e corrigidos incrementalmente. Descoberta indiscriminada de localizadores, URL de processo construída sem link e identificador de RPV inventado foram removidos. O executor não substitui tipo 51 por honorário de outra natureza e recusa produção enquanto a identidade/cobertura de itens estiver incompleta. Seus testes locais não comprovam gravação judicial.

A fila automática agora usa `queue.rs` e `queue_navigation.py`, com SQLite, retomada e várias RPVs por processo. Login detectado na UI inicia a fila do localizador selecionado. Consulte [AUTOMATIC_REVIEW.md](AUTOMATIC_REVIEW.md). A fila automática nunca chama o executor de escrita.

## Verificação final da fila — 09/10/2026

- `cargo test -p alma-core`: 12 testes aprovados.
- `.venv/bin/pytest -q`: 60 testes aprovados.
- `npm run build`: TypeScript e Vite aprovados.
- Worker congelado: JSONL, HTML, PDF, Chromium e cleanup aprovados fora do checkout.
- Build Tauri release Linux: compilado com os comandos de fila. O teste instalado e o recibo ficam no diretório `release/linux` após o empacotamento.

Arquivos novos principais: `queue.rs`, `queue_navigation.py`, `documents.py`, `test_queue.py`, `test_document_acquisition.py`, `test_document_review.py`. Alterações principais: adapter, session, worker, runner, store, frontend Operations, comandos Tauri e transporte local. Próximo passo externo: homologar a fila e os seletores em uma sessão autorizada; a execução local não comprova comportamento do eproc judicial.

Pacote final Ubuntu gerado e executado: `.deb` de aproximadamente 427 MiB, `package-smoke.json` aprovado (worker, restart, JSONL, HTML, PDF, reconciliação, SQLite, demo/Chromium). Janela nativa aberta em Xvfb e conferida visualmente. Atalho local `ALMA — Teste local` aponta para o pacote atualizado. Recibo e captura em `release/linux`. Windows segue sem binário gerado nesta máquina.
