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

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));
const WIDGET_URI = "ui://sentinel/status/v1.html";
const MCP_PATH = "/mcp";
const DEFAULT_API_URL = "http://127.0.0.1:8050";
const DEFAULT_TIMEOUT_MS = 8_000;
const widgetHtml = readFileSync(resolve(MODULE_DIR, "public", "sentinel-widget.html"), "utf8");

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

export function createSentinelMcpServer({ apiUrl = DEFAULT_API_URL, fetchImpl = fetch } = {}) {
  const server = new McpServer(
    { name: "automation-sentinel", version: "0.1.0" },
    {
      instructions:
        "Use as ferramentas de leitura para consultar a saúde das automações. Antes de afirmar que uma rotina está saudável ou com falha, consulte os dados atuais. Use sentinel_render_status quando uma visualização ajudar.",
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
} = {}) {
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
        "Access-Control-Allow-Headers": "content-type, mcp-session-id",
        "Access-Control-Expose-Headers": "Mcp-Session-Id",
      });
      res.end();
      return;
    }

    if (req.method === "GET" && url.pathname === "/") {
      res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ service: "automation-sentinel-mcp", mcp: MCP_PATH }));
      return;
    }

    const mcpMethods = new Set(["POST", "GET", "DELETE"]);
    if (url.pathname === MCP_PATH && req.method && mcpMethods.has(req.method)) {
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");
      const mcpServer = createSentinelMcpServer({ apiUrl, fetchImpl });
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
}
