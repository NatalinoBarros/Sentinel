# 🛡️ Sentinel - Centralizador de Notificações e Monitoramento de Automações

O **Sentinel** é um sistema completo, leve e autônomo para monitorar a saúde de automações em Python, PHP, arquivos BAT e outros processos capazes de fazer chamadas HTTP.

Ele resolve os dois grandes problemas de quem mantém automações:
1. **Notificação Ativa de Erros:** Se o script rodar e quebrar, captura o erro e o *traceback* completo e envia um alerta imediato.
2. **Dead Man's Switch (Ausência de Execução):** Se o script **não rodar** (computador desligado, falha de cron, queda de energia), o Sentinel detecta a ausência do sinal de vida (*heartbeat*) e soa o alarme.
   Para rotinas que só operam em parte do dia, configure no painel a **janela de execução** e os **dias da semana**. O fim da janela é exclusivo, seguindo o Agendador do Windows: 09:00–12:00 com intervalo de 60 minutos representa 09:00, 10:00 e 11:00. Fora da janela e nos dias desmarcados não há falso alerta de ausência.

---

## 🏗️ Arquitetura e Tecnologias

* **FastAPI:** API de alta performance para receber os pings de início, sucesso e erro.
* **SQLite:** Banco de dados relacional embutido de arquivo único (`sentinel.db`), sem dependência de serviços externos.
* **APScheduler:** Agendador interno que inspeciona prazos, recebe comandos do Telegram e entrega relatórios programados.
* **Telegram Bot:** Alertas, consultas sob demanda e relatórios automáticos formatados em HTML.
* **Dashboard Web:** Interface em tela cheia com indicadores laterais, cards ordenados por criticidade e histórico de até 100 execuções.
* **Client SDK:** clientes sem dependências externas para plugar em scripts Python e PHP.
* **Identificação de Linguagem:** cada cliente informa automaticamente sua linguagem; o dashboard mostra os ícones do Python, PHP e arquivos BAT ao lado da rotina.
* **MCP App:** integração somente leitura para ChatGPT, Codex e outros hosts compatíveis com MCP Apps, com ferramentas de consulta e painel visual.

---

## 🚀 Como Iniciar o Sistema

### 1. Instalação das dependências
Abra o terminal na pasta do projeto e instale os pacotes:
```bash
pip install -r requirements.txt
```

### 2. Configuração do Telegram (Opcional para testes)
Edite o arquivo `.env`:
```ini
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
TELEGRAM_COMMANDS_ENABLED=true
TELEGRAM_POLL_INTERVAL_SECONDS=5
TELEGRAM_HISTORY_LIMIT=5
CONSOLE_ALERTS=true
```

> **Como obter o Token e Chat ID no Telegram (leva 2 minutos):**
> 1. No Telegram, converse com o `@BotFather`, envie `/newbot` e siga as instruções para obter o `TOKEN`.
> 2. Inicie uma conversa com seu novo bot e envie qualquer mensagem (ex: "oi").
> 3. Converse com o bot `@userinfobot` para descobrir o seu `CHAT_ID` numérico.

Com o Sentinel em execução, o bot também aceita comandos do chat configurado:

* `/status` — mostra o status de todas as automações.
* `/ultimas job_id` — mostra as últimas 5 execuções do job informado.
* `/ultimas job_id 10` — permite solicitar entre 1 e 20 execuções.
* `/automacoes` — lista os nomes e IDs disponíveis.
* `/agendar status 09:00 1-5` — envia o status geral automaticamente de segunda a sexta às 09:00.
* `/agendar ultimas job_id 18:00 1-5 5` — envia o histórico do job no horário escolhido.
* `/agendamentos` — lista os relatórios automáticos.
* `/cancelar_agendamento ID` — remove um relatório agendado.
* `/ajuda` — mostra a ajuda dos comandos.

