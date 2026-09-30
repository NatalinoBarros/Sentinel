import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, before, test } from "node:test";
import { unlink } from "node:fs/promises";
import { resolve } from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { normalizeJob, startMcpHttpServer, summarizeJobs } from "../server.mjs";

let apiServer;
let mcpServer;
let client;

const jobs = [
  {
    job_id: "job_ok",
    name: "Job OK",
    language: "python",
    last_status: "SUCCESS",
    last_ping_at: "2026-09-29T09:00:00",
    next_expected_at: "2026-09-29T09:30:00",
    expected_interval_minutes: 30,
    grace_period_minutes: 15,
    max_duration_minutes: 20,
    execution_window_start: "07:00",
    execution_window_end: "18:00",
    execution_weekdays: "1,2,3,4,5",
  },
  { job_id: "job_fail", name: "Job Falha", last_status: "FAILED" },
];

const executions = [
  {
    id: 10,
    job_id: "job_fail",
    status: "FAILED",
    started_at: "2026-09-29T08:00:00",
    finished_at: "2026-09-29T08:00:02",
    duration_seconds: 2,
    error_message: "Falha simulada",
    traceback: "Traceback simulado",
  },
  {
    id: 9,
    job_id: "job_ok",
    status: "SUCCESS",
    started_at: "2026-09-29T07:30:00",
    finished_at: "2026-09-29T07:30:10",
    duration_seconds: 10,
  },
];

const statePath = resolve("test", ".attention-state-test.json");

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
}

function close(server) {
  return server ? new Promise((resolve) => server.close(resolve)) : Promise.resolve();
}

before(async () => {
  apiServer = createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    res.setHeader("content-type", "application/json");
    if (url.pathname === "/api/jobs" && req.method === "POST") {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const current = jobs.find((job) => job.job_id === payload.job_id);
      if (!current) return res.writeHead(404).end(JSON.stringify({ detail: "not found" }));
      Object.assign(current, payload, { next_expected_at: "2026-10-02T10:00:00" });
      return res.end(JSON.stringify(current));
    }
    if (url.pathname === "/api/jobs") return res.end(JSON.stringify(jobs));
    if (url.pathname === "/api/health") return res.end(JSON.stringify({
      service: "automation-sentinel",
      version: "1.1.0",
      uptime_seconds: 120,
      database: { connected: true, jobs_count: 2, executions_count: 2, last_updated_at: "2026-09-29T09:00:00" },
      checked_at: "2026-09-29T09:01:00",
    }));
    if (url.pathname === "/api/executions/period") return res.end(JSON.stringify(executions));
    if (url.pathname === "/api/executions") return res.end(JSON.stringify(executions));
    res.writeHead(404).end(JSON.stringify({ detail: "not found" }));
  });
  await listen(apiServer);
  const apiPort = apiServer.address().port;
  mcpServer = await startMcpHttpServer({
    apiUrl: `http://127.0.0.1:${apiPort}`,
    port: 0,
    proactiveStatePath: statePath,
  });
  const mcpPort = mcpServer.address().port;
  client = new Client({ name: "sentinel-test", version: "0.1.0" });
  await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${mcpPort}/mcp`)));
});

after(async () => {
  await client?.close();
  await close(mcpServer);
  await close(apiServer);
  await unlink(statePath).catch(() => {});
});

test("normaliza os dados do banco para o contrato MCP", () => {
  const job = normalizeJob(jobs[0]);
  assert.equal(job.jobId, "job_ok");
  assert.equal(job.status, "SUCCESS");
  assert.equal(job.expectedIntervalMinutes, 30);
});

test("resume estados críticos e saudáveis", () => {
  assert.deepEqual(summarizeJobs(jobs.map(normalizeJob)), {
    total: 2,
    healthy: 1,
    running: 0,
    failed: 1,
    missed: 0,
    pending: 0,
  });
});

test("expõe ferramentas MCP e retorna dados estruturados", async () => {
  const { tools } = await client.listTools();
  assert.deepEqual(
    tools.map((tool) => tool.name).sort(),
    [
      "sentinel_check_changes",
      "sentinel_compare_periods",
      "sentinel_diagnose_job",
      "sentinel_get_attention_queue",
      "sentinel_get_executions",
      "sentinel_get_metrics",
      "sentinel_list_jobs",
      "sentinel_render_operations",
      "sentinel_render_status",
      "sentinel_self_status",
      "sentinel_update_job_schedule",
    ],
  );

  const result = await client.callTool({ name: "sentinel_render_status", arguments: { history_limit: 10 } });
  assert.equal(result.isError, undefined);
  assert.equal(result.structuredContent.summary.total, 2);
  assert.equal(result.structuredContent.executions[0].errorMessage, "Falha simulada");
});

test("atualiza agendamento via MCP preservando o job", async () => {
  const result = await client.callTool({
    name: "sentinel_update_job_schedule",
    arguments: { job_id: "job_ok", schedule_cron: "0 10 2 * *", execution_weekdays: [1, 2, 3, 4, 5, 6, 7] },
  });
  assert.equal(result.isError, undefined);
  assert.equal(result.structuredContent.scheduleCron, "0 10 2 * *");
  assert.equal(result.structuredContent.job.nextExpectedAt, "2026-10-02T10:00:00");
  Object.assign(jobs[0], {
    schedule_cron: null,
    next_expected_at: "2026-09-29T09:30:00",
    execution_weekdays: "1,2,3,4,5",
  });
});

test("retorna saúde, fila de atenção, diagnóstico e métricas", async () => {
  const selfStatus = await client.callTool({ name: "sentinel_self_status", arguments: {} });
  assert.equal(selfStatus.structuredContent.api.database.connected, true);

  const queue = await client.callTool({ name: "sentinel_get_attention_queue", arguments: {} });
  assert.equal(queue.structuredContent.attentionQueue[0].jobId, "job_fail");

  const diagnosis = await client.callTool({
    name: "sentinel_diagnose_job",
    arguments: { job_id: "job_fail", history_limit: 20 },
  });
  assert.equal(diagnosis.structuredContent.failures, 1);

  const metrics = await client.callTool({ name: "sentinel_get_metrics", arguments: { days: 7 } });
  assert.equal(metrics.structuredContent.metrics.totalExecutions, 2);
  assert.equal(metrics.structuredContent.metrics.successRate, 50);
});

test("renderiza operações e persiste baseline proativo sem alerta falso", async () => {
  const panel = await client.callTool({ name: "sentinel_render_operations", arguments: {} });
  assert.equal(panel.structuredContent.attentionQueue.length, 2);
  assert.equal(panel.structuredContent.attentionQueue[0].jobId, "job_fail");
  assert.equal(panel.structuredContent.metrics.totalExecutions, 2);

  const changes = await client.callTool({ name: "sentinel_check_changes", arguments: {} });
  assert.equal(changes.structuredContent.isBaseline, true);
  assert.equal(changes.structuredContent.changes.relevant, true);
  assert.equal(changes.structuredContent.notified, false);
});
