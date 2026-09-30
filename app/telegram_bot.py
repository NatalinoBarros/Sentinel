import html
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_HISTORY_LIMIT
from app.database import (
    create_telegram_report_schedule,
    delete_telegram_report_schedule,
    get_due_telegram_report_schedules,
    get_job,
    get_recent_executions,
    list_jobs,
    list_telegram_report_schedules,
    mark_telegram_report_sent,
)
from app.notifier import send_telegram_message


_last_update_id: Optional[int] = None
_commands_registered = False

STATUS_INFO = {
    "SUCCESS": ("🟢", "Saudável"),
    "RUNNING": ("🔵", "Executando"),
    "FAILED": ("🔴", "Com falha"),
    "TIMEOUT": ("⏱️", "Travado / timeout"),
    "MISSED": ("⚠️", "Não executou"),
    "PENDING": ("⚪", "Aguardando"),
}


def parse_command(text: str) -> Tuple[str, List[str]]:
    parts = (text or "").strip().split()
    if not parts or not parts[0].startswith("/"):
        return "", []
    command = parts[0][1:].split("@", 1)[0].lower()
    return command, parts[1:]


def parse_weekday_spec(value: str) -> List[int]:
    aliases = {
        "todos": list(range(1, 8)),
        "diario": list(range(1, 8)),
        "diasuteis": list(range(1, 6)),
        "seg-sex": list(range(1, 6)),
    }
    normalized = (value or "").strip().lower()
    if normalized in aliases:
        return aliases[normalized]
    days = set()
    for part in normalized.split(","):
        if "-" in part:
            bounds = part.split("-", 1)
            if len(bounds) != 2:
                raise ValueError("Dias inválidos.")
            start, end = int(bounds[0]), int(bounds[1])
            if start > end:
                raise ValueError("Intervalo de dias inválido.")
            days.update(range(start, end + 1))
        else:
            days.add(int(part))
    result = sorted(days)
    if not result or any(day < 1 or day > 7 for day in result):
        raise ValueError("Use dias de 1 a 7; exemplo: 1-5.")
    return result


def _format_datetime(value: Optional[str]) -> str:
    if not value:
        return "Nunca"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}min"


def _status_icon_label(status: str) -> Tuple[str, str]:
    return STATUS_INFO.get(status, ("❔", status or "Desconhecido"))


def build_status_messages(jobs: List[Dict[str, Any]], max_length: int = 3800) -> List[str]:
    if not jobs:
        return ["📊 <b>STATUS DAS AUTOMAÇÕES</b>\n\nNenhuma automação cadastrada."]

    counts: Dict[str, int] = {}
    for job in jobs:
        status = job.get("last_status") or "PENDING"
        counts[status] = counts.get(status, 0) + 1

    summary_order = ("SUCCESS", "RUNNING", "FAILED", "TIMEOUT", "MISSED", "PENDING")
    summary = []
    for status in summary_order:
        if counts.get(status):
            icon, label = _status_icon_label(status)
            summary.append(f"{icon} {label}: <b>{counts[status]}</b>")

    header = f"📊 <b>STATUS DAS AUTOMAÇÕES ({len(jobs)})</b>\n" + " · ".join(summary)
    blocks = []
    for job in jobs:
        status = job.get("last_status") or "PENDING"
        icon, label = _status_icon_label(status)
        name = html.escape(str(job.get("name") or job.get("job_id") or "Sem nome"))
        job_id = html.escape(str(job.get("job_id") or ""))
        blocks.append(
            f"{icon} <b>{name}</b> (<code>{job_id}</code>)\n"
            f"Status: {label}\n"
            f"Última: {_format_datetime(job.get('last_ping_at'))}\n"
            f"Próxima: {_format_datetime(job.get('next_expected_at'))}"
        )

    messages = []
    current = header
    for block in blocks:
        addition = "\n\n" + block
        if len(current) + len(addition) > max_length:
            messages.append(current)
            current = "📊 <b>STATUS — CONTINUAÇÃO</b>" + addition
        else:
            current += addition
    messages.append(current)
    return messages


