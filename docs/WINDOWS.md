# Instalador Windows para o funcionário

Alvo confirmado: Windows 10/11 x64. O produto de entrega é
`ALMA-0.1.0-windows-x64-setup.exe`, com interface de instalação em português,
atalho ALMA no Menu Iniciar e desinstalador. O funcionário não precisa de
Python, Node, Rust ou terminal.

## Estado desta entrega

O fluxo de empacotamento foi implementado; **ainda não há instalador Windows
gerado/testado nesta máquina Linux**. O motor congelado foi gerado e executado
no Linux, inclusive depois de movido para outro diretório com espaço no nome.
Esse teste não substitui compilar e instalar no Windows, nem verificar a janela
Tauri/WebView2. O workflow abaixo somente disponibiliza artefato após seus
checks passarem. A janela requer também a conferência manual indicada abaixo.

## O que vai dentro

- Frontend compilado e aplicativo Tauri/Rust.
- Python e bibliotecas do worker em pacote PyInstaller onedir.
- Chromium compatível com o Playwright do worker, em recursos do aplicativo.
- Instalador offline do WebView2; não baixa dependências ao abrir a ALMA.
- Regras determinísticas compiladas no Rust.

Não vão dentro: documentos judiciais, logs de engenharia, banco de processos,
credenciais, perfil do navegador, `.venv`, código do recorder. Os exemplos são
sintéticos e gerados em tempo de execução. OCR não está incluído nesta versão.
O tamanho do instalador será maior por incluir Chromium e WebView2.

Auditoria vai para o diretório de dados do usuário resolvido por Tauri; o
perfil dedicado permanece no diretório resolvido por platformdirs. Nem banco
nem downloads são escritos em Program Files ou na pasta da instalação.
Atualizações/desinstalação não apagam deliberadamente esses dados de trabalho.

## Gerar uma vez em um computador de desenvolvimento Windows

Pré-requisitos **somente da máquina que gera o instalador**: Python x64
(recomendado 3.12), Node 22, Rust estável para MSVC e Visual Studio Build Tools
com ferramentas C++/Windows SDK. Internet necessária durante a compilação.

No PowerShell, na pasta extraída do projeto:

```powershell
.\scripts\build-windows.ps1
.\scripts\test-windows-install.ps1
```

Se a política institucional bloquear scripts, solicitar execução à TI; os
scripts não alteram essa política. Não é necessário desativar a proteção do
Windows. O instalador de teste não possui assinatura digital: eventual assinatura
institucional deverá ser configurada com certificado autorizado antes da
ampla distribuição.

A primeira etapa instala dependências em `.venv`, executa testes, congela o
worker, inclui Chromium, testa o worker isolado e produz o instalador NSIS.
A segunda instala em diretório temporário, executa o aplicativo em modo de
verificação (Rust → worker → documentos → regras → SQLite), verifica o Chromium
instalado e desinstala o teste. Ela não abre uma sessão real nem acessa o eproc.

Saídas em `release/windows/`:

- `ALMA-0.1.0-windows-x64-setup.exe`
- `SHA256SUMS.txt`
- `installation-check.json` após o teste de instalação
- `LEIA-ME.txt`

## Gerar automaticamente no GitHub

Workflow `.github/workflows/windows-installer.yml`, execução manual
`workflow_dispatch`. Depois de colocar o projeto em repositório autorizado,
abrir Actions → Instalador ALMA Windows x64 → Run workflow. Baixar o artefato
`ALMA-Windows-x64` quando a execução terminar com sucesso.

O workflow usa runner Windows e não publica release, site ou dados judiciais.
Nenhum repositório remoto foi criado e nenhum código foi enviado nesta sessão.
Permissão do job: leitura do conteúdo. O artefato expira em 14 dias.

## Conferência manual antes de entregar

1. Em Windows de teste, instalar o setup e abrir ALMA pelo Menu Iniciar.
2. Confirmar que abre a janela sem terminal e sem exigir Python/Node.
3. Ensaiar com a opção “Gravação: proposta HTML + pedido AJG em PDF”.
4. Conferir 2.400,00 + 390,00 = 2.790,00 e 12/09/2026 → 09/2026.
5. Fechar/reabrir; verificar que o motor reinicia normalmente.
6. Consultar evidência PDF e HTML na janela WebView2.
7. Confirmar que salvamento/intimação continuam indisponíveis neste MVP.

O instalador distribui as funções existentes. Ele não implementa o salvamento
supervisionado nem resolve os pontos DISCOVERY_REQUIRED do eproc.

## Referências de empacotamento

- [Instaladores Windows no Tauri](https://tauri.app/distribute/windows-installer/).
- [Recursos embarcados do Tauri](https://v2.tauri.app/develop/resources/).
- [Playwright e PyInstaller](https://playwright.dev/python/docs/library#pyinstaller).
- [PyInstaller: builds por plataforma](https://www.pyinstaller.org/en/stable/usage.html).
