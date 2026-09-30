import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, before, test } from "node:test";

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
];

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
  apiServer = createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    res.setHeader("content-type", "application/json");
    if (url.pathname === "/api/jobs") return res.end(JSON.stringify(jobs));
    if (url.pathname === "/api/executions") return res.end(JSON.stringify(executions));
    res.writeHead(404).end(JSON.stringify({ detail: "not found" }));
  });
  await listen(apiServer);
  const apiPort = apiServer.address().port;
  mcpServer = await startMcpHttpServer({ apiUrl: `http://127.0.0.1:${apiPort}`, port: 0 });
  const mcpPort = mcpServer.address().port;
  client = new Client({ name: "sentinel-test", version: "0.1.0" });
  await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${mcpPort}/mcp`)));
});

after(async () => {
  await client?.close();
  await close(mcpServer);
  await close(apiServer);
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
    ["sentinel_get_executions", "sentinel_list_jobs", "sentinel_render_status"],
  );

  const result = await client.callTool({ name: "sentinel_render_status", arguments: { history_limit: 10 } });
  assert.equal(result.isError, undefined);
  assert.equal(result.structuredContent.summary.total, 2);
  assert.equal(result.structuredContent.executions[0].errorMessage, "Falha simulada");
});
