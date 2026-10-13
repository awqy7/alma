# Leitura automática após login

Na aba **Revisar no eproc**, informe o endereço e o nome exato do localizador.
A opção **Ler todas as RPVs do localizador configurado** começa marcada.
Clique em **Abrir navegador eproc** e faça login normalmente no perfil ALMA.
A interface verifica a sessão a cada três segundos, sem pedir senha ou código.
Ao reconhecer login e unidade, inicia a fila sem exigir o botão Verificar login.

O Rust coordena a fila; o Python apenas navega, lê e extrai. A fila:

1. Abre o localizador configurado pelos links existentes na página.
2. Percorre paginação reconhecida, deduplicando números de processo.
3. Descobre as RPVs existentes de cada processo, inclusive várias no mesmo processo.
4. Lê uma RPV por vez, obtém documentos candidatos, extrai fatos, confronta e persiste evidências.
5. Registra exceções individuais e segue para o próximo item quando a falha não compromete a sessão.
6. Pausa em sessão expirada, mudança de unidade, mudança estrutural, timeout ou indisponibilidade HTTP.

Nenhuma ação de preenchimento, salvamento, intimação ou transmissão é chamada
pela fila automática. Processos acessíveis fora do localizador não são incluídos.
Cor de link visitado não é usada como sinal de conclusão.

## Retomada e cobertura

SQLite registra `review_queues` e `review_queue_items`. A chave do item combina
fila, processo e identificador de RPV encontrado no link. Após reinício, a fila
fica pausada. Ao conectar novamente e reconhecer a sessão, os links são
redescobertos e os itens concluídos são preservados. A fila pertence ao hash
da origem e da unidade selecionada; mudar de unidade não continua a fila anterior.

O controle **Pausar leitura automática** impede o próximo item. No desktop,
também sinaliza pausa entre etapas; no ensaio HTTP, aguarda a requisição corrente.
**Iniciar / continuar fila** retoma pendências. Uma fila encerrada pode ser
reexecutada por solicitação explícita, para revalidação.

“Analisada” não significa todos os campos corretos. Cada relatório informa
cobertura, divergências e campos não verificáveis. Beneficiários/honorários ainda
não possuem leitura completa com associação de identidade; o salvamento oficial
permanece bloqueado por essa precondição, inclusive no executor experimental.

## Limites verificáveis

- Até duas abas controladas, navegador serial e espaçamento entre comandos.
- Paginação por links existentes com `rel=next` ou semântica Próxima. Controles
  desconhecidos precisam de mapeamento; o limite de 100 páginas/10.000 processos
  gera exceção, não um falso resultado de leitura completa.
- Paginação da lista de requisições ainda não é percorrida; quando detectada,
  gera DISCOVERY_REQUIRED para aquele processo.
- PDF direto e HTML textual; visualizador embutido não mapeado interrompe a leitura.
- Nenhuma execução comprovada em sessão real: o usuário informou indisponibilidade.

## Testes

`tests/integration/test_queue.py` exercita Rust → JSONL → Python → Chromium →
DOM → PDF → reconciliação → SQLite. Cobre duas páginas, duas RPVs no mesmo
processo, processo sem requisição, retomada sem duplicação e sessão expirada.
`tests/browser/test_preview.py` verifica o disparo automático após login na UI;
somente nesse teste de interface o transporte é simulado. Não substitui o teste
integrado do motor nem homologação institucional.
