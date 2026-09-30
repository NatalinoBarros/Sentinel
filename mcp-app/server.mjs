import { createServer as createHttpServer } from "node:http";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";

import {
  buildAttentionQueue,
  calculateMetrics,
  compareMetrics,
  diagnoseJob,
} from "./analytics.mjs";
import { createProactiveMonitor } from "./proactive-monitor.mjs";

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
const WIDGET_URI = "ui://sentinel/status/v1.html";
// The URI is a cache key for MCP App hosts. Bump it whenever the widget HTML
// changes materially so connected clients do not reuse an older interface.
const OPERATIONS_WIDGET_URI = "ui://sentinel/operations/v3.html";
const MCP_PATH = "/mcp";
const DEFAULT_API_URL = "http://127.0.0.1:8050";
const DEFAULT_TIMEOUT_MS = 8_000;
const MCP_VERSION = "0.4.0";
const MCP_STARTED_AT = new Date();
const widgetHtml = readFileSync(resolve(MODULE_DIR, "public", "sentinel-widget.html"), "utf8");
const operationsWidgetHtml = readFileSync(resolve(MODULE_DIR, "public", "operations-widget.html"), "utf8");

const statusValues = ["PENDING", "RUNNING", "SUCCESS", "FAILED", "MISSED", "TIMEOUT"];

const jobSchema = z.object({
  jobId: z.string(),
  name: z.string(),
  language: z.string().nullable(),
  status: z.string(),
  lastPingAt: z.string().nullable(),
  nextExpectedAt: z.string().nullable(),
  expectedIntervalMinutes: z.number().nullable(),
  gracePeriodMinutes: z.number().nullable(),
  maxDurationMinutes: z.number().nullable(),
  executionWindowStart: z.string().nullable(),
  executionWindowEnd: z.string().nullable(),
  executionWeekdays: z.string().nullable(),
});

const executionSchema = z.object({
  id: z.number(),
  jobId: z.string(),
  status: z.string(),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
  durationSeconds: z.number().nullable(),
  errorMessage: z.string().nullable(),
  traceback: z.string().nullable(),
});

const summarySchema = z.object({
  total: z.number(),
  healthy: z.number(),
  running: z.number(),
  failed: z.number(),
  missed: z.number(),
  pending: z.number(),
});

const attentionItemSchema = z.object({
  jobId: z.string(),
  name: z.string(),
  status: z.string(),
  severity: z.string(),
  score: z.number(),
  reason: z.string(),
  since: z.string().nullable(),
  nextExpectedAt: z.string().nullable(),
});

const metricsSchema = z.object({
  period: z.object({ from: z.string(), to: z.string(), label: z.string().optional() }),
  totalExecutions: z.number(),
  successCount: z.number(),
  failureCount: z.number(),
  missedCount: z.number(),
  timeoutCount: z.number(),
  runningCount: z.number(),
  successRate: z.number(),
  absenceRate: z.number(),
  averageDurationSeconds: z.number().nullable(),
  p95DurationSeconds: z.number().nullable(),
  durationViolations: z.number(),
  statusCounts: z.record(z.number()),
});

