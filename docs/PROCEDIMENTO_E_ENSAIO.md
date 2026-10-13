# Do procedimento relatado à conferência ALMA

O texto fornecido descreve o preenchimento manual de uma requisição e sua
tramitação. Não descreve fielmente o que o MVP já executava. O vídeo não foi
reexaminado nesta alteração: os tempos, valores e cliques citados são do relato
do usuário. “Preparar transmissão” não pode ser tratado como etapa observada.

## Procedimento de conferência, com limites explícitos

1. O funcionário autentica no eproc em perfil dedicado. O localizador e a RPV
   precisam ser identificados com segurança; a navegação completa ainda requer
   descoberta. Não existe clique por coordenadas.
2. Identificar os documentos do cálculo/proposta e da solicitação do perito.
   PROACORDO/PGTOPERITO são pistas, não uma lista fechada de arquivos nem prova
   de vinculação ao beneficiário.
3. Ler cada documento e preservar texto, posição, página e SHA-256. Separar
   observações de conclusões: um valor encontrado não é uma RPV validada.
4. Procurar o total dos atrasados e o valor **solicitado** ao perito. “Valor do
   acordo”, valor já pago, percentual, desconto e saldo são conceitos diferentes.
5. Localizar data da proposta e data-base separadamente. Aplicar a regra confirmada pelo usuário: mês/ano da proposta, preservando
   a data original e a evidência. Havendo conflito com data-base explícita, parar.
6. Para o cenário relatado, apresentar a soma aritmética de 2.400,00 + 390,00 =
   2.790,00, mantendo visíveis as duas fontes. Essa conta não confirma, por si só,
   que a regra institucional manda compor o total com essas duas parcelas.
7. Comparar o resultado aos dados lidos do eproc, quando mapeados. No ensaio
   local, comparar **aos valores digitados pelo testador**, claramente identificados.
8. Mostrar ao funcionário a diferença, a razão da conclusão e as fontes. Só
   acionar a pessoa onde existir dúvida, divergência ou cobertura incompleta.
9. O usuário solicitou também execução supervisionada. Seu plano está disponível,
   mas o executor de salvamento real ainda depende do DOM autorizado. Intimação
   e transmissão não são automáticas; nenhuma dessas ações foi enviada pelo ensaio.

“RPV Original”, juros “Não incidem”, IRPF-RRA “Não”, ausência de destaque e
“Devolução à Seção Judiciária” são configurações observadas em um caso. Sua
aplicabilidade precisa de regra institucional e contexto, não de repetição
visual do vídeo. A ALMA não as generaliza automaticamente.

## Versão para testar agora

```bash
cd /home/awqy/alma
./testar.sh
```

Abrir `http://127.0.0.1:4318`. O script compila o frontend e o núcleo Rust e
inicia um servidor restrito ao loopback. Isso permite testar sem GTK/WebKit.
No ensaio o transporte é React → HTTP local Rust → JSONL Python. No desktop
permanece React → Tauri IPC → Rust → JSONL Python. Não há React → Python.

Na tela **Ensaiar documentos**, enviar de 1 a 4 PDFs ou HTMLs UTF-8, até 8 MB cada, e opcionalmente
digitar total/data-base que constam no cadastro. Ou abrir “Testar agora com
documentos fictícios”. São sete cenários: normal, layout alternativo, conflito
entre valores, ausência de data-base explícita, gravação HTML + AJG, processo
divergente e múltiplos pedidos de perito. Os PDFs fictícios são criados e lidos
durante a execução; não há relatórios prontos ou números injetados na interface.

Para reproduzir o retrabalho do relato: informar total **2.400,00** e data-base
**10/2026**, executar o cenário normal. O resultado identifica **2.790,00** e
**09/2026** e mostra duas diferenças. O exemplo também contém data da proposta
**21/09/2026**, distinguindo-a da competência usada como data-base.

O ensaio não abre navegador eproc, não autentica, não faz download remoto,
não altera processo e não persiste os PDFs. O worker remove os temporários ao
terminar. O relatório fica na tela; “Baixar relatório” permite guardá-lo
localmente. **O ensaio não grava histórico SQLite automaticamente.**

A aba **Revisar no eproc** preserva o modo de leitura operacional via Tauri.
Durante a execução, há eventos, pausa, estado e evidências. Continua limitada
pelos pontos de DISCOVERY.md e pelas dependências nativas ainda não instaladas.
A aba **Execução supervisionada** prepara campos e impedimentos, sem executar
salvamento. A autorização posterior para as duas versões ampliou o escopo;
a habilitação real depende dos pontos concretos em [RECORDED_SPEC.md](RECORDED_SPEC.md).

## Reconhecimento de PDFs de escritórios diferentes

A leitura não depende da posição fixa do mouse nem de um modelo visual único.
O extrator aceita rótulos explícitos equivalentes, ignora diferenças de caixa
e acentuação e usa a geometria do texto para reunir células na mesma linha.
Também aceita rótulo e valor em linhas adjacentes, sob condições restritas.

- Atrasados: “total dos atrasados”, “valor dos atrasados”, “montante das
  parcelas vencidas”, “total das parcelas vencidas”.
- Perito: requer contexto de pedido/solicitação; “honorários periciais” sozinho
  é insuficiente para afirmar que se trata do valor requisitado.
- Datas: DD/MM/AAAA, MM/AAAA e dia/mês por extenso. Preserva precisão: mês não
  vira primeiro ou último dia por suposição.
- Negação, pagamento já realizado, cancelamento ou múltiplos números tornam
  o contexto incerto. Fontes com valores diferentes são mostradas juntas.
- Qualquer página sem leitura utilizável impede concluir automaticamente.
  OCR de baixa confiança também impede seleção.

Limites: não é compreensão universal de qualquer petição. Texto livre sem
rótulos reconhecidos, tabelas complexas, múltiplos beneficiários e documentos
digitalizados ainda exigem ampliação/validação. OCR já existente permanece
opcional; no ensaio desta versão está desativado e páginas sem texto são
marcadas como não verificáveis. Nenhum LLM ou ML toma decisões.

Para ampliar cobertura, adicionar exemplos **anonimizados/sintéticos** de cada
variação, definir o significado exato do campo, ajustar o extrator e acrescentar
teste que prove tanto o acerto quanto a rejeição de uma fonte ambígua.

## Interface

Paleta: azul institucional #142d4e/#245cbb, fundo #f4f7fb, confirmação #176e50,
atenção #895511 e divergência #a1372f. Tipografia do sistema para leitura longa.
Mesa de trabalho: arquivos/comparação no topo, resultados relevantes, fontes
ao lado e trilha do que foi executado. O destaque principal é a diferença
documental, não um painel de métricas artificiais.

O funcionário vê valor, data, trecho e documento. Detalhes técnicos ficam
recolhidos em “Rastreabilidade”. Campos informativos ausentes não são exibidos
como pendências obrigatórias. A interface não chama uma decisão jurídica de
“decisão da ALMA”.

Detalhamento da gravação, limites atuais e regra confirmada: [RECORDED_SPEC.md](RECORDED_SPEC.md).
