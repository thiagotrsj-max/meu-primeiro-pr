# Telegram → Binance Signal Bot (semi-automático)

Lê sinais de trade postados num grupo/canal do Telegram (ex.: "Signal Tracker
Club"), aplica um filtro de risco, te manda a proposta calculada por DM no
Telegram para você **aprovar ou rejeitar com um clique**, e só então envia a
ordem para a Binance Futures.

## ⚠️ Leia antes de usar

- Sinais de grupos de Telegram **não são recomendação confiável**. Muitos
  desses grupos são monetizados por link de afiliado (ex.: cadastro na
  corretora), o que cria incentivo para manter gente operando, lucrativo ou
  não. Trate qualquer sinal como não verificado.
- Este bot **não dá conselho de investimento** — ele automatiza mecânica
  (ler, calcular tamanho de posição, enviar ordem), a decisão de operar
  continua sendo sua, sinal a sinal, pelo botão Aprovar/Rejeitar.
- Comece **sempre** em `BINANCE_TESTNET=true` e `DRY_RUN=true`. Só desative
  depois de rodar por um tempo e conferir que o parser e o cálculo de
  posição estão corretos.
- Crie a API key da Binance com **apenas** permissão de Futures Trading,
  **sem** permissão de saque, e restrita por IP se possível.
- Este repositório é público — o arquivo `.env` (com suas chaves reais)
  **nunca** deve ser commitado. Já está no `.gitignore`, mas confira sempre
  antes de dar `git push`.

## Arquitetura

```
telegram_listener.py  -> escuta o grupo via Telethon (sua conta pessoal)
signal_parser.py       -> extrai os campos estruturados do texto do sinal
risk_manager.py         -> decide tamanho de posição / rejeita sinais ruins
approval_bot.py          -> te manda a proposta e espera Aprovar/Rejeitar
binance_executor.py       -> envia entrada + stop loss + take-profits
storage.py                 -> log de auditoria em SQLite (signals.db)
main.py                     -> orquestra o fluxo acima
```

## Setup

1. **Instale as dependências** (recomendado usar um virtualenv):
   ```bash
   cd Projetos/telegram-binance-bot
   pip install -r requirements.txt
   ```

2. **Credenciais do Telegram (conta pessoal)**: acesse
   https://my.telegram.org → API Development Tools → crie um app → copie
   `api_id` e `api_hash`.

3. **Bot de aprovação**: fale com [@BotFather](https://t.me/BotFather) no
   Telegram, `/newbot`, siga as instruções, copie o token gerado. Depois
   fale com [@userinfobot](https://t.me/userinfobot) pra descobrir seu
   `chat_id` pessoal (é pra esse chat que o bot vai te mandar os sinais).

4. **Chaves da Binance**:
   - Para testar: crie uma conta e chaves em
     https://testnet.binancefuture.com (é separado da conta normal).
   - Para produção (depois de validar): crie em binance.com, na seção API
     Management, com permissão só de Futures, sem saque.

5. **Configure o `.env`**:
   ```bash
   cp .env.example .env
   ```
   Preencha os valores. Mantenha `BINANCE_TESTNET=true` e `DRY_RUN=true`
   no início.

6. **Rode**:
   ```bash
   python main.py
   ```
   Na primeira execução, o Telethon vai pedir no terminal o código que
   chegou no seu Telegram (login interativo, uma vez só — depois fica
   salvo em `telegram_user.session`, local e gitignored).

## Fluxo de uma operação

1. O bot vê uma mensagem no grupo configurado que "parece" um sinal
   (contém "Ordem Limite" + "Moeda:").
2. Tenta fazer o parse estruturado. Se o formato não bater, ignora e loga
   um aviso (não trava o processo).
3. Aplica `risk_manager`: whitelist de moeda, limite de posições
   simultâneas, R/R mínimo (calculado localmente, não confia no valor que
   o canal manda), teto de alavancagem, tamanho de posição baseado em %
   de risco do seu saldo.
4. Se aprovado pela camada de risco, te manda uma mensagem no Telegram com
   os números calculados e dois botões.
5. Se você clicar ✅, envia entrada (LIMIT) + stop loss (STOP_MARKET) +
   take-profits escalonados (TAKE_PROFIT_MARKET) para a Binance.
6. Se você clicar ❌ ou não responder dentro do timeout configurado
   (`APPROVAL_TIMEOUT_SECONDS`), nada é executado.
7. Tudo fica registrado em `signals.db` (SQLite) — sinal recebido, decisão
   da camada de risco, sua decisão, e IDs das ordens enviadas.

## Ajustar a gestão de risco

Todos os parâmetros ficam no `.env`:

| Variável | O que faz |
|---|---|
| `MAX_RISK_PER_TRADE_PCT` | % do saldo que você aceita perder se o stop for atingido, por trade |
| `MAX_LEVERAGE` | teto de alavancagem, mesmo que o sinal peça mais |
| `MIN_RR_RATIO` | recompensa/risco mínimo (baseado no alvo 1) pra sequer te perguntar |
| `MAX_CONCURRENT_POSITIONS` | quantas posições abertas o bot deixa acumular |
| `COIN_WHITELIST` | lista de moedas permitidas (vazio = todas) |

## Limitações conhecidas / próximos passos

- O parser é específico pro formato de mensagem visto no canal
  "Signal Tracker Club" (rótulos em português: Moeda, Tipo, Alavancagem,
  Zona de Entrada, Stop Loss, Alvos T1-T5). Se o formato mudar, ajuste os
  regex em `signal_parser.py`.
- `quantity` é arredondada para 3 casas decimais de forma genérica — cada
  par na Binance tem seu próprio `stepSize`/`tickSize`; para produção,
  vale consultar `futures_exchange_info()` e arredondar corretamente por
  símbolo antes de enviar a ordem.
- Contagem de posições abertas em modo dry-run é sempre 0; em modo real,
  consulta a Binance diretamente (não depende só do log local).
- Não há reconciliação automática de posições fechadas manualmente por
  você direto na Binance — o `signals.db` reflete o que o bot fez, não
  necessariamente o estado atual da conta.
