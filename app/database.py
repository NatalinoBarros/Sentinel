import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict, Any, Iterator
from croniter import croniter
from app.config import DB_PATH, DEFAULT_GRACE_MINUTES

@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Inicializa as tabelas no SQLite se não existirem e aplica migrações."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                language TEXT,
                schedule_cron TEXT,
                expected_interval_minutes INTEGER DEFAULT 1440,
                grace_period_minutes INTEGER DEFAULT 15,
                max_duration_minutes INTEGER DEFAULT 60,
                execution_window_start TEXT,
                execution_window_end TEXT,
                execution_weekdays TEXT,
                last_ping_at TIMESTAMP,
                last_status TEXT DEFAULT 'PENDING',
                next_expected_at TIMESTAMP,
                alert_sent_for_missing INTEGER DEFAULT 0,
                alert_sent_for_timeout INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                duration_seconds REAL,
                status TEXT NOT NULL,
                error_message TEXT,
                traceback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS telegram_report_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                job_id TEXT,
                schedule_time TEXT NOT NULL,
                weekdays TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7',
                history_limit INTEGER NOT NULL DEFAULT 5,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_sent_on TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrações seguras para tabelas existentes
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "max_duration_minutes" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN max_duration_minutes INTEGER DEFAULT 60")
        if "alert_sent_for_timeout" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN alert_sent_for_timeout INTEGER DEFAULT 0")
        if "execution_window_start" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN execution_window_start TEXT")
        if "execution_window_end" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN execution_window_end TEXT")
        if "execution_weekdays" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN execution_weekdays TEXT")
        if "language" not in columns:
            cursor.execute("ALTER TABLE jobs ADD COLUMN language TEXT")

        conn.commit()

def _parse_window_time(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"Horário inválido: {value}. Use o formato HH:MM.") from exc


def _parse_weekdays(value: Any) -> List[int]:
    """Normaliza dias da semana no padrão ISO: segunda=1, domingo=7."""
    if value is None or value == "":
        return list(range(1, 8))
    if isinstance(value, str):
        raw_days = value.split(",")
    else:
        raw_days = value
    try:
        weekdays = sorted({int(day) for day in raw_days})
    except (TypeError, ValueError) as exc:
        raise ValueError("Dias da semana inválidos.") from exc
    if not weekdays or any(day < 1 or day > 7 for day in weekdays):
        raise ValueError("Selecione ao menos um dia válido da semana (1 a 7).")
    return weekdays


def _next_allowed_window_start(base_date, window_start: time, weekdays: List[int], include_date: bool = False) -> datetime:
    days_ahead = 0 if include_date else 1
    while days_ahead <= 7:
        candidate_date = base_date + timedelta(days=days_ahead)
        if candidate_date.isoweekday() in weekdays:
            return datetime.combine(candidate_date, window_start)
        days_ahead += 1
    raise ValueError("Não foi possível calcular o próximo dia de execução.")


