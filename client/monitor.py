import time
import json
import traceback
import functools
from urllib import request, error
from typing import Optional, Callable, Any

DEFAULT_SERVER_URL = "http://127.0.0.1:8050"

def _http_post(url: str, payload: dict, timeout: float = 5.0) -> Optional[dict]:
    """Envia requisição POST HTTP usando apenas a biblioteca padrão do Python (sem dependências extras)."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Sentinel-Client/1.0"},
            method="POST"
        )
        with request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                resp_data = response.read().decode("utf-8")
                return json.loads(resp_data)
    except Exception as exc:
        print(f"[Sentinel Monitor Warning] Não foi possível contatar o servidor central ({url}): {exc}")
    return None

class SentinelMonitor:
    """Context Manager para monitorar execuções de blocos de código."""
    def __init__(
        self,
        job_id: str,
        name: Optional[str] = None,
        server_url: str = DEFAULT_SERVER_URL,
        timeout: float = 5.0
    ):
        self.job_id = job_id
        self.name = name or job_id
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.execution_id: Optional[int] = None
        self.start_time: float = 0.0

    def __enter__(self):
        self.start_time = time.time()
        start_payload = {"job_name": self.name, "language": "python"}
        resp = _http_post(f"{self.server_url}/api/ping/{self.job_id}/start", start_payload, timeout=self.timeout)
        if resp and "execution_id" in resp:
            self.execution_id = resp["execution_id"]
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time

        if exc_type is not None:
            # Houve erro
            tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            fail_payload = {
                "error_message": str(exc_val) or exc_type.__name__,
                "traceback": tb_str,
                "execution_id": self.execution_id,
                "duration_seconds": duration
            }
            _http_post(f"{self.server_url}/api/ping/{self.job_id}/fail", fail_payload, timeout=self.timeout)
            # Retorna False para propagar a exceção original no script do usuário
            return False
        else:
            # Sucesso
            success_payload = {
                "execution_id": self.execution_id,
                "duration_seconds": duration
            }
            _http_post(f"{self.server_url}/api/ping/{self.job_id}/success", success_payload, timeout=self.timeout)
            return True

def monitor_job(
    job_id: str,
    name: Optional[str] = None,
    server_url: str = DEFAULT_SERVER_URL,
    timeout: float = 5.0
):
    """
    Decorator para envelopar funções de automação.
    
    Exemplo:
        @monitor_job(job_id="relatorio_diario", name="Relatório Diário de Vendas")
        def gerar_relatorio():
            # código da automação aqui
            pass
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with SentinelMonitor(
                job_id=job_id,
                name=name or func.__name__,
                server_url=server_url,
                timeout=timeout
            ):
                return func(*args, **kwargs)
        return wrapper
    return decorator
