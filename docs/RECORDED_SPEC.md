# Procedimento da gravação e implementação

Fonte: especificação textual fornecida pelo usuário. O vídeo não foi revisto
nesta alteração. A descrição distingue observações, inferências e lacunas;
não serve como prova de que um seletor ou uma regra funciona em todo processo.

## O que corresponde ao código

| Etapa | Implementação atual | Limite |
|---|---|---|
| Proposta em HTML | Leitura local de DOM estático, tabelas, rótulos e fecho | Não navega até o documento real automaticamente |
| Pedido AJG em PDF | Texto nativo, geometria, valor requisitado, processo, tipo, atuação, réu | Layouts não reconhecidos exigem revisão |
| Atrasados + pedido de perito | Soma decimal exata no Rust, duas fontes preservadas | Aritmética não confirma obrigação de devolução |
| Processo dos documentos | Comparação com CNJ informado, com/sem pontuação | Não valida dígitos verificadores nem identidade do beneficiário |
| Data-base | Mês/ano da proposta, regra confirmada pelo usuário nesta sessão | Conflito documental impede conclusão |
| Relatório para funcionário | Valores, comparação, motivo, evidência e plano proposto | Ensaio não grava histórico SQLite automaticamente |
| Leitura do eproc | Sessão dedicada e seção principal com seletores observados | Navegação, índice real, beneficiários e honorários ainda DISCOVERY_REQUIRED |
| Preencher e salvar | Executor real implementado: cabeçalho, beneficiário (#ifrSubFrm), honorários, releitura e screenshot | Testado somente com mock eproc; validação em sessão autorizada pendente |
| Intimar/transmitir | Fora do executor | Não é acionado por nenhum modo |

## Regra de data-base confirmada

O usuário confirmou **mês/ano da data da proposta**. A configuração fica em
`rules/recorded_procedure.json`, `RPV_PROPOSAL_MONTH_V1`, versão 1, com origem
`user_in_session`. Exemplo sintético: 12/09/2026 → 2026-09 → 09/2026 na UI.
A data de juntada, DIB, DIP, DCB e a data do pagamento não substituem a proposta.

A extração preserva a data completa e seu trecho. Rust deriva o mês. Se uma
data-base explícita discordar, ou as fontes trouxerem datas diferentes, não
existe valor escolhido automaticamente. O relatório contém regra, versão,
derivação e evidência. A confirmação desta regra não autoriza deduzir regras
tributárias ou de honorários de um único exemplo.

## Duas modalidades solicitadas

**Ensaio:** executar leitura e comparação reais em arquivos locais, sem ação no
eproc. Aceita PDFs e HTML UTF-8; sete cenários sintéticos são gerados e lidos
pelo motor. Não usa resultados prontos.

**Execução supervisionada:** preparar o plano dos campos, mostrando de onde
vieram e o que impede executar. A aba existe e usa os mesmos dados reais do
motor. O executor de escrita (`apply_eproc_plan`) está implementado e testado
com mock eproc: preenche cabeçalho, beneficiário e honorários via subform
iframe, faz releitura de verificação e captura screenshot. A autorização do
usuário para desenvolver as duas modalidades está registrada.

Para habilitar em produção faltam: validação em sessão autorizada com RPV real,
confirmação de que seletores correspondem ao DOM de produção, e verificação de
idempotência em caso de falha parcial. Intimação permanece separada e não
automática.

## Ajustes necessários na narrativa do vídeo

- Link roxo significa histórico de navegação, não processo concluído. A fila
  da ALMA deve usar sua própria auditoria e identidade de processo/requisição.
- Há cinco tipos de diálogo no relato, mas seis ocorrências, pois o beneficiário
  foi salvo duas vezes. Confirmação de intimação não é um aviso informativo.
- Valor requisitado só vira candidato de perito no contexto AJG/solicitação.
  O nome PGTOPERITO é pista; não é prova suficiente.
- Dois pedidos com o mesmo valor continuam sendo dois pedidos. Não deduplicar
  por valor, escolher o primeiro ou somar silenciosamente.
- A proposta pode ser HTML; não atribuir página PDF fictícia. Evidência HTML
  guarda localização na árvore, seção, texto e hash.
- O caso anterior mostra estado final; não é uma segunda execução completa.
- Com máscara de centavos, 240000 representa 2.400,00; a menção a 24000 no
  relato é inconsistente. Futuro executor deverá ler de volta após preencher.
- Preparar transmissão aparece como opção; seu acionamento não foi observado.

## Reconhecimento e limites

Rótulos equivalentes, caixa/acentuação, células na mesma linha e pares
rótulo/valor adjacentes permitem variação entre escritórios. Ausência, leitura
ilegível, negação, valor zero/negativo, múltiplos valores e fontes conflitantes
não são resolvidos por adivinhação. Novas variações exigem exemplos sintéticos
e testes de acerto e rejeição.

HTML não é aberto como página executável: scripts, iframes e elementos ocultos
conhecidos são excluídos; nenhum recurso remoto é buscado. A UI mostra texto
escapado. O ensaio não usa OCR; PDF sem texto utilizável exige revisão. OCR
opcional já existe no pipeline operacional, mas precisa de instalação/calibração.