def calculate_next_expected(job: Dict[str, Any], base_time: Optional[datetime] = None) -> Optional[datetime]:
    """Calcula a próxima execução esperada com base em cron ou intervalo em minutos."""
    if base_time is None:
        base_time = datetime.now()
    
    cron_expr = job.get("schedule_cron")
    if cron_expr and cron_expr.strip():
        try:
            iter = croniter(cron_expr.strip(), base_time)
            return iter.get_next(datetime)
        except Exception:
            pass
    
    raw_interval = job.get("expected_interval_minutes")
    interval = 1440 if raw_interval is None else raw_interval

    window_start = _parse_window_time(job.get("execution_window_start"))
    window_end = _parse_window_time(job.get("execution_window_end"))
    weekdays = _parse_weekdays(job.get("execution_weekdays"))
    if bool(window_start) != bool(window_end):
        raise ValueError("Informe o início e o fim da janela de execução.")
    if not window_start:
        return base_time + timedelta(minutes=interval)
    if window_start >= window_end:
        raise ValueError("O fim da janela deve ser posterior ao início.")
    if interval <= 0:
        raise ValueError("O intervalo deve ser maior que zero.")

    start_today = datetime.combine(base_time.date(), window_start)
    end_today = datetime.combine(base_time.date(), window_end)
    if base_time.isoweekday() not in weekdays:
        return _next_allowed_window_start(base_time.date(), window_start, weekdays)
    if base_time < start_today:
        return start_today
    if base_time >= end_today:
        return _next_allowed_window_start(base_time.date(), window_start, weekdays)

    elapsed_minutes = (base_time - start_today).total_seconds() / 60
    completed_intervals = int(elapsed_minutes // interval) + 1
    next_expected = start_today + timedelta(minutes=completed_intervals * interval)
    # O fim é exclusivo, como no Agendador do Windows: uma janela 09:00–12:00
    # com intervalo de 1h espera execuções às 09:00, 10:00 e 11:00.
    if next_expected >= end_today:
        return _next_allowed_window_start(base_time.date(), window_start, weekdays)
    return next_expected

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def list_jobs() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs ORDER BY name ASC")
        return [dict(row) for row in cursor.fetchall()]

def register_or_update_job(
    job_id: str,
    name: Optional[str] = None,
    language: Optional[str] = None,
    schedule_cron: Optional[str] = None,
    expected_interval_minutes: Optional[int] = None,
    grace_period_minutes: Optional[int] = None,
    max_duration_minutes: Optional[int] = None,
    execution_window_start: Optional[str] = None,
    execution_window_end: Optional[str] = None,
    execution_weekdays: Any = None
) -> Dict[str, Any]:
    existing = get_job(job_id)
    now = datetime.now()
    name = name or (existing["name"] if existing else job_id)
    normalized_language = (language or "").strip().lower() or None
    if normalized_language not in (None, "python", "php", "other"):
        raise ValueError("Linguagem inválida. Use python, php ou other.")
    if normalized_language is None and existing:
        normalized_language = existing.get("language")
    grace = grace_period_minutes if grace_period_minutes is not None else (existing["grace_period_minutes"] if existing else DEFAULT_GRACE_MINUTES)
    cron = schedule_cron if schedule_cron is not None else (existing.get("schedule_cron") if existing else None)
    if expected_interval_minutes is not None:
        interval = expected_interval_minutes
    elif existing and existing.get("expected_interval_minutes") is not None:
        interval = existing.get("expected_interval_minutes")
    else:
        interval = 1440

    max_dur = max_duration_minutes if max_duration_minutes is not None else (existing.get("max_duration_minutes") if existing and existing.get("max_duration_minutes") is not None else 60)

    if execution_window_start is None and execution_window_end is None and existing:
        window_start = existing.get("execution_window_start")
        window_end = existing.get("execution_window_end")
    else:
        window_start = (execution_window_start or "").strip() or None
        window_end = (execution_window_end or "").strip() or None

    if execution_weekdays is None and existing:
        weekdays = existing.get("execution_weekdays") or "1,2,3,4,5,6,7"
    else:
        weekdays = ",".join(str(day) for day in _parse_weekdays(execution_weekdays))

    job_data = {
        "job_id": job_id,
        "name": name,
        "language": normalized_language,
        "schedule_cron": cron,
        "expected_interval_minutes": interval,
        "grace_period_minutes": grace,
        "max_duration_minutes": max_dur,
        "execution_window_start": window_start,
        "execution_window_end": window_end,
        "execution_weekdays": weekdays
    }

    next_expected = calculate_next_expected(job_data, now)
    window_changed = bool(existing) and (
        existing.get("execution_window_start") != window_start
        or existing.get("execution_window_end") != window_end
        or (existing.get("execution_weekdays") or "1,2,3,4,5,6,7") != weekdays
    )
    clear_stale_missed = bool(
        existing
        and existing.get("last_status") == "MISSED"
        and window_changed
        and next_expected
        and next_expected > now
    )

    with get_connection() as conn:
        cursor = conn.cursor()
        if existing:
            cursor.execute("""
                UPDATE jobs
                SET name = ?, language = ?, schedule_cron = ?, expected_interval_minutes = ?, grace_period_minutes = ?,
                    max_duration_minutes = ?, execution_window_start = ?, execution_window_end = ?,
                    execution_weekdays = ?, next_expected_at = ?,
                    last_status = CASE WHEN ? THEN 'PENDING' ELSE last_status END,
                    alert_sent_for_missing = CASE WHEN ? THEN 0 ELSE alert_sent_for_missing END,
                    updated_at = ?
                WHERE job_id = ?
            """, (name, normalized_language, cron, interval, grace, max_dur, window_start, window_end, weekdays,
                  next_expected.isoformat() if next_expected else None,
                  clear_stale_missed, clear_stale_missed, now.isoformat(), job_id))
        else:
            cursor.execute("""
                INSERT INTO jobs (job_id, name, language, schedule_cron, expected_interval_minutes, grace_period_minutes,
                                  max_duration_minutes, execution_window_start, execution_window_end,
                                  execution_weekdays, last_status, next_expected_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            """, (job_id, name, normalized_language, cron, interval, grace, max_dur, window_start, window_end, weekdays,
                  next_expected.isoformat() if next_expected else None, now.isoformat(), now.isoformat()))
        conn.commit()

    return get_job(job_id)

def record_start(job_id: str, job_name: Optional[str] = None, language: Optional[str] = None) -> int:
    now = datetime.now()
    job = get_job(job_id)
    if not job:
        job = register_or_update_job(job_id=job_id, name=job_name or job_id, language=language)

    normalized_language = (language or "").strip().lower() or None
    if normalized_language not in (None, "python", "php", "other"):
        raise ValueError("Linguagem inválida. Use python, php ou other.")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET last_ping_at = ?, last_status = 'RUNNING', language = COALESCE(?, language),
                alert_sent_for_missing = 0, alert_sent_for_timeout = 0, updated_at = ?
            WHERE job_id = ?
        """, (now.isoformat(), normalized_language, now.isoformat(), job_id))

        cursor.execute("""
            INSERT INTO job_executions (job_id, started_at, status, created_at)
            VALUES (?, ?, 'RUNNING', ?)
        """, (job_id, now.isoformat(), now.isoformat()))
        conn.commit()
        return cursor.lastrowid

def record_success(job_id: str, execution_id: Optional[int] = None, duration_seconds: Optional[float] = None) -> Dict[str, Any]:
    now = datetime.now()
    job = get_job(job_id)
    if not job:
        job = register_or_update_job(job_id=job_id)

    next_expected = calculate_next_expected(job, now)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET last_ping_at = ?, last_status = 'SUCCESS', next_expected_at = ?,
                alert_sent_for_missing = 0, updated_at = ?
            WHERE job_id = ?
        """, (now.isoformat(), next_expected.isoformat() if next_expected else None, now.isoformat(), job_id))

        if execution_id:
            cursor.execute("""
                UPDATE job_executions
                SET finished_at = ?, duration_seconds = ?, status = 'SUCCESS'
                WHERE id = ?
            """, (now.isoformat(), duration_seconds, execution_id))
        else:
            # Encontra a última execução em aberto deste job
            cursor.execute("""
                SELECT id, started_at FROM job_executions
                WHERE job_id = ? AND status = 'RUNNING'
                ORDER BY id DESC LIMIT 1
            """, (job_id,))
            row = cursor.fetchone()
            if row:
                exec_id, started_at = row["id"], row["started_at"]
                if not duration_seconds and started_at:
                    try:
                        st = datetime.fromisoformat(started_at)
                        duration_seconds = (now - st).total_seconds()
                    except Exception:
                        pass
                cursor.execute("""
                    UPDATE job_executions
                    SET finished_at = ?, duration_seconds = ?, status = 'SUCCESS'
                    WHERE id = ?
                """, (now.isoformat(), duration_seconds, exec_id))
            else:
                cursor.execute("""
                    INSERT INTO job_executions (job_id, started_at, finished_at, duration_seconds, status, created_at)
                    VALUES (?, ?, ?, ?, 'SUCCESS', ?)
                """, (job_id, now.isoformat(), now.isoformat(), duration_seconds or 0, now.isoformat()))

        conn.commit()

    return get_job(job_id)

