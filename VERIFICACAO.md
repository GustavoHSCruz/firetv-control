# Verificação — 26/10/2026

## Aparelho real

- Fire TV Stick de 3ª geração informado pelo usuário; modelo ADB `AFTSSS`.
- Fire OS `7.7.1.7 (PS7717/5741)`, Android 9, SDK 28.
- Conexão ADB de rede autorizada pelo usuário na TV (endereço local omitido).
- Android SDK Platform-Tools oficial `37.0.1-15733141`, ADB `1.0.41`.

Verificações concluídas no aparelho:

1. Conectar e lembrar o dispositivo autorizado.
2. Ler identidade, versão e armazenamento (aproximadamente 889 MB livres).
3. Listar 12 pacotes retornados por `pm list packages -3`.
4. Navegar no armazenamento compartilhado, com nomes e tipos das entradas.
5. Capturar PNG válido da tela pelo CLI e pelo painel.
6. Enviar um arquivo temporário ao diretório Download, copiá-lo ao PC,
   comparar os bytes e apagar da TV somente o arquivo criado pelo teste.
7. Enviar o comando Home do controle remoto.
8. Consultar a home atual e as três atividades HOME da Amazon. O parser foi
   ajustado para a indentação real de `query-activities --brief`.
9. Abrir a atividade real da home da Amazon pelo painel.
10. Percorrer o painel no navegador usando o dispositivo físico: identidade,
    apps, arquivos, componentes HOME e captura.

Home atual: `com.amazon.tv.launcher/.ui.HomeActivity_vNext`.
Os outros dois componentes HOME encontrados são auxiliares do sistema;
o painel os identifica e não oferece abertura direta deles.

Não foi instalado um launcher novo nem alterada a associação do botão Home.
Instalação/desinstalação de APKs e entrada de texto foram verificadas com a
fixture explícita, não com alterações nos aplicativos pessoais do aparelho.
A compatibilidade de um launcher alternativo e da troca permanente de Home
continua dependendo da escolha do app e do firmware.

## Testes locais

- 19 testes Python passaram: subprocessos, erros, validações, argumentos do
  shell, arquivos, desinstalação, persistência, concorrência e autenticação HTTP.
- Sintaxe JavaScript validada com `node --check`.
- Fluxo de navegador passou contra servidor HTTP e subprocesso de teste:
  conectar, controle, texto, PNG, aplicativos, instalar/desinstalar, enviar e
  baixar arquivos, abrir launcher, desconectar e layout de 390 px.
- Verificação do painel real no Chromium sem erros JavaScript.
- `git diff --check` sem erros. Binários, screenshots e caches ignorados no Git.

Evidências locais não versionadas em `artifacts/`:
`panel-real.png`, `firetv-real-before.png`, `firetv-real-home.png`,
`panel-desktop.png`, `panel-mobile.png`.

## Versão independente e Docker

- Projeto separado em um pacote `firetv_control`, sem dependência dos repositórios
  usados como referência. Wheel `firetv_control-0.2.0` construído e instalado.
- Skill de uso por agentes validada com o validador de skills.
- scrcpy 5.0.1 recebido da distribuição oficial com SHA-256 verificado.
- Gravação H.264 de aproximadamente 7,4 segundos confirmada em 1280×720;
  extração contínua de quadros JPEG confirmada no aparelho físico.
- Imagem Docker construída com Python 3.12, ADB e FFmpeg do Debian; o servidor
  scrcpy tem versão e SHA-256 fixados no Dockerfile.
- Container executado como UID 1000, sem capabilities, com raiz somente leitura,
  volume persistente e porta publicada somente em 127.0.0.1.
- Vídeo real no navegador por Docker confirmado em 1280×720, com novos quadros
  recebidos e comandos do controle remoto durante a transmissão.
- Acesso por favorito sem fragmento confirmado após a autorização por cookie.
- Reinício do container preservou chave do painel, cookie, identidade ADB e
  dispositivo; o vídeo voltou a iniciar sem nova autorização na TV.
- 19 testes unitários/de contrato passaram; fluxo completo de navegador contra
  fixture passou. A imagem iniciou e ficou healthy.
