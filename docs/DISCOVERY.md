# Descoberta a partir dos logs locais

Somente metadados de código foram usados. Valores, URLs completas e documentos
reais não foram copiados. `eproc-recorder` permanece intacto.

Confirmados no inventário: `#txtNumProcesso`, `#txtValorTotal`, datas,
componentes financeiros e de honorários no registry. Também foram observados
`#selInfraUnidades` (estrutura do painel), `#txtNumRequisicao` (input hidden),
`#txtCpfCnpjBenefi` (input hidden), `#selPessoaRequerido` (select).

A gravação contém ações `oficio_requisitorio_requisicoes_cadastrar`,
`oficio_requisitorio_requisicoes_editar` e
`oficio_requisitorio_beneficiarioshonorarios_editar`.
Esses nomes não são autorização para acioná-las automaticamente: GET também
pode produzir efeitos. Não foram copiados endpoints nem parâmetros.

## DISCOVERY_REQUIRED

- Origem autorizada do ambiente alvo e confirmação do marcador de sessão.
- Links de localizador/processo, paginação e identificação estável da RPV.
- Abertura somente leitura do ofício, inclusive modais e abas secundárias.
- Escopo de cada beneficiário/honorário: mesmos IDs reaparecem em formulários.
- IRPF: o log tem seletores de deduções, mas a semântica exata e o valor não
  podem ser inferidos dos nomes. Não foi inventado `#txtIRPF`.
- Índice de eventos: associação inequívoca evento/documento, links/popup de
  download e regras para distinguir documentos revisados ou substituídos.
- HAR sanitizado está desabilitado; não há captura de corpos, cookies ou headers.

O adapter lê RPVs abertas manualmente ou pela fila automática. Navegação, paginação semântica, índice documental e download de links diretos estão implementados; visualizadores não mapeados e cobertura de itens continuam pendentes. Consulte AUTOMATIC_REVIEW.md para o escopo atual.
O adapter de teste usa Chromium real e um servidor loopback sintético explícito.
Seu modo não aceita hosts remotos. Não é fallback silencioso para produção.

O parser inicialmente reconhece linhas explicitamente rotuladas. Não associa
um valor sem escopo a um beneficiário por proximidade ou por suposição.
