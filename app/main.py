import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator

from app.config import TEMPLATES_DIR, STATIC_DIR, HOST, PORT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from app.database import (
    init_db,
    list_jobs,
    get_job,
    register_or_update_job,
    record_start,
    record_success,
    record_failure,
    get_recent_executions,
    delete_job
)
from app.scheduler import start_scheduler, stop_scheduler
from app.notifier import notify_failure, send_telegram_message

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    os.makedirs(STATIC_DIR, exist_ok=True)
    init_db()
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()

app = FastAPI(
    title="Sentinel - Automation Monitor",
    description="Centralizador de Monitoramento, Heartbeats e Alertas para Automações",
    version="1.0.0",
    lifespan=lifespan
)

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# --- Modelos Pydantic ---
class JobRegisterRequest(BaseModel):
    job_id: str
    name: Optional[str] = None
    language: Optional[Literal["python", "php", "other"]] = None
    schedule_cron: Optional[str] = None
    expected_interval_minutes: Optional[int] = 1440
    grace_period_minutes: Optional[int] = 15
    max_duration_minutes: Optional[int] = 60
    execution_window_start: Optional[str] = None
    execution_window_end: Optional[str] = None
    execution_weekdays: Optional[List[int]] = None

    @model_validator(mode="after")
    def validate_execution_window(self):
        start_value = (self.execution_window_start or "").strip()
        end_value = (self.execution_window_end or "").strip()
        if bool(start_value) != bool(end_value):
            raise ValueError("Informe o início e o fim da janela de execução.")
        if start_value:
            try:
                start = datetime.strptime(start_value, "%H:%M").time()
                end = datetime.strptime(end_value, "%H:%M").time()
            except ValueError as exc:
                raise ValueError("Use o formato HH:MM na janela de execução.") from exc
            if start >= end:
                raise ValueError("O fim da janela deve ser posterior ao início.")
        if self.execution_weekdays is not None:
            if not self.execution_weekdays:
                raise ValueError("Selecione ao menos um dia da semana.")
            if any(day < 1 or day > 7 for day in self.execution_weekdays):
                raise ValueError("Os dias da semana devem estar entre 1 e 7.")
        return self

class PingStartRequest(BaseModel):
    job_name: Optional[str] = None
    language: Optional[Literal["python", "php", "other"]] = None

class PingSuccessRequest(BaseModel):
    execution_id: Optional[int] = None
    duration_seconds: Optional[float] = None

class PingFailRequest(BaseModel):
    error_message: str
    traceback: Optional[str] = None
    execution_id: Optional[int] = None
    duration_seconds: Optional[float] = None

# --- Rotas Web ---
@app.get("/", response_class=FileResponse)
async def get_dashboard():
    """Renderiza o painel visual de monitoramento."""
    dashboard_path = TEMPLATES_DIR / "dashboard.html"
    return FileResponse(str(dashboard_path))


# --- Rotas de API ---
@app.get("/api/jobs")
def api_list_jobs():
    return list_jobs()

@app.post("/api/jobs")
def api_register_job(payload: JobRegisterRequest):
    job = register_or_update_job(
        job_id=payload.job_id,
        name=payload.name,
        language=payload.language,
        schedule_cron=payload.schedule_cron,
        expected_interval_minutes=payload.expected_interval_minutes,
        grace_period_minutes=payload.grace_period_minutes,
        max_duration_minutes=payload.max_duration_minutes,
        execution_window_start=payload.execution_window_start,
        execution_window_end=payload.execution_window_end,
        execution_weekdays=payload.execution_weekdays
    )
    return job


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str):
    """Remove um job e todo o seu histórico."""
    deleted = delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return {"status": "ok", "message": f"Job {job_id} removido com sucesso"}


@app.post("/api/ping/{job_id}/start")
def api_ping_start(job_id: str, payload: Optional[PingStartRequest] = None):
    """O script avisa que começou a rodar."""
    job_name = payload.job_name if payload else None
    language = payload.language if payload else None
    exec_id = record_start(job_id=job_id, job_name=job_name, language=language)
    return {"status": "ok", "message": "Início registrado", "execution_id": exec_id}

@app.post("/api/ping/{job_id}/success")
def api_ping_success(job_id: str, payload: Optional[PingSuccessRequest] = None):
    """O script avisa que finalizou com sucesso."""
    exec_id = payload.execution_id if payload else None
    duration = payload.duration_seconds if payload else None
    job = record_success(job_id=job_id, execution_id=exec_id, duration_seconds=duration)
    return {"status": "ok", "message": "Sucesso registrado", "job": job}

@app.post("/api/ping/{job_id}/fail")
async def api_ping_fail(job_id: str, payload: PingFailRequest):
    """O script avisa que falhou, registrando erro e enviando notificação imediata."""
    job = record_failure(
        job_id=job_id,
        error_message=payload.error_message,
        traceback_str=payload.traceback,
        execution_id=payload.execution_id,
        duration_seconds=payload.duration_seconds
    )
    # Dispara o alerta para o Telegram / Console
    await notify_failure(
        job=job,
        error_message=payload.error_message,
        traceback_str=payload.traceback,
        duration_seconds=payload.duration_seconds
    )
    return {"status": "ok", "message": "Falha registrada e alerta disparado"}

@app.get("/api/executions")
def api_list_executions(limit: int = 30, job_id: Optional[str] = None):
    return get_recent_executions(limit=limit, job_id=job_id)

@app.post("/api/test-telegram")
async def api_test_telegram():
    """Envia uma mensagem de teste para o canal configurado."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=400, detail="Telegram não configurado no arquivo .env")
    
    msg = (
        "🤖 <b>TESTE DE CONEXÃO SENTINEL</b>\n"
        "O seu centralizador de monitoramento de automações está conectado com sucesso ao Telegram!"
    )
    ok = await send_telegram_message(msg)
    if ok:
        return {"status": "ok", "message": "Mensagem enviada com sucesso no Telegram!"}
    else:
        raise HTTPException(status_code=500, detail="Falha ao enviar mensagem no Telegram. Verifique o Token e Chat ID.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