### 3. Rodando o Servidor Central
```bash
python -m uvicorn app.main:app --port 8050 --reload
```
Acesse no seu navegador:
* **Dashboard:** [http://127.0.0.1:8050](http://127.0.0.1:8050)
* **Documentação Interativa (Swagger):** [http://127.0.0.1:8050/docs](http://127.0.0.1:8050/docs)

### 4. MCP App para ChatGPT e Codex

O MCP App fica em `mcp-app/` e consome as APIs REST do Sentinel. Esta primeira versão é deliberadamente **somente leitura**: ela consulta estados e diagnósticos, mas não cadastra, edita, remove ou envia pings em nome das automações.

Com o Sentinel da porta 8050 em execução, instale e inicie o MCP App:

```powershell
cd mcp-app
npm.cmd install
npm.cmd start
```

No Windows, também é possível usar `run_mcp.bat`. O endpoint local será `http://127.0.0.1:8787/mcp`.

Para permitir conexões de outras máquinas da mesma rede, configure o bind no `.env` e reinicie o MCP App:

```dotenv
MCP_HOST=0.0.0.0
MCP_PORT=8787
```

Use `http://IP_DA_MAQUINA:8787/` somente para verificar se o serviço responde. O endereço MCP que deve ser cadastrado no cliente é `http://IP_DA_MAQUINA:8787/mcp`. Abrir `/mcp` diretamente em um navegador comum retorna `406 Not Acceptable`, pois esse endpoint exige um cliente Streamable HTTP que aceite `text/event-stream`.

Se outra máquina ainda não alcançar a porta, crie uma regra de entrada TCP 8787 no Firewall do Windows limitada ao perfil privado e à sub-rede necessária. O bind em `0.0.0.0` não substitui a liberação do firewall.

Ferramentas expostas na versão 0.2:

* `sentinel_list_jobs` — lista automações, estados atuais e resumo operacional;
* `sentinel_get_executions` — consulta histórico, mensagens de erro e traceback;
* `sentinel_self_status` — informa versões, uptime, banco, última atualização e latência;
* `sentinel_get_attention_queue` — retorna somente jobs que exigem atenção, por criticidade;
* `sentinel_diagnose_job` — identifica falhas consecutivas, atrasos, timeouts e erros recorrentes;
* `sentinel_get_metrics` — calcula sucesso, ausência, média, p95 e violações de tempo;
* `sentinel_compare_periods` — compara hoje × ontem ou 7 × 30 dias;
* `sentinel_check_changes` — compara a fila atual com o último estado persistido;
* `sentinel_render_status` — exibe o painel compacto original;
* `sentinel_render_operations` — exibe um painel operacional moderno e responsivo com visão geral, fila priorizada, distribuição, métricas formatadas, linha do tempo e diagnósticos expansíveis. O painel permite atualização manual e sincroniza automaticamente a cada 60 segundos.

O monitor proativo é ativado com `MCP_PROACTIVE_ENABLED=true`. Ele consulta a API no intervalo configurado, grava somente a fotografia operacional em `mcp-app/data/attention-state.json` e não emite nada quando o estado permanece igual. Se `MCP_ALERT_WEBHOOK_URL` estiver configurada, envia `sentinel.attention.changed` apenas quando um job entra, muda ou sai da fila; `MCP_ALERT_WEBHOOK_SECRET` adiciona assinatura HMAC-SHA256.

> O webhook é a integração proativa desta versão local. A entrega nativa de eventos em chats exige MCP Events, protocolo 2.0, armazenamento de assinaturas e callbacks HTTPS; ela não é simulada por polling do ChatGPT.

As variáveis opcionais `SENTINEL_API_URL`, `MCP_HOST` e `MCP_PORT` ficam no `.env`. O bind `0.0.0.0` destina-se à rede local confiável. Para acesso pela internet, não encaminhe a porta 8787 diretamente: publique por HTTPS com autenticação e controle de acesso, ou use um túnel MCP seguro, sempre informando a URL completa terminada em `/mcp`.

Validação local:

```powershell
cd mcp-app
npm.cmd test
```

### Dashboard

O painel ocupa toda a largura e altura da tela e oferece:

* indicadores **Total**, **Saudáveis**, **Executando**, **Com Falha** e **Ausentes** empilhados na lateral esquerda;
* navegação entre **Automações** e **Últimas execuções** na barra superior;
* modos de visualização em **Cards** ou **Lista**, com preferência salva no navegador;
* cards minimizados por padrão, expansíveis individualmente ou pelo comando **Expandir todos**;
* status, próxima execução, linguagem, frequência, janela, dias da semana, tolerância, última execução e limite de execução em cada card;
* modal de diagnóstico para falhas, com mensagem completa, traceback, identificação da execução e opção de copiar o erro;
* ordenação automática por prioridade: falha/timeout, ausente, executando, saudável e aguardando;
* filtro de automações e filtro de histórico por `job_id`;
* atalho em cada card para abrir diretamente as últimas execuções daquela automação.

### Configuração de horários e dias

Para uma rotina executada de segunda a sexta, a cada 60 minutos, durante três horas a partir das 09:00, deixe o Cron vazio e configure:

```text
Intervalo: 60 minutos
Início: 09:00
Fim: 12:00
Dias: segunda, terça, quarta, quinta e sexta
```

O fim da janela é exclusivo, como no Agendador do Windows. Nesse exemplo, o Sentinel espera sinais às 09:00, 10:00 e 11:00. Depois das 12:00 e no final de semana, o Dead Man's Switch fica em espera.

Para uma execução única às 09:00 de segunda a sexta, também é possível usar:

```cron
0 9 * * 1-5
```

---

## 🐍 Como Usar nas Suas Automações

Você só precisa de **2 linhas de código** para monitorar qualquer script Python existente:

```python
from client.monitor import monitor_job

@monitor_job(job_id="relatorio_diario", name="Relatório Diário de Vendas")
def minha_automacao():
    print("Processando dados...")
    # Se ocorrer qualquer erro aqui, o Sentinel captura o traceback
    # e envia o alerta imediato no Telegram!

if __name__ == "__main__":
    minha_automacao()
```

### Ou usando `with` (Context Manager):
```python
from client.monitor import SentinelMonitor

with SentinelMonitor(job_id="fechamento_contabil", name="Fechamento Contábil"):
    # seu código aqui
    pass
```

---

## 🐘 Como Usar em Scripts PHP

O cliente PHP usa os mesmos endpoints e envia as mesmas informações do cliente Python: início, identificador da execução, sucesso ou falha, duração, mensagem e rastreamento do erro.

Inclua o cliente e envolva a rotina em `sentinel_monitor`, que funciona como um decorator para um `callable`:

```php
<?php
require_once __DIR__ . '/client/sentinel_monitor.php';

// Forma minima: o nome exibido sera o proprio job_id.
sentinel_monitor('minha_rotina_php', function () {
    // rotina monitorada
});

// Forma completa:
sentinel_monitor(
    'baixa_retornos_grafeno',
    'Baixa de retornos Grafeno',
    function () {
        executarBaixaRetornos();
    },
    'http://127.0.0.1:8050' // opcional; também aceita SENTINEL_SERVER_URL
);

function executarBaixaRetornos()
{
    // Corpo principal da automação.
    // Em uma falha funcional, lance uma exceção:
    // throw new RuntimeException('A API Grafeno retornou HTTP ' . $status);
}
```

O valor retornado pelo `callable` é preservado. Exceções e erros PHP são registrados como falha e relançados, mantendo o comportamento original. Erros fatais e `exit/die` prematuros também são registrados pelo tratamento de encerramento.

Requer PHP 7 ou superior. A extensão cURL é usada quando instalada; sem ela, o cliente utiliza os streams HTTP nativos do PHP.

Para adaptar o script Grafeno usado como exemplo:

1. Remova o `die("arquivo desativado")` quando desejar ativá-lo.
2. Mantenha os `require` e a função `BaixaArquivos` fora do wrapper.
3. Coloque o fluxo principal em `executarBaixaRetornos()` e chame essa função dentro de `sentinel_monitor`.
4. Troque blocos que apenas imprimem erros por `throw new RuntimeException(...)`. Caso contrário, o PHP termina normalmente e o Sentinel registra sucesso.
5. Quando um `exit` representar conclusão normal, substitua-o por `return`. O cliente considera `exit/die` dentro da rotina uma interrupção anormal.

### Exemplo com consultas ao banco

Para scripts legados como o monitoramento de notas fiscais, deixe as funções auxiliares como estão e mova somente o bloco principal para uma função:

```php
<?php
require_once __DIR__ . '/client/sentinel_monitor.php';

// Funções auxiliares existentes permanecem aqui.

function executarMonitoramentoNf()
{
    if (!isset($GLOBALS['config'])) {
        require '../config.php';
        require '../functions.php';
        require '../DBFunctions.php';
    }

    $conn = DbConect();
    $query = 'SELECT ...';
    $result = DBQuery($query, $conn)
        or sentinel_fail('Erro: ' . DbError($conn) . ' na query ' . $query);

    // Restante do fluxo principal existente.
}

sentinel_monitor(
    'monitoramento_nf_email',
    'Monitoramento de notas fiscais por e-mail',
    'executarMonitoramentoNf'
);
```

O helper `sentinel_fail($mensagem)` substitui `die($mensagem)`: ele encerra a rotina por exceção, permitindo que o Sentinel registre a mensagem completa e o stack trace antes de manter a falha visível para o PHP.

### Identificação automática da linguagem

Os clientes incluem a linguagem no ping de início sem exigir configuração adicional:

* `client/monitor.py` envia `language: "python"`.
* `client/sentinel_monitor.php` envia `language: "php"`.
* O dashboard exibe os ícones do Python, PHP e Windows/BAT ao lado do nome da automação; linguagens não identificadas usam um ícone próprio de interrogação.

Jobs cadastrados antes desse recurso exibem temporariamente um ícone neutro. A linguagem é preenchida na próxima execução realizada com o cliente atualizado. Se `sentinel_monitor.php` tiver sido copiado para outro sistema, substitua essa cópia pela versão mais recente.

A linguagem também pode ser definida manualmente ao cadastrar ou editar uma rotina no dashboard. As opções são **Python**, **PHP** e **Outra / BAT**. Uma identificação enviada posteriormente pelo cliente durante o ping de início atualiza esse metadado.

Exemplos disponíveis:

* `tests/php/example_success.php` e `tests/php/example_failure.php`: casos mínimos de sucesso e falha.
* `examples/php/monitoramento_nf_com_sentinel.php`: processamento de banco e envio de e-mails.
* `examples/php/analise_nfs_com_sentinel.php`: processamento longo em CLI ou em vários ciclos HTTP.
* `examples/php/retorno_bancario_grafeno_com_sentinel.php`: paginação de contas, download e distribuição de retornos bancários da Grafeno.

No exemplo de ciclos HTTP, o redirecionamento entre requisições usa `return` em vez de `exit`, permitindo que o Sentinel finalize cada ciclo corretamente. Erros de lote, fila sem progresso e limite máximo de ciclos são registrados como falha.

No exemplo Grafeno, o cliente Sentinel fica uma pasta acima e é importado com `require_once __DIR__ . '/../sentinel_monitor.php';`. Falhas enviadas ao Sentinel usam mensagens resumidas e nunca incluem o header `Authorization` nem o token da API.

---

## 🪟 Como Usar em Arquivos BAT

Arquivos `.bat` podem enviar os sinais de início, sucesso e falha com o `curl.exe` incluído no Windows 10/11:

```bat
@echo off
setlocal
set "SENTINEL_URL=http://127.0.0.1:8050"
set "JOB_ID=minha_rotina_bat"

curl.exe -s -X POST "%SENTINEL_URL%/api/ping/%JOB_ID%/start" ^
  -H "Content-Type: application/json" ^
  -d "{\"job_name\":\"Minha rotina BAT\",\"language\":\"other\"}" >nul 2>&1

call "C:\Automacoes\minha_rotina_original.bat"
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" goto sucesso
curl.exe -s -X POST "%SENTINEL_URL%/api/ping/%JOB_ID%/fail" ^
  -H "Content-Type: application/json" ^
  -d "{\"error_message\":\"BAT finalizado com codigo %EXIT_CODE%\"}" >nul 2>&1
goto fim

:sucesso
curl.exe -s -X POST "%SENTINEL_URL%/api/ping/%JOB_ID%/success" ^
  -H "Content-Type: application/json" -d "{}" >nul 2>&1

:fim
endlocal & exit /b %EXIT_CODE%
```

O `JOB_ID` deve ser igual ao cadastrado no painel. Quando o BAT abrir outro processo, use `start /wait` para aguardar sua conclusão. Evite `pause` em tarefas executadas pelo Agendador do Windows, pois ele mantém o processo indefinidamente em execução.

---

## 🧪 Rodando o Script de Demonstração e Testes

Com o servidor rodando, execute em outro terminal:
```bash
python tests/test_simulation.py
```
Esse script executa uma bateria de testes simulando:
1. Uma automação rodando com sucesso 🟢
2. Uma automação sofrendo falha crítica com divisão por zero 🔴
3. O registro de uma automação que "não rodou" para disparar o Dead Man's Switch ⚠️

Os testes unitários do cálculo de janelas, dias úteis, metadados de linguagem e Telegram podem ser executados sem o servidor:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