def record_failure(
    job_id: str,
    error_message: str,
    traceback_str: Optional[str] = None,
    execution_id: Optional[int] = None,
    duration_seconds: Optional[float] = None
) -> Dict[str, Any]:
    now = datetime.now()
    job = get_job(job_id)
    if not job:
        job = register_or_update_job(job_id=job_id)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET last_ping_at = ?, last_status = 'FAILED', updated_at = ?
            WHERE job_id = ?
        """, (now.isoformat(), now.isoformat(), job_id))

        if execution_id:
            cursor.execute("""
                UPDATE job_executions
                SET finished_at = ?, duration_seconds = ?, status = 'FAILED',
                    error_message = ?, traceback = ?
                WHERE id = ?
            """, (now.isoformat(), duration_seconds, error_message, traceback_str, execution_id))
        else:
            cursor.execute("""
                SELECT id, started_at FROM job_executions
                WHERE job_id = ? AND status = 'RUNNING'
                ORDER BY id DESC LIMIT 1
            """, (job_id,))
            row = cursor.fetchone()
            if row:
                exec_id, started_at = row["id"], row["started_at"]
                if not duration_seconds and started_at:
                    try:
                        st = datetime.fromisoformat(started_at)
                        duration_seconds = (now - st).total_seconds()
                    except Exception:
                        pass
                cursor.execute("""
                    UPDATE job_executions
                    SET finished_at = ?, duration_seconds = ?, status = 'FAILED',
                        error_message = ?, traceback = ?
                    WHERE id = ?
                """, (now.isoformat(), duration_seconds, error_message, traceback_str, exec_id))
            else:
                cursor.execute("""
                    INSERT INTO job_executions (job_id, started_at, finished_at, duration_seconds, status, error_message, traceback, created_at)
                    VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?)
                """, (job_id, now.isoformat(), now.isoformat(), duration_seconds or 0, error_message, traceback_str, now.isoformat()))

        conn.commit()

    return get_job(job_id)

def mark_missed(job_id: str) -> None:
    now = datetime.now()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET last_status = 'MISSED', alert_sent_for_missing = 1, updated_at = ?
            WHERE job_id = ?
        """, (now.isoformat(), job_id))

        cursor.execute("""
            INSERT INTO job_executions (job_id, started_at, finished_at, duration_seconds, status, error_message, created_at)
            VALUES (?, ?, ?, 0, 'MISSED', 'Automação ausente: prazo estourado sem execução', ?)
        """, (job_id, now.isoformat(), now.isoformat(), now.isoformat()))
        conn.commit()

