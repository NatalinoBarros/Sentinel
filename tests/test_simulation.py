import sys
import time
import requests
from pathlib import Path

# Garante suporte a UTF-8 no terminal Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from client.monitor import monitor_job

SERVER_URL = "http://127.0.0.1:8050"

print("="*60)
print("[*] INICIANDO BATERIA DE TESTES DO SENTINEL")
print("="*60)

# 1. Teste de Sucesso
@monitor_job(job_id="automacao_sucesso", name="Extracao Diaria de Vendas", server_url=SERVER_URL)
def tarefa_com_sucesso():
    print("\n[1] Executando tarefa_com_sucesso()...")
    time.sleep(1.0)
    print(" -> Processamento concluido com sucesso!")
    return True

# 2. Teste de Erro (captura de traceback)
@monitor_job(job_id="automacao_com_falha", name="Sincronizacao ERP Bancario", server_url=SERVER_URL)
def tarefa_com_falha():
    print("\n[2] Executando tarefa_com_falha()...")
    time.sleep(0.5)
    print(" -> Simulando erro critico (Divisao por zero)...")
    resultado = 10 / 0
    return resultado

# 3. Teste do Dead Man's Switch (Ausência)
def simular_dead_mans_switch():
    print("\n[3] Configurando job para teste de Dead Man's Switch (Ausencia)...")
    payload = {
        "job_id": "automacao_fantasma",
        "name": "Robo Noturno de Backup",
        "expected_interval_minutes": 0,
        "grace_period_minutes": 0
    }
    resp = requests.post(f"{SERVER_URL}/api/jobs", json=payload)
    print(f" -> Job cadastrado: {resp.json()['name']} ({resp.json()['job_id']})")
    print(" -> O script 'automacao_fantasma' NAO sera executado.")
    print(" -> O Sentinel (APScheduler) identificara a falta de sinal e disparara o alerta!")

if __name__ == "__main__":
    # Testa se o servidor esta online
    try:
        r = requests.get(f"{SERVER_URL}/api/jobs", timeout=3)
        print("[+] Servidor Sentinel esta online e respondendo!\n")
    except Exception as e:
        print(f"[-] Erro: O servidor Sentinel nao esta rodando em {SERVER_URL}.")
        print("Inicie o servidor primeiro com: python -m uvicorn app.main:app --port 8050")
        sys.exit(1)

    # Executa teste 1: Sucesso
    try:
        tarefa_com_sucesso()
        print("[+] Teste 1 finalizado (Sucesso registrado no Sentinel).")
    except Exception as e:
        print(f"[-] Erro no teste 1: {e}")

    # Executa teste 2: Falha controlada
    try:
        tarefa_com_falha()
    except ZeroDivisionError:
        print("[+] Teste 2 finalizado (Excecao capturada pelo decorator e alerta enviado).")

    # Executa teste 3: Dead man's switch
    simular_dead_mans_switch()

    print("\n" + "="*60)
    print("[*] Bateria concluida com sucesso!")
    print("Acesse o painel web no navegador: http://127.0.0.1:8050")
    print("="*60)
