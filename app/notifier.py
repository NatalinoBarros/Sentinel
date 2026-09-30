import sys
import html
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CONSOLE_ALERTS

# Garante suporte a UTF-8 no terminal Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

async def send_telegram_message(message_html: str, chat_id: Optional[str] = None) -> bool:
    """Envia uma mensagem formatada em HTML para o Telegram."""
    destination_chat_id = str(chat_id or TELEGRAM_CHAT_ID).strip()
    if not TELEGRAM_BOT_TOKEN or not destination_chat_id:
        if CONSOLE_ALERTS:
            print("\n" + "="*50)
            print("[INFO] [TELEGRAM DESATIVADO OU NÃO CONFIGURADO]")
            print("Mensagem formatada para envio:")
            clean_text = (
                message_html
                .replace("<pre>", "\n--- TRACEBACK ---\n")
                .replace("</pre>", "\n-----------------\n")
                .replace("<b>", "")
                .replace("</b>", "")
                .replace("<code>", "`")
                .replace("</code>", "`")
            )
            print(clean_text)
            print("="*50 + "\n")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": destination_chat_id,
        "text": message_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            else:
                print(f"[ERRO TELEGRAM] Status {resp.status_code}: {resp.text}")
                return False
    except Exception as exc:
        print(f"[ERRO TELEGRAM] Falha na conexão com a API: {exc}")
        return False

async def notify_failure(
    job: Dict[str, Any],
    error_message: str,
    traceback_str: Optional[str] = None,
    duration_seconds: Optional[float] = None
) -> bool:
    """Notifica falha crítica em uma automação."""
    job_name = html.escape(job.get("name") or job.get("job_id", "Desconhecido"))
    job_id = html.escape(job.get("job_id", ""))
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    dur_str = f"{duration_seconds:.2f}s" if duration_seconds is not None else "N/A"
    clean_error = html.escape(str(error_message))

    msg = [
        "🔴 <b>FALHA NA AUTOMAÇÃO</b>",
        f"<b>Job:</b> {job_name} (<code>{job_id}</code>)",
        f"<b>Horário:</b> {now_str}",
        f"<b>Duração:</b> {dur_str}",
        f"<b>Erro:</b> <code>{clean_error}</code>",
    ]

    if traceback_str:
        clean_tb = html.escape(traceback_str.strip())
        if len(clean_tb) > 2500:
            clean_tb = "..." + clean_tb[-2500:]
        msg.append(f"\n<b>Traceback:</b>\n<pre>{clean_tb}</pre>")

    full_message = "\n".join(msg)

    if CONSOLE_ALERTS:
        print("\n" + "!"*50)
        print(f"[ALERTA DE FALHA] Job: {job_name} ({job_id})")
        print(f"Erro: {error_message}")
        if traceback_str:
            print(f"Traceback:\n{traceback_str.strip()}")
        print("!"*50 + "\n")

    return await send_telegram_message(full_message)

async def notify_missed(job: Dict[str, Any]) -> bool:
    """Notifica quando um job não rodou dentro do prazo esperado (Dead Man's Switch)."""
    job_name = html.escape(job.get("name") or job.get("job_id", "Desconhecido"))
    job_id = html.escape(job.get("job_id", ""))
    expected_at = job.get("next_expected_at", "N/A")
    grace = job.get("grace_period_minutes", 15)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    msg = [
        "⚠️ <b>ALERTA: AUTOMAÇÃO NÃO EXECUTOU (DEAD MAN'S SWITCH)</b>",
        f"<b>Job:</b> {job_name} (<code>{job_id}</code>)",
        f"<b>Horário Esperado:</b> {expected_at}",
        f"<b>Tolerância Configurada:</b> {grace} minutos",
        f"<b>Horário do Alerta:</b> {now_str}",
        "\n<b>Diagnóstico:</b> O script <b>não iniciou nem deu sinal de vida</b> dentro do prazo estipulado.",
        "Verifique o Agendador de Tarefas do Windows, o servidor ou o status da máquina!"
    ]

    full_message = "\n".join(msg)

    if CONSOLE_ALERTS:
        print("\n" + "?"*50)
        print(f"[ALERTA DE AUSÊNCIA] Job: {job_name} ({job_id}) NÃO EXECUTOU!")
        print(f"Esperado para: {expected_at} (Tolerância: {grace} min)")
        print("?"*50 + "\n")

    return await send_telegram_message(full_message)

async def notify_recovery(job: Dict[str, Any]) -> bool:
    """Notifica quando uma automação que estava falhando ou ausente voltou a ter sucesso."""
    job_name = html.escape(job.get("name") or job.get("job_id", "Desconhecido"))
    job_id = html.escape(job.get("job_id", ""))
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    msg = [
        "🟢 <b>AUTOMAÇÃO RECUPERADA COM SUCESSO</b>",
        f"<b>Job:</b> {job_name} (<code>{job_id}</code>)",
        f"<b>Horário:</b> {now_str}",
        "A automação voltou a operar normalmente."
    ]
    return await send_telegram_message("\n".join(msg))

async def notify_timeout(job: Dict[str, Any], running_minutes: float) -> bool:
    """Notifica quando uma automação ficou executando por muito tempo (possível travamento/quebra)."""
    job_name = html.escape(job.get("name") or job.get("job_id", "Desconhecido"))
    job_id = html.escape(job.get("job_id", ""))
    max_duration = job.get("max_duration_minutes", 60)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    start_time = job.get("last_ping_at", "N/A")

    if running_minutes >= 60:
        dur_str = f"{running_minutes / 60:.1f} horas ({int(running_minutes)} min)"
    else:
        dur_str = f"{int(running_minutes)} minutos"

    msg = [
        "⏱️ <b>ALERTA: AUTOMAÇÃO TRAVADA / TEMPO LIMITE EXCEDIDO</b>",
        f"<b>Job:</b> {job_name} (<code>{job_id}</code>)",
        f"<b>Início da Execução:</b> {start_time}",
        f"<b>Tempo Executando:</b> {dur_str}",
        f"<b>Limite Máximo Permitido:</b> {max_duration} minutos",
        f"<b>Horário do Alerta:</b> {now_str}",
        "\n<b>Diagnóstico:</b> O script iniciou mas <b>não concluiu nem reportou erro</b> no prazo.",
        "Possível causa: <b>travamento em loop infinito, deadlock de banco ou processo finalizado abruptamente</b>.",
        "Verifique o Gerenciador de Tarefas ou o servidor onde o script roda!"
    ]

    full_message = "\n".join(msg)

    if CONSOLE_ALERTS:
        print("\n" + "@"*50)
        print(f"[ALERTA DE TIMEOUT] Job: {job_name} ({job_id}) EXCEDEU O TEMPO MÁXIMO!")
        print(f"Tempo rodando: {dur_str} (Limite: {max_duration} min)")
        print("@"*50 + "\n")

    return await send_telegram_message(full_message)