def build_executions_message(job: Dict[str, Any], executions: List[Dict[str, Any]]) -> str:
    name = html.escape(str(job.get("name") or job.get("job_id") or "Sem nome"))
    job_id = html.escape(str(job.get("job_id") or ""))
    header = f"🕘 <b>ÚLTIMAS EXECUÇÕES</b>\n<b>{name}</b> (<code>{job_id}</code>)"
    if not executions:
        return header + "\n\nNenhuma execução registrada."

    lines = [header]
    for execution in executions:
        status = execution.get("status") or "PENDING"
        icon, label = _status_icon_label(status)
        when = _format_datetime(execution.get("started_at"))
        duration = _format_duration(execution.get("duration_seconds"))
        line = f"{icon} <b>{label}</b> · {when} · {duration}"
        error = execution.get("error_message")
        if error:
            clean_error = html.escape(str(error).replace("\n", " "))
            if len(clean_error) > 180:
                clean_error = clean_error[:177] + "..."
            line += f"\n└ {clean_error}"
        lines.append(line)
    return "\n\n".join(lines)


def build_jobs_message(jobs: List[Dict[str, Any]]) -> str:
    if not jobs:
        return "🤖 <b>AUTOMAÇÕES</b>\n\nNenhuma automação cadastrada."
    lines = ["🤖 <b>AUTOMAÇÕES DISPONÍVEIS</b>"]
    for job in jobs:
        name = html.escape(str(job.get("name") or job.get("job_id") or "Sem nome"))
        job_id = html.escape(str(job.get("job_id") or ""))
        lines.append(f"• {name}: <code>{job_id}</code>")
    lines.append("\nUse <code>/ultimas job_id</code> para consultar o histórico.")
    return "\n".join(lines)


def build_help_message() -> str:
    return (
        "🤖 <b>COMANDOS DO SENTINEL</b>\n\n"
        "<code>/status</code> — status de todas as automações\n"
        "<code>/ultimas job_id</code> — últimas execuções de uma automação\n"
        "<code>/ultimas job_id 10</code> — define a quantidade (máximo 20)\n"
        "<code>/automacoes</code> — lista nomes e IDs disponíveis\n"
        "<code>/agendar status 09:00 1-5</code> — agenda o status geral\n"
        "<code>/agendar ultimas job_id 18:00 1-5 5</code> — agenda o histórico\n"
        "<code>/agendamentos</code> — lista relatórios agendados\n"
        "<code>/cancelar_agendamento ID</code> — cancela um agendamento\n"
        "<code>/ajuda</code> — exibe esta ajuda"
    )


def build_schedules_message(schedules: List[Dict[str, Any]]) -> str:
    if not schedules:
        return "📅 <b>AGENDAMENTOS</b>\n\nNenhum relatório automático agendado."
    lines = ["📅 <b>RELATÓRIOS AGENDADOS</b>"]
    for schedule in schedules:
        days = schedule["weekdays"]
        target = "status geral" if schedule["report_type"] == "status" else f"últimas de {html.escape(schedule['job_id'])}"
        lines.append(f"<b>#{schedule['id']}</b> · {schedule['schedule_time']} · dias {days} · {target}")
    lines.append("\nPara cancelar: <code>/cancelar_agendamento ID</code>")
    return "\n".join(lines)