def mark_timeout(job_id: str, max_duration_minutes: int, duration_seconds: float) -> Dict[str, Any]:
    """Marca um job como travado (TIMEOUT) e finaliza a execução aberta com mensagem descritiva."""
    now = datetime.now()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET last_status = 'TIMEOUT', alert_sent_for_timeout = 1, updated_at = ?
            WHERE job_id = ?
        """, (now.isoformat(), job_id))

        cursor.execute("""
            SELECT id FROM job_executions
            WHERE job_id = ? AND status = 'RUNNING'
            ORDER BY id DESC LIMIT 1
        """, (job_id,))
        row = cursor.fetchone()
        dur_h = duration_seconds / 3600
        msg = f"Tempo limite excedido: executando há {dur_h:.1f}h (limite: {max_duration_minutes}m). Possível travamento ou processo encerrado abruptamente."
        if row:
            cursor.execute("""
                UPDATE job_executions
                SET finished_at = ?, duration_seconds = ?, status = 'TIMEOUT', error_message = ?
                WHERE id = ?
            """, (now.isoformat(), duration_seconds, msg, row["id"]))
        else:
            cursor.execute("""
                INSERT INTO job_executions (job_id, started_at, finished_at, duration_seconds, status, error_message, created_at)
                VALUES (?, ?, ?, ?, 'TIMEOUT', ?, ?)
            """, (job_id, now.isoformat(), now.isoformat(), duration_seconds, msg, now.isoformat()))

        conn.commit()
    return get_job(job_id)


def get_recent_executions(limit: int = 30, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        if job_id:
            cursor.execute("""
                SELECT * FROM job_executions
                WHERE job_id = ?
                ORDER BY id DESC LIMIT ?
            """, (job_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM job_executions
                ORDER BY id DESC LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_executions_between(
    started_from: datetime,
    started_to: datetime,
    job_id: Optional[str] = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """Consulta execuções dentro de um período civil usando timestamps persistidos pelo Sentinel."""
    safe_limit = max(1, min(int(limit), 10000))
    clauses = ["COALESCE(started_at, created_at) >= ?", "COALESCE(started_at, created_at) < ?"]
    parameters: List[Any] = [started_from.isoformat(), started_to.isoformat()]
    if job_id:
        clauses.append("job_id = ?")
        parameters.append(job_id)
    parameters.append(safe_limit)

    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            SELECT * FROM job_executions
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT ?
            """,
            parameters,
        )
        return [dict(row) for row in cursor.fetchall()]