function asNullableString(value) {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function asNullableNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function normalizeJob(job) {
  return {
    jobId: String(job.job_id ?? ""),
    name: String(job.name ?? job.job_id ?? "Automação sem nome"),
    language: asNullableString(job.language),
    status: String(job.last_status ?? "PENDING").toUpperCase(),
    lastPingAt: asNullableString(job.last_ping_at),
    nextExpectedAt: asNullableString(job.next_expected_at),
    expectedIntervalMinutes: asNullableNumber(job.expected_interval_minutes),
    gracePeriodMinutes: asNullableNumber(job.grace_period_minutes),
    maxDurationMinutes: asNullableNumber(job.max_duration_minutes),
    executionWindowStart: asNullableString(job.execution_window_start),
    executionWindowEnd: asNullableString(job.execution_window_end),
    executionWeekdays: asNullableString(job.execution_weekdays),
  };
}

export function normalizeExecution(execution) {
  return {
    id: Number(execution.id),
    jobId: String(execution.job_id ?? ""),
    status: String(execution.status ?? "PENDING").toUpperCase(),
    startedAt: asNullableString(execution.started_at),
    finishedAt: asNullableString(execution.finished_at),
    durationSeconds: asNullableNumber(execution.duration_seconds),
    errorMessage: asNullableString(execution.error_message),
    traceback: asNullableString(execution.traceback),
  };
}

export function summarizeJobs(jobs) {
  const summary = { total: jobs.length, healthy: 0, running: 0, failed: 0, missed: 0, pending: 0 };
  for (const job of jobs) {
    if (job.status === "SUCCESS") summary.healthy += 1;
    else if (job.status === "RUNNING") summary.running += 1;
    else if (job.status === "FAILED" || job.status === "TIMEOUT") summary.failed += 1;
    else if (job.status === "MISSED") summary.missed += 1;
    else summary.pending += 1;
  }
  return summary;
}

function normalizeApiUrl(apiUrl) {
  return (apiUrl || DEFAULT_API_URL).replace(/\/+$/, "");
}

async function fetchJson(apiUrl, pathname, fetchImpl = fetch) {
  const url = `${normalizeApiUrl(apiUrl)}${pathname}`;
  let response;
  try {
    response = await fetchImpl(url, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
    });
  } catch (error) {
    throw new Error(`Sentinel indisponível em ${normalizeApiUrl(apiUrl)}: ${error.message}`);
  }

  if (!response.ok) {
    const detail = (await response.text()).slice(0, 500).trim();
    throw new Error(`Sentinel respondeu HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
  }
  return response.json();
}

async function updateJobSchedule(apiUrl, { jobId, scheduleCron, executionWeekdays }, fetchImpl = fetch) {
  const rawJobs = await fetchJson(apiUrl, "/api/jobs", fetchImpl);
  const current = rawJobs.find((job) => String(job.job_id) === jobId);
  if (!current) throw new Error(`Automação '${jobId}' não encontrada.`);

  const payload = {
    job_id: jobId,
    name: current.name,
    language: current.language,
    schedule_cron: scheduleCron,
    expected_interval_minutes: current.expected_interval_minutes,
    grace_period_minutes: current.grace_period_minutes,
    max_duration_minutes: current.max_duration_minutes,
    execution_window_start: current.execution_window_start,
    execution_window_end: current.execution_window_end,
    execution_weekdays: executionWeekdays,
  };
  const url = `${normalizeApiUrl(apiUrl)}/api/jobs`;
  let response;
  try {
    response = await fetchImpl(url, {
      method: "POST",
      headers: { accept: "application/json", "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
    });
  } catch (error) {
    throw new Error(`Sentinel indisponível em ${normalizeApiUrl(apiUrl)}: ${error.message}`);
  }
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 500).trim();
    throw new Error(`Sentinel respondeu HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
  }
  return response.json();
}

export async function fetchJobs(apiUrl, { status } = {}, fetchImpl = fetch) {
  const jobs = (await fetchJson(apiUrl, "/api/jobs", fetchImpl)).map(normalizeJob);
  const normalizedStatus = status?.trim?.().toUpperCase();
  return normalizedStatus ? jobs.filter((job) => job.status === normalizedStatus) : jobs;
}

export async function fetchExecutions(apiUrl, { jobId, limit = 20 } = {}, fetchImpl = fetch) {
  const params = new URLSearchParams({ limit: String(Math.max(1, Math.min(Number(limit) || 20, 100))) });
  if (jobId) params.set("job_id", jobId);
  return (await fetchJson(apiUrl, `/api/executions?${params}`, fetchImpl)).map(normalizeExecution);
}

export async function fetchExecutionsPeriod(
  apiUrl,
  { from, to, jobId, limit = 5000 } = {},
  fetchImpl = fetch,
) {
  const params = new URLSearchParams({
    started_from: from,
    started_to: to,
    limit: String(Math.max(1, Math.min(Number(limit) || 5000, 10000))),
  });
  if (jobId) params.set("job_id", jobId);
  return (await fetchJson(apiUrl, `/api/executions/period?${params}`, fetchImpl)).map(normalizeExecution);
}

export async function fetchHealth(apiUrl, fetchImpl = fetch) {
  const startedAt = performance.now();
  const health = await fetchJson(apiUrl, "/api/health", fetchImpl);
  return { ...health, roundTripLatencyMs: Math.round((performance.now() - startedAt) * 100) / 100 };
}

function startOfDay(value = new Date()) {
  const date = new Date(value);
  date.setHours(0, 0, 0, 0);
  return date;
}

function toLocalIso(date) {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().replace("Z", "");
}

export function resolvePeriod({ from, to, days = 7, now = new Date() } = {}) {
  const end = to ? new Date(to) : new Date(now);
  const start = from ? new Date(from) : new Date(end.getTime() - Math.max(1, days) * 86_400_000);
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf()) || start >= end) {
    throw new Error("Período inválido: 'from' deve ser anterior a 'to'.");
  }
  return { from: toLocalIso(start), to: toLocalIso(end) };
}

