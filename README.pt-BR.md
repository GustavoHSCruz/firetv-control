# Fire TV Control

Aplicativo independente para gerenciar um Fire TV com **Fire OS** pelo PC.
Possui painel em português, vídeo ao vivo no navegador e comandos de terminal.
CLI-Anything e REA foram referências de criação; não são dependências.

## Usar com Docker

```sh
cp .env.example .env
# Coloque o IP do Fire TV em FIRETV_DEVICE dentro do .env.
docker compose up -d --build
docker compose logs firetv
```

Abra uma vez o endereço completo com `/#...` mostrado no log. O navegador recebe
um cookie de acesso e depois você pode salvar **http://127.0.0.1:8765/** nos
favoritos. A chave do painel, a identidade ADB e o aparelho escolhido ficam no
volume persistente. A primeira conexão exige aceitar a autorização na TV.

O serviço usa `restart: unless-stopped`: continua funcionando depois de fechar
o terminal e volta quando o Docker inicia. O Docker precisa estar configurado
para iniciar com o computador. Para interromper: `docker compose stop`. Para
voltar: `docker compose up -d`. Evite `down --volumes` se quiser preservar as
chaves e configurações.

## Conectar e ver ao vivo

1. Na TV, ative Configurações → Meu Fire TV → Opções do desenvolvedor → Depuração
   ADB. Se o menu estiver oculto, pressione OK sete vezes no nome do aparelho em
   Sobre. Confira o IP em Sobre → Rede.
2. Conecte pelo painel e aceite o aviso de depuração na TV.
3. Na aba Controle remoto, clique em **Ver ao vivo**. O vídeo aparece no próprio
   painel. Para parar, clique em **Encerrar vídeo**.

No Fire Stick de 3ª geração com Android 9/Fire OS 7, o áudio continua saindo pela
TV. Superfícies protegidas por DRM podem aparecer pretas. A taxa de quadros e o
atraso dependem do aparelho e da rede; a origem é limitada a 720p/30 FPS.

O painel também instala APKs, abre apps, desinstala apps de terceiros com
confirmação, transfere arquivos do armazenamento compartilhado, envia texto e
salva capturas PNG. Não acessa dados privados, senhas ou sessões dos apps.

Para personalizar o visual, instale um launcher Android compatível, como o
[Luncher](https://github.com/CVasilakis/luncher), pela fonte oficial. Layout,
favoritos e papel de parede são configurados nele. **A troca permanente do botão
Home depende do firmware**; o painel consulta e abre launchers, sem desativar a
home original. Vega OS não é compatível com APKs e não é suportado aqui.

Sem Docker: `python3 run.py setup`, `python3 run.py setup-mirror`, instale FFmpeg
e execute `./iniciar.sh`. Consulte o [README completo](README.md) para a CLI,
variáveis de ambiente, testes, limitações e arquitetura.