def get_database_health() -> Dict[str, Any]:
    """Retorna uma verificação leve do SQLite sem expor credenciais ou caminhos locais."""
    with get_connection() as conn:
        conn.execute("SELECT 1").fetchone()
        jobs_count = conn.execute("SELECT COUNT(*) AS total FROM jobs").fetchone()["total"]
        executions_count = conn.execute("SELECT COUNT(*) AS total FROM job_executions").fetchone()["total"]
        row = conn.execute("""
            SELECT MAX(changed_at) AS last_updated_at
            FROM (
                SELECT MAX(updated_at) AS changed_at FROM jobs
                UNION ALL
                SELECT MAX(COALESCE(finished_at, started_at, created_at)) AS changed_at
                FROM job_executions
            )
        """).fetchone()
        return {
            "connected": True,
            "jobs_count": jobs_count,
            "executions_count": executions_count,
            "last_updated_at": row["last_updated_at"] if row else None,
        }

def delete_job(job_id: str) -> bool:
    """Remove um job e todo o seu histórico de execuções."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM job_executions WHERE job_id = ?", (job_id,))
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return cursor.rowcount > 0


def create_telegram_report_schedule(
    chat_id: str,
    report_type: str,
    schedule_time: str,
    weekdays: Any,
    job_id: Optional[str] = None,
    history_limit: int = 5,
) -> Dict[str, Any]:
    report_type = report_type.strip().lower()
    if report_type not in ("status", "ultimas"):
        raise ValueError("Tipo de relatório inválido.")
    try:
        normalized_time = datetime.strptime(schedule_time.strip(), "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError("Horário inválido. Use HH:MM.") from exc
    normalized_days = ",".join(str(day) for day in _parse_weekdays(weekdays))
    history_limit = max(1, min(int(history_limit), 20))
    if report_type == "ultimas" and not job_id:
        raise ValueError("Informe o job_id para o relatório de últimas execuções.")
    if job_id and not get_job(job_id):
        raise ValueError(f"Automação '{job_id}' não encontrada.")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO telegram_report_schedules
                (chat_id, report_type, job_id, schedule_time, weekdays, history_limit)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(chat_id), report_type, job_id, normalized_time, normalized_days, history_limit))
        schedule_id = cursor.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM telegram_report_schedules WHERE id = ?", (schedule_id,)).fetchone()
        return dict(row)


def list_telegram_report_schedules(chat_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM telegram_report_schedules
            WHERE chat_id = ? AND enabled = 1
            ORDER BY schedule_time, id
        """, (str(chat_id),)).fetchall()
        return [dict(row) for row in rows]


def delete_telegram_report_schedule(schedule_id: int, chat_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM telegram_report_schedules WHERE id = ? AND chat_id = ?",
            (schedule_id, str(chat_id)),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_due_telegram_report_schedules(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now()
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    weekday = str(now.isoweekday())
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM telegram_report_schedules
            WHERE enabled = 1 AND schedule_time = ?
              AND (last_sent_on IS NULL OR last_sent_on != ?)
        """, (current_time, today)).fetchall()
    return [
        dict(row) for row in rows
        if weekday in str(row["weekdays"]).split(",")
    ]


def mark_telegram_report_sent(schedule_id: int, sent_on: Optional[str] = None) -> None:
    sent_on = sent_on or datetime.now().date().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE telegram_report_schedules SET last_sent_on = ? WHERE id = ?",
            (sent_on, schedule_id),
        )
        conn.commit()