function comparisonPeriods(kind, now = new Date()) {
  const today = startOfDay(now);
  if (kind === "today_vs_yesterday") {
    const yesterday = new Date(today.getTime() - 86_400_000);
    return {
      current: { label: "hoje", from: toLocalIso(today), to: toLocalIso(now) },
      previous: { label: "ontem", from: toLocalIso(yesterday), to: toLocalIso(today) },
    };
  }
  const sevenDaysAgo = new Date(now.getTime() - 7 * 86_400_000);
  const thirtyDaysAgo = new Date(now.getTime() - 30 * 86_400_000);
  return {
    current: { label: "últimos 7 dias", from: toLocalIso(sevenDaysAgo), to: toLocalIso(now) },
    previous: { label: "últimos 30 dias", from: toLocalIso(thirtyDaysAgo), to: toLocalIso(now) },
  };
}

export async function fetchOperationsSnapshot(apiUrl, fetchImpl = fetch) {
  const period = resolvePeriod({ days: 7 });
  const [jobs, executions] = await Promise.all([
    fetchJobs(apiUrl, {}, fetchImpl),
    fetchExecutionsPeriod(apiUrl, { ...period, limit: 5000 }, fetchImpl),
  ]);
  return {
    generatedAt: new Date().toISOString(),
    summary: summarizeJobs(jobs),
    attentionQueue: buildAttentionQueue(jobs),
    metrics: calculateMetrics(jobs, executions, { ...period, label: "últimos 7 dias" }),
    jobs,
    executions: executions.slice(0, 100),
  };
}

export async function fetchSnapshot(apiUrl, { jobIds, historyLimit = 20 } = {}, fetchImpl = fetch) {
  const [allJobs, allExecutions] = await Promise.all([
    fetchJobs(apiUrl, {}, fetchImpl),
    fetchExecutions(apiUrl, { limit: historyLimit }, fetchImpl),
  ]);
  const selectedIds = new Set((jobIds ?? []).map(String));
  const jobs = selectedIds.size ? allJobs.filter((job) => selectedIds.has(job.jobId)) : allJobs;
  const executions = selectedIds.size
    ? allExecutions.filter((execution) => selectedIds.has(execution.jobId))
    : allExecutions;
  return {
    generatedAt: new Date().toISOString(),
    summary: summarizeJobs(jobs),
    jobs,
    executions,
  };
}

function textResult(text, structuredContent) {
  return {
    content: [{ type: "text", text }],
    structuredContent,
  };
}

function errorResult(error) {
  return {
    isError: true,
    content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }],
  };
}

