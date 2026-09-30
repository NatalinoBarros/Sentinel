from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import CHECK_INTERVAL_SECONDS, TELEGRAM_COMMANDS_ENABLED, TELEGRAM_POLL_INTERVAL_SECONDS
from app.database import list_jobs, mark_missed, mark_timeout
from app.notifier import notify_missed, notify_timeout
from app.telegram_bot import dispatch_scheduled_telegram_reports, poll_telegram_commands

scheduler = AsyncIOScheduler()

async def check_dead_mans_switch():
    """
    Verifica todos os jobs cadastrados para:
    1. Dead Man's Switch: automações que NÃO rodaram dentro do horário previsto + tolerância.
    2. Timeout / Travamento: automações que ficaram em status 'RUNNING' além do tempo limite máximo.
    """
    now = datetime.now()
    jobs = list_jobs()

    for job in jobs:
        status = job.get("last_status", "")

        # -------------------------------------------------------------
        # 1. VERIFICAÇÃO DE TIMEOUT / EXECUÇÃO TRAVADA (Status RUNNING)
        # -------------------------------------------------------------
        if status == "RUNNING":
            last_ping_str = job.get("last_ping_at")
            if last_ping_str:
                try:
                    last_ping = datetime.fromisoformat(last_ping_str)
                    max_duration_minutes = job.get("max_duration_minutes", 60) or 60
                    timeout_deadline = last_ping + timedelta(minutes=max_duration_minutes)
                    alert_timeout_sent = bool(job.get("alert_sent_for_timeout", 0))

                    if now > timeout_deadline and not alert_timeout_sent:
                        elapsed_seconds = (now - last_ping).total_seconds()
                        elapsed_minutes = elapsed_seconds / 60
                        print(f"[TIMEOUT MONITOR] Automação travada detectada: {job['job_id']} (rodando há {elapsed_minutes:.1f}m, limite {max_duration_minutes}m)")
                        updated_job = mark_timeout(job["job_id"], max_duration_minutes, elapsed_seconds)
                        await notify_timeout(updated_job or job, elapsed_minutes)
                except Exception as exc:
                    print(f"[SCHEDULER ERROR] Erro ao calcular timeout do job {job['job_id']}: {exc}")
            continue

        # -------------------------------------------------------------
        # 2. VERIFICAÇÃO DE DEAD MAN'S SWITCH (Automação Ausente)
        # -------------------------------------------------------------
        next_exp_str = job.get("next_expected_at")
        if not next_exp_str:
            continue

        try:
            next_expected = datetime.fromisoformat(next_exp_str)
        except Exception:
            continue

        grace_minutes = job.get("grace_period_minutes", 15)
        deadline = next_expected + timedelta(minutes=grace_minutes)

        alert_sent = bool(job.get("alert_sent_for_missing", 0))

        if now > deadline and not alert_sent and status != "RUNNING":
            print(f"[DEAD MAN'S SWITCH] Detectada ausência de execução para o job: {job['job_id']}")
            mark_missed(job["job_id"])
            job["next_expected_at"] = next_exp_str
            await notify_missed(job)

def start_scheduler():
    """Inicia o agendador em segundo plano."""
    if not scheduler.running:
        scheduler.add_job(
            check_dead_mans_switch,
            "interval",
            seconds=CHECK_INTERVAL_SECONDS,
            id="dead_mans_switch_checker",
            replace_existing=True
        )
        if TELEGRAM_COMMANDS_ENABLED:
            scheduler.add_job(
                poll_telegram_commands,
                "interval",
                seconds=max(2, TELEGRAM_POLL_INTERVAL_SECONDS),
                id="telegram_command_poller",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            scheduler.add_job(
                dispatch_scheduled_telegram_reports,
                "interval",
                seconds=15,
                id="telegram_scheduled_reports",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        scheduler.start()
        print(f"[SCHEDULER] Monitor de ausência e timeouts iniciado (checagem a cada {CHECK_INTERVAL_SECONDS}s).")

def stop_scheduler():
    """Encerra o agendador."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[SCHEDULER] Monitor de agendamento encerrado.")