async def handle_command(text: str, chat_id: str) -> None:
    command, args = parse_command(text)
    if command in ("start", "ajuda", "help"):
        await send_telegram_message(build_help_message(), chat_id)
        return
    if command in ("status", "todos"):
        for message in build_status_messages(list_jobs()):
            await send_telegram_message(message, chat_id)
        return
    if command in ("automacoes", "jobs"):
        await send_telegram_message(build_jobs_message(list_jobs()), chat_id)
        return
    if command == "agendar":
        usage = (
            "Formatos:\n"
            "<code>/agendar status 09:00 1-5</code>\n"
            "<code>/agendar ultimas job_id 18:00 1-5 5</code>\n\n"
            "Dias: 1=segunda, ..., 7=domingo. Também aceita <code>todos</code> ou <code>diasuteis</code>."
        )
        if not args:
            await send_telegram_message(usage, chat_id)
            return
        try:
            report_type = args[0].lower()
            if report_type == "status" and len(args) == 3:
                schedule_time = args[1]
                weekdays = parse_weekday_spec(args[2])
                schedule = create_telegram_report_schedule(chat_id, "status", schedule_time, weekdays)
            elif report_type in ("ultimas", "historico") and 4 <= len(args) <= 5:
                job_id = args[1]
                schedule_time = args[2]
                weekdays = parse_weekday_spec(args[3])
                limit = int(args[4]) if len(args) == 5 else TELEGRAM_HISTORY_LIMIT
                schedule = create_telegram_report_schedule(
                    chat_id, "ultimas", schedule_time, weekdays, job_id=job_id, history_limit=limit
                )
            else:
                await send_telegram_message(usage, chat_id)
                return
        except (ValueError, TypeError) as exc:
            await send_telegram_message(f"❌ {html.escape(str(exc))}\n\n{usage}", chat_id)
            return
        await send_telegram_message(
            f"✅ Agendamento <b>#{schedule['id']}</b> criado para {schedule['schedule_time']} "
            f"nos dias {schedule['weekdays']}.",
            chat_id,
        )
        return
    if command == "agendamentos":
        await send_telegram_message(build_schedules_message(list_telegram_report_schedules(chat_id)), chat_id)
        return
    if command in ("cancelar_agendamento", "desagendar"):
        if len(args) != 1 or not args[0].isdigit():
            await send_telegram_message("Use <code>/cancelar_agendamento ID</code>.", chat_id)
            return
        deleted = delete_telegram_report_schedule(int(args[0]), chat_id)
        message = "✅ Agendamento cancelado." if deleted else "❌ Agendamento não encontrado."
        await send_telegram_message(message, chat_id)
        return
    if command in ("ultimas", "historico"):
        if not args:
            await send_telegram_message(
                "Informe o ID da automação. Exemplo: <code>/ultimas Crypt_Lamina</code>\n\n"
                + build_jobs_message(list_jobs()),
                chat_id,
            )
            return
        job_id = args[0]
        job = get_job(job_id)
        if not job:
            await send_telegram_message(
                f"❌ Automação <code>{html.escape(job_id)}</code> não encontrada.\n\n" + build_jobs_message(list_jobs()),
                chat_id,
            )
            return
        limit = TELEGRAM_HISTORY_LIMIT
        if len(args) > 1:
            try:
                limit = max(1, min(int(args[1]), 20))
            except ValueError:
                await send_telegram_message("A quantidade deve ser um número entre 1 e 20.", chat_id)
                return
        executions = get_recent_executions(limit=limit, job_id=job_id)
        await send_telegram_message(build_executions_message(job, executions), chat_id)
        return
    if command:
        await send_telegram_message("Comando não reconhecido. Use <code>/ajuda</code>.", chat_id)


async def _register_commands(client: httpx.AsyncClient) -> None:
    global _commands_registered
    if _commands_registered:
        return
    commands = [
        {"command": "status", "description": "Status de todas as automações"},
        {"command": "ultimas", "description": "Últimas execuções de uma automação"},
        {"command": "automacoes", "description": "Listar automações e IDs"},
        {"command": "agendar", "description": "Criar relatório automático"},
        {"command": "agendamentos", "description": "Listar relatórios agendados"},
        {"command": "cancelar_agendamento", "description": "Cancelar relatório agendado"},
        {"command": "ajuda", "description": "Ver comandos disponíveis"},
    ]
    response = await client.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands",
        json={"commands": commands},
    )
    if response.status_code == 200:
        _commands_registered = True
    else:
        print(f"[TELEGRAM BOT] Falha ao registrar comandos: {response.status_code} {response.text}")


async def poll_telegram_commands() -> None:
    """Busca e processa comandos enviados pelo chat autorizado."""
    global _last_update_id
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    params = {"timeout": 0, "allowed_updates": "[\"message\"]"}
    if _last_update_id is not None:
        params["offset"] = _last_update_id + 1

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await _register_commands(client)
            response = await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params=params,
            )
            response.raise_for_status()
            updates = response.json().get("result", [])
    except Exception as exc:
        print(f"[TELEGRAM BOT] Falha ao consultar comandos: {exc}")
        return

    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            _last_update_id = max(_last_update_id or update_id, update_id)
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = message.get("text") or ""
        if chat_id != str(TELEGRAM_CHAT_ID):
            print(f"[TELEGRAM BOT] Comando ignorado de chat não autorizado: {chat_id}")
            continue
        await handle_command(text, chat_id)


async def dispatch_scheduled_telegram_reports() -> None:
    """Envia uma vez por dia os relatórios que venceram no minuto atual."""
    now = datetime.now()
    for schedule in get_due_telegram_report_schedules(now):
        chat_id = str(schedule["chat_id"])
        sent = True
        if schedule["report_type"] == "status":
            for message in build_status_messages(list_jobs()):
                sent = await send_telegram_message(message, chat_id) and sent
        else:
            job = get_job(schedule["job_id"])
            if not job:
                sent = await send_telegram_message(
                    f"❌ O job agendado <code>{html.escape(schedule['job_id'])}</code> não existe mais.",
                    chat_id,
                )
            else:
                executions = get_recent_executions(
                    limit=schedule["history_limit"], job_id=schedule["job_id"]
                )
                sent = await send_telegram_message(build_executions_message(job, executions), chat_id)
        if sent:
            mark_telegram_report_sent(schedule["id"], now.date().isoformat())