export function createSentinelMcpServer({
  apiUrl = DEFAULT_API_URL,
  fetchImpl = fetch,
  proactiveMonitor = null,
} = {}) {
  const server = new McpServer(
    { name: "automation-sentinel", version: MCP_VERSION },
    {
      instructions:
        "Consulte dados atuais antes de afirmar a saúde de uma automação. Priorize sentinel_get_attention_queue para triagem, sentinel_diagnose_job para causa e sentinel_get_metrics para tendências. Use sentinel_render_operations quando uma visualização ajudar.",
    },
  );

  registerAppResource(server, "sentinel-status-widget", WIDGET_URI, {}, async () => ({
    contents: [
      {
        uri: WIDGET_URI,
        mimeType: RESOURCE_MIME_TYPE,
        text: widgetHtml,
        _meta: { ui: { prefersBorder: true } },
      },
    ],
  }));

  registerAppResource(server, "sentinel-operations-widget", OPERATIONS_WIDGET_URI, {}, async () => ({
    contents: [
      {
        uri: OPERATIONS_WIDGET_URI,
        mimeType: RESOURCE_MIME_TYPE,
        text: operationsWidgetHtml,
        _meta: { ui: { prefersBorder: true } },
      },
    ],
  }));

  registerAppTool(
    server,
    "sentinel_self_status",
    {
      title: "Verificar saúde do Sentinel",
      description: "Informa versões, uptime, conexão com API e banco, última atualização e latência.",
      inputSchema: {},
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const api = await fetchHealth(apiUrl, fetchImpl);
        const value = {
          mcp: {
            version: MCP_VERSION,
            startedAt: MCP_STARTED_AT.toISOString(),
            uptimeSeconds: Math.max(0, Math.floor((Date.now() - MCP_STARTED_AT.getTime()) / 1000)),
          },
          api,
          proactiveMonitoring: proactiveMonitor?.status?.() ?? { enabled: false },
          checkedAt: new Date().toISOString(),
        };
        return textResult(
          `Sentinel ${api.version}; API ${api.database?.connected ? "e banco conectados" : "com indisponibilidade"}; latência ${api.roundTripLatencyMs} ms.`,
          value,
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_list_jobs",
    {
      title: "Listar automações do Sentinel",
      description: "Lista as automações monitoradas e seus estados atuais, sem alterar dados.",
      inputSchema: {
        status: z.enum(statusValues).optional().describe("Filtra pelo estado atual da automação."),
      },
      outputSchema: { summary: summarySchema, jobs: z.array(jobSchema) },
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ status } = {}) => {
      try {
        const jobs = await fetchJobs(apiUrl, { status }, fetchImpl);
        return textResult(
          `${jobs.length} automação(ões) encontrada(s).`,
          { summary: summarizeJobs(jobs), jobs },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_update_job_schedule",
    {
      title: "Atualizar agendamento de automação",
      description: "Atualiza somente o cron e os dias permitidos de uma automação existente, preservando os demais parâmetros.",
      inputSchema: {
        job_id: z.string().min(1),
        schedule_cron: z.string().min(5).describe("Expressão cron de cinco campos."),
        execution_weekdays: z.array(z.number().int().min(1).max(7)).min(1).default([1, 2, 3, 4, 5, 6, 7]),
      },
      _meta: {},
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ job_id: jobId, schedule_cron: scheduleCron, execution_weekdays: executionWeekdays }) => {
      try {
        const updated = await updateJobSchedule(
          apiUrl,
          { jobId, scheduleCron, executionWeekdays },
          fetchImpl,
        );
        return textResult(
          `Agendamento de ${updated.name ?? jobId} atualizado para '${updated.schedule_cron}'. Próxima execução: ${updated.next_expected_at ?? "não calculada"}.`,
          { job: normalizeJob(updated), scheduleCron: updated.schedule_cron },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_get_executions",
    {
      title: "Consultar execuções do Sentinel",
      description:
        "Consulta o histórico recente, incluindo mensagem e traceback de falhas. Use job_id para restringir o diagnóstico.",
      inputSchema: {
        job_id: z.string().min(1).optional(),
        limit: z.number().int().min(1).max(100).default(20),
      },
      outputSchema: { executions: z.array(executionSchema) },
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ job_id: jobId, limit } = {}) => {
      try {
        const executions = await fetchExecutions(apiUrl, { jobId, limit }, fetchImpl);
        return textResult(
          `${executions.length} execução(ões) encontrada(s)${jobId ? ` para ${jobId}` : ""}.`,
          { executions },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_get_attention_queue",
    {
      title: "Listar fila de atenção do Sentinel",
      description: "Lista somente automações que exigem atenção, ordenadas por criticidade objetiva.",
      inputSchema: {},
      outputSchema: { generatedAt: z.string(), attentionQueue: z.array(attentionItemSchema) },
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const jobs = await fetchJobs(apiUrl, {}, fetchImpl);
        const attentionQueue = buildAttentionQueue(jobs);
        return textResult(
          attentionQueue.length
            ? `${attentionQueue.length} automação(ões) exigem atenção.`
            : "Nenhuma automação exige atenção neste momento.",
          { generatedAt: new Date().toISOString(), attentionQueue },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_diagnose_job",
    {
      title: "Diagnosticar automação do Sentinel",
      description: "Analisa falhas consecutivas, ausências, timeouts e padrões recorrentes de erro de um job.",
      inputSchema: {
        job_id: z.string().min(1),
        history_limit: z.number().int().min(5).max(100).default(30),
      },
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ job_id: jobId, history_limit: historyLimit }) => {
      try {
        const [jobs, executions] = await Promise.all([
          fetchJobs(apiUrl, {}, fetchImpl),
          fetchExecutions(apiUrl, { jobId, limit: historyLimit }, fetchImpl),
        ]);
        const job = jobs.find((candidate) => candidate.jobId === jobId);
        if (!job) return errorResult(new Error(`Automação '${jobId}' não encontrada.`));
        const diagnosis = diagnoseJob(job, executions);
        return textResult(
          `Diagnóstico de ${job.name}: severidade ${diagnosis.severity}, ${diagnosis.findings.join(" ")}`,
          diagnosis,
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_get_metrics",
    {
      title: "Calcular métricas do Sentinel",
      description: "Calcula sucesso, ausência, duração média, p95 e violações de tempo em um período.",
      inputSchema: {
        job_id: z.string().min(1).optional(),
        from: z.string().optional().describe("Data/hora ISO inclusiva."),
        to: z.string().optional().describe("Data/hora ISO exclusiva."),
        days: z.number().int().min(1).max(365).default(7),
      },
      outputSchema: { metrics: metricsSchema },
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ job_id: jobId, from, to, days } = {}) => {
      try {
        const period = { ...resolvePeriod({ from, to, days }), label: from || to ? "período informado" : `últimos ${days ?? 7} dias` };
        const [jobs, executions] = await Promise.all([
          fetchJobs(apiUrl, {}, fetchImpl),
          fetchExecutionsPeriod(apiUrl, { ...period, jobId }, fetchImpl),
        ]);
        const selectedJobs = jobId ? jobs.filter((job) => job.jobId === jobId) : jobs;
        const metrics = calculateMetrics(selectedJobs, executions, period);
        return textResult(
          `${metrics.totalExecutions} execuções; sucesso ${metrics.successRate}%; ausência ${metrics.absenceRate}%; p95 ${metrics.p95DurationSeconds ?? "sem dados"}s.`,
          { metrics },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_compare_periods",
    {
      title: "Comparar períodos do Sentinel",
      description: "Compara hoje com ontem ou os últimos 7 dias com os últimos 30 dias.",
      inputSchema: {
        comparison: z.enum(["today_vs_yesterday", "last_7_vs_last_30"]).default("today_vs_yesterday"),
        job_id: z.string().min(1).optional(),
      },
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ comparison, job_id: jobId } = {}) => {
      try {
        const periods = comparisonPeriods(comparison ?? "today_vs_yesterday");
        const jobs = await fetchJobs(apiUrl, {}, fetchImpl);
        const selectedJobs = jobId ? jobs.filter((job) => job.jobId === jobId) : jobs;
        const [currentExecutions, previousExecutions] = await Promise.all([
          fetchExecutionsPeriod(apiUrl, { ...periods.current, jobId }, fetchImpl),
          fetchExecutionsPeriod(apiUrl, { ...periods.previous, jobId }, fetchImpl),
        ]);
        const result = compareMetrics(
          calculateMetrics(selectedJobs, currentExecutions, periods.current),
          calculateMetrics(selectedJobs, previousExecutions, periods.previous),
        );
        return textResult(
          `Comparação concluída: ${periods.current.label} versus ${periods.previous.label}.`,
          { comparison: comparison ?? "today_vs_yesterday", ...result },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_check_changes",
    {
      title: "Verificar mudanças relevantes no Sentinel",
      description: "Compara a fila de atenção atual com o estado persistido e informa apenas entradas, alterações ou resoluções.",
      inputSchema: {},
      _meta: {},
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        if (!proactiveMonitor) return errorResult(new Error("Monitor proativo não inicializado."));
        const result = await proactiveMonitor.check({ notify: false });
        return textResult(
          result.isBaseline
            ? "Linha de base do monitoramento proativo criada sem emitir alerta."
            : result.changes?.relevant
            ? `Mudança relevante: +${result.changes.added.length}, ~${result.changes.changed.length}, -${result.changes.resolved.length}.`
            : "Nenhuma mudança relevante desde a última verificação.",
          result,
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_render_operations",
    {
      title: "Exibir operações do Sentinel",
      description: "Renderiza painel operacional com fila de atenção, barras, linha do tempo, métricas e erros.",
      inputSchema: {},
      _meta: { ui: { resourceUri: OPERATIONS_WIDGET_URI } },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const snapshot = await fetchOperationsSnapshot(apiUrl, fetchImpl);
        return textResult(
          `Painel operacional: ${snapshot.attentionQueue.length} item(ns) de atenção e ${snapshot.metrics.totalExecutions} execuções em 7 dias.`,
          snapshot,
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  registerAppTool(
    server,
    "sentinel_render_status",
    {
      title: "Exibir painel do Sentinel",
      description: "Renderiza um painel visual somente leitura com status e execuções recentes.",
      inputSchema: {
        job_ids: z.array(z.string().min(1)).max(50).optional(),
        history_limit: z.number().int().min(1).max(100).default(20),
      },
      outputSchema: {
        generatedAt: z.string(),
        summary: summarySchema,
        jobs: z.array(jobSchema),
        executions: z.array(executionSchema),
      },
      _meta: { ui: { resourceUri: WIDGET_URI } },
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ job_ids: jobIds, history_limit: historyLimit } = {}) => {
      try {
        const snapshot = await fetchSnapshot(apiUrl, { jobIds, historyLimit }, fetchImpl);
        return textResult(
          `Painel gerado com ${snapshot.jobs.length} automação(ões) e ${snapshot.executions.length} execução(ões).`,
          snapshot,
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  return server;
}

export async function startMcpHttpServer({
  apiUrl = process.env.SENTINEL_API_URL || DEFAULT_API_URL,
  host = process.env.MCP_HOST || "127.0.0.1",
  port = Number(process.env.MCP_PORT || 8787),
  fetchImpl = fetch,
  proactiveEnabled = String(process.env.MCP_PROACTIVE_ENABLED || "false").toLowerCase() === "true",
  proactiveIntervalSeconds = Number(process.env.MCP_PROACTIVE_INTERVAL_SECONDS || 60),
  proactiveStatePath = process.env.MCP_PROACTIVE_STATE_PATH || resolve(MODULE_DIR, "data", "attention-state.json"),
  webhookUrl = process.env.MCP_ALERT_WEBHOOK_URL || "",
  webhookSecret = process.env.MCP_ALERT_WEBHOOK_SECRET || "",
} = {}) {
  const proactiveMonitor = createProactiveMonitor({
    fetchJobs: () => fetchJobs(apiUrl, {}, fetchImpl),
    statePath: proactiveStatePath,
    intervalSeconds: proactiveIntervalSeconds,
    webhookUrl,
    webhookSecret,
    fetchImpl,
  });
  if (proactiveEnabled) proactiveMonitor.start();

  const httpServer = createHttpServer(async (req, res) => {
    if (!req.url) {
      res.writeHead(400).end("Missing URL");
      return;
    }

    const url = new URL(req.url, `http://${req.headers.host ?? "localhost"}`);
    if (req.method === "OPTIONS" && url.pathname === MCP_PATH) {
      res.writeHead(204, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "content-type, mcp-session-id, mcp-protocol-version",
        "Access-Control-Expose-Headers": "Mcp-Session-Id",
      });
      res.end();
      return;
    }

    if (req.method === "GET" && url.pathname === "/") {
      res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({
        service: "automation-sentinel-mcp",
        version: MCP_VERSION,
        mcp: MCP_PATH,
        proactiveMonitoring: proactiveMonitor.status(),
      }));
      return;
    }

    const mcpMethods = new Set(["POST", "GET", "DELETE"]);
    if (url.pathname === MCP_PATH && req.method && mcpMethods.has(req.method)) {
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");
      const mcpServer = createSentinelMcpServer({ apiUrl, fetchImpl, proactiveMonitor });
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });

      res.on("close", () => {
        transport.close();
        mcpServer.close();
      });

      try {
        await mcpServer.connect(transport);
        await transport.handleRequest(req, res);
      } catch (error) {
        console.error("Erro ao processar requisição MCP:", error);
        if (!res.headersSent) res.writeHead(500).end("Internal server error");
      }
      return;
    }

    res.writeHead(404).end("Not Found");
  });

  await new Promise((resolveListen, rejectListen) => {
    httpServer.once("error", rejectListen);
    httpServer.listen(port, host, resolveListen);
  });
  httpServer.once("close", () => proactiveMonitor.stop());
  httpServer.proactiveMonitor = proactiveMonitor;
  return httpServer;
}

const invokedDirectly = process.argv[1]
  && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;

if (invokedDirectly) {
  const server = await startMcpHttpServer();
  const address = server.address();
  const host = typeof address === "object" && address ? address.address : "127.0.0.1";
  const port = typeof address === "object" && address ? address.port : process.env.MCP_PORT || 8787;
  console.log(`Sentinel MCP App em http://${host}:${port}${MCP_PATH}`);
  console.log(`API Sentinel: ${normalizeApiUrl(process.env.SENTINEL_API_URL || DEFAULT_API_URL)}`);
  console.log(`Monitor proativo: ${server.proactiveMonitor.status().enabled ? "ativo" : "desativado"}`);
}
