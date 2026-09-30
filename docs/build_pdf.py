import os
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)

DOCS_DIR = Path(__file__).resolve().parent
PDF_PATH = DOCS_DIR / "DOCUMENTACAO.pdf"

def generate_pdf():
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm
    )

    styles = getSampleStyleSheet()

    # Estilos customizados
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=5
    )

    bullet_style = ParagraphStyle(
        "Bullet_Custom",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=3
    )

    code_style = ParagraphStyle(
        "Code_Custom",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#F8FAFC")
    )

    callout_style = ParagraphStyle(
        "Callout_Custom",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1E3A8A")
    )

    story = []

    # Cabeçalho
    story.append(Paragraph("SENTINEL - MONITOR DE AUTOMAÇÕES", title_style))
    story.append(Paragraph("Documentação Técnica, Arquitetura e Manual Operacional - v1.5", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#4F46E5"), spaceAfter=12))

    # 1. Visão Geral
    story.append(Paragraph("1. Visão Geral", h1_style))
    story.append(Paragraph(
        "O <b>Sentinel</b> é um sistema centralizador, leve e autônomo, desenvolvido em Python para monitorar "
        "a saúde de tarefas agendadas, rotinas batch e robôs de automação corporativos.",
        body_style
    ))
    story.append(Paragraph(
        "<i>\"Um script que não roda não consegue enviar uma mensagem avisando que não rodou.\"</i>",
        ParagraphStyle("Quote", parent=body_style, fontName="Helvetica-Oblique", textColor=colors.HexColor("#475569"), leftIndent=12)
    ))
    story.append(Paragraph(
        "O sistema elimina pontos cegos operacionais atuando em duas frentes complementares:",
        body_style
    ))
    story.append(Paragraph("- <b>Notificação Ativa de Erro (Push):</b> Intercepta falhas em tempo de execução via decorador e envia alerta com duração e <i>traceback</i> completo da falha.", bullet_style))
    story.append(Paragraph("- <b>Dead Man's Switch (Monitor de Ausência):</b> Vigia contínuo em segundo plano que aguarda o sinal de vida do script. Se o script não executar dentro do horário previsto mais a tolerância, o Sentinel soa o alarme no Telegram.", bullet_style))

    # 2. Heartbeat e Falha Silenciosa
    story.append(Paragraph("2. O Conceito de Heartbeat e a Falha Silenciosa", h1_style))
    story.append(Paragraph(
        "<b>Heartbeat</b> (<i>batimento cardíaco</i>) é o padrão de engenharia usado para verificar se um sistema está vivo e ativo. "
        "A melhor analogia é o <b>monitor cardíaco de um hospital</b>:",
        body_style
    ))
    story.append(Paragraph("- Enquanto o paciente está vivo, o monitor emite batimentos regulares: <i>bip... bip... bip...</i>", bullet_style))
    story.append(Paragraph("- O médico não precisa perguntar a cada segundo se o paciente vive: o batimento periódico atesta a saúde.", bullet_style))
    story.append(Paragraph("- Se o coração parar (silêncio), o monitor detecta a ausência e dispara a sirene de emergência: <b>PIIIIIIIIII!</b>", bullet_style))
    story.append(Paragraph(
        "<b>Por que arquivos de log falham?</b> Em falhas silenciosas (computador desligado por engano, agendador de tarefas travado, queda de energia ou erro de memória), "
        "<b>o script sequer chega a iniciar</b>. Ele não gera log nem envia e-mails. Com o Heartbeat do Sentinel, <b>a ausência de sinal é uma má notícia</b>.",
        body_style
    ))

    # 3. Arquitetura
    story.append(Paragraph("3. Arquitetura e Stack de Tecnologias", h1_style))
    comp_data = [
        [Paragraph("<b>Componente</b>", body_style), Paragraph("<b>Tecnologia</b>", body_style), Paragraph("<b>Responsabilidade</b>", body_style)],
        [Paragraph("Backend API", body_style), Paragraph("FastAPI (Porta 8050)", body_style), Paragraph("Recebe requisições de start, success e fail em alta velocidade.", body_style)],
        [Paragraph("Banco de Dados", body_style), Paragraph("SQLite (sentinel.db)", body_style), Paragraph("Persistência em arquivo único com histórico e janelas esperadas.", body_style)],
        [Paragraph("Vigia em Background", body_style), Paragraph("APScheduler", body_style), Paragraph("Inspeciona o banco a cada 15s verificando automações ausentes.", body_style)],
        [Paragraph("Disparador", body_style), Paragraph("Telegram Bot API / Console", body_style), Paragraph("Entrega mensagens formatadas em HTML com blocos de código.", body_style)],
        [Paragraph("Dashboard Web", body_style), Paragraph("Tailwind CSS + Jinja2", body_style), Paragraph("Interface web moderna com métricas e visualizador de erros.", body_style)],
        [Paragraph("Clientes SDK", body_style), Paragraph("Python e PHP nativos", body_style), Paragraph("Decorador Python e wrapper PHP com identificação automática da linguagem.", body_style)],
        [Paragraph("MCP App", body_style), Paragraph("Node.js + MCP Apps", body_style), Paragraph("Ferramentas somente leitura e painel visual para ChatGPT, Codex e hosts MCP compatíveis.", body_style)],
    ]
    t_comp = Table(comp_data, colWidths=[3.2*cm, 4.2*cm, 10.4*cm])
    t_comp.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(t_comp)
    story.append(Spacer(1, 8))

    # 4. A Função Decoradora
    story.append(Paragraph("4. Como Funciona a Função Decoradora (@monitor_job)", h1_style))
    story.append(Paragraph(
        "Um <b>decorador</b> funciona como uma <b>\"capa protetora\"</b> ou <b>\"vigia\"</b> colocado em volta da função sem alterar a regra de negócio interna. "
        "Ele adota a arquitetura clássica de 3 camadas:",
        body_style
    ))
    story.append(Paragraph("1. <code>monitor_job(...)</code>: Recebe parâmetros de configuração (job_id, name, server_url).", bullet_style))
    story.append(Paragraph("2. <code>decorator(func)</code>: Recebe a função original que foi decorada (ex: def main).", bullet_style))
    story.append(Paragraph("3. <code>wrapper(*args, **kwargs)</code>: O 'dublê' que executa no lugar da sua função dentro do contexto <code>SentinelMonitor</code>.", bullet_style))
    story.append(Paragraph(
        "<b>Ciclo de Vida:</b> No <code>__enter__</code>, avisa o Sentinel que iniciou (Executando). Se der sucesso, envia duração (OK). "
        "Se der erro, no <code>__exit__</code> extrai o <i>traceback</i> completo, dispara o alerta no Telegram e <b>relança a exceção original</b> (<code>raise e</code>) sem mascarar falhas.",
        body_style
    ))

    code_text = (
        "from monitor import monitor_job\n\n"
        "@monitor_job(job_id=\"meu_job\", name=\"Nome da Automacao\")\n"
        "def main():\n"
        "    try:\n"
        "        processar_dados()\n"
        "    except Exception as e:\n"
        "        logger.error(\"Erro no processamento\", exc_info=e)\n"
        "        raise e  # <- OBRIGATORIO: relancar para o Sentinel alertar!"
    )
    t_code = Table([[Paragraph(code_text.replace("\n", "<br/>").replace(" ", "&nbsp;"), code_style)]], colWidths=[17.8*cm])
    t_code.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#0F172A")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_code)
    story.append(Spacer(1, 6))

    story.append(Paragraph("4.1 Integração PHP e Identificação de Linguagem", h2_style))
    story.append(Paragraph(
        "O cliente <code>sentinel_monitor.php</code> envolve uma função PHP e registra início, sucesso, falha, duração e stack trace. "
        "Use <code>sentinel_fail($mensagem)</code> no lugar de <code>die($mensagem)</code> para preservar o detalhe da falha.",
        body_style
    ))
    php_code = (
        "require_once __DIR__ . '/sentinel_monitor.php';\n\n"
        "sentinel_monitor(\n"
        "    'monitoramento_nf_email',\n"
        "    'Monitoramento de notas fiscais',\n"
        "    'executarMonitoramento'\n"
        ");"
    )
    t_php_code = Table([[Paragraph(php_code.replace("\n", "<br/>").replace(" ", "&nbsp;"), code_style)]], colWidths=[17.8*cm])
    t_php_code.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#0F172A")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_php_code)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "O cliente Python envia <code>language: python</code> e o cliente PHP envia <code>language: php</code>. "
        "O dashboard apresenta o ícone do Python ou o elefante do PHP ao lado do job. Jobs antigos recebem a linguagem na próxima execução com o cliente atualizado.",
        body_style
    ))
    story.append(Paragraph(
        "Em scripts divididos em vários ciclos HTTP, use <code>return</code> depois de emitir o redirecionamento, em vez de <code>exit</code>. "
        "Relance erros capturados nos lotes e use <code>sentinel_fail(...)</code> se a fila não avançar ou atingir o limite de ciclos.",
        body_style
    ))
    story.append(Paragraph(
        "No retorno bancário Grafeno, o cliente pode ser importado da pasta anterior com <code>__DIR__ . '/../sentinel_monitor.php'</code>. "
        "Falhas de API, banco, download, log e cópia são monitoradas; paginação e troca de empresa terminam com <code>return</code>. "
        "Nunca inclua o header Authorization nem o token da API nos alertas.",
        body_style
    ))

    # 5. Inicialização e Telegram
    story.append(Paragraph("5. Inicialização do Serviço e Telegram", h1_style))
    story.append(Paragraph("- <b>Iniciar Serviço:</b> Duplo clique no atalho <code>run.bat</code> ou comando <code>python -m uvicorn app.main:app --host 127.0.0.1 --port 8050 --reload</code>.", bullet_style))
    story.append(Paragraph("- <b>Painel Web:</b> <u>http://127.0.0.1:8050</u> | <b>Documentação Swagger:</b> <u>http://127.0.0.1:8050/docs</u>", bullet_style))
    story.append(Paragraph("- <b>Telegram:</b> Crie o bot no <b>@BotFather</b> (<code>/newbot</code>), capture seu Chat ID com <b>@userinfobot</b> e configure no arquivo <code>.env</code>.", bullet_style))
    story.append(Paragraph("5.1 MCP App para ChatGPT e Codex", h2_style))
    story.append(Paragraph(
        "O diretório <code>mcp-app/</code> fornece um servidor MCP somente leitura. Ele consulta a API REST do Sentinel e expõe as ferramentas "
        "<code>sentinel_list_jobs</code>, <code>sentinel_get_executions</code> e <code>sentinel_render_status</code>. A última ferramenta entrega um painel visual "
        "compatível com o padrão MCP Apps; nenhuma delas cadastra, edita, remove ou envia pings.",
        body_style
    ))
    story.append(Paragraph(
        "- <b>Inicialização:</b> Execute <code>npm.cmd install</code> e <code>npm.cmd start</code> dentro de <code>mcp-app</code>, ou use <code>run_mcp.bat</code>.",
        bullet_style
    ))
    story.append(Paragraph(
        "- <b>Endpoint:</b> <u>http://127.0.0.1:8787/mcp</u>. Ajuste <code>SENTINEL_API_URL</code>, <code>MCP_HOST</code> e <code>MCP_PORT</code> no <code>.env</code>.",
        bullet_style
    ))
    story.append(Paragraph(
        "- <b>Segurança:</b> Para acesso remoto, publique por HTTPS e adicione autenticação antes de expor dados operacionais.",
        bullet_style
    ))

    # 6. Automações Ativas
    story.append(Paragraph("6. Automações Ativas Monitoradas", h1_style))
    jobs_data = [
        [Paragraph("<b>Job ID</b>", body_style), Paragraph("<b>Nome</b>", body_style), Paragraph("<b>Caminho do Script</b>", body_style)],
        [Paragraph("Crypt_Lamina", body_style), Paragraph("Criptografia PDF Lâmina", body_style), Paragraph("C:\\Automações\\crypt_lamina\\main.py", body_style)],
        [Paragraph("Slipagem_NetFactor", body_style), Paragraph("Slipagem NetFactor", body_style), Paragraph("C:\\Automações\\slipagem\\main.py", body_style)],
    ]
    t_jobs = Table(jobs_data, colWidths=[4*cm, 5.8*cm, 8*cm])
    t_jobs.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_jobs)

    # Constrói o PDF
    doc.build(story)
    print(f"PDF gerado com sucesso em: {PDF_PATH}")

if __name__ == "__main__":
    generate_pdf()
