import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildAttentionQueue,
  calculateMetrics,
  diagnoseJob,
  diffAttention,
  percentile,
} from "../analytics.mjs";

const jobs = [
  { jobId: "ok", name: "OK", status: "SUCCESS", maxDurationMinutes: 1, gracePeriodMinutes: 5 },
  { jobId: "fail", name: "Falha", status: "FAILED", maxDurationMinutes: 1, gracePeriodMinutes: 5 },
  { jobId: "missed", name: "Ausente", status: "MISSED", maxDurationMinutes: 1, gracePeriodMinutes: 5 },
];

const executions = [
  { id: 4, jobId: "fail", status: "FAILED", durationSeconds: 80, errorMessage: "HTTP 500 no lote 22" },
  { id: 3, jobId: "fail", status: "FAILED", durationSeconds: 70, errorMessage: "HTTP 500 no lote 31" },
  { id: 2, jobId: "ok", status: "SUCCESS", durationSeconds: 10, errorMessage: null },
  { id: 1, jobId: "missed", status: "MISSED", durationSeconds: 0, errorMessage: "Prazo estourado" },
];

test("ordena a fila por criticidade objetiva", () => {
  const queue = buildAttentionQueue(jobs);
  assert.deepEqual(queue.map((item) => item.jobId), ["fail", "missed"]);
  assert.equal(queue[0].severity, "critical");
});

test("calcula métricas, p95 e violações", () => {
  const metrics = calculateMetrics(jobs, executions, { from: "a", to: "b" });
  assert.equal(metrics.totalExecutions, 4);
  assert.equal(metrics.successRate, 25);
  assert.equal(metrics.missedCount, 1);
  assert.equal(metrics.durationViolations, 2);
  assert.equal(metrics.p95DurationSeconds, 80);
  assert.equal(percentile([10, 20, 30], 95), 30);
});

test("diagnóstico identifica falhas consecutivas e erro recorrente normalizado", () => {
  const diagnosis = diagnoseJob(jobs[1], executions.filter((item) => item.jobId === "fail"));
  assert.equal(diagnosis.consecutiveFailures, 2);
  assert.equal(diagnosis.recurringErrors[0].count, 2);
  assert.equal(diagnosis.severity, "high");
});

test("detector informa entradas e resoluções sem ruído", () => {
  const previous = buildAttentionQueue([jobs[1]]);
  const current = buildAttentionQueue([jobs[2]]);
  const changes = diffAttention(previous, current);
  assert.equal(changes.added[0].jobId, "missed");
  assert.equal(changes.resolved[0].jobId, "fail");
  assert.equal(changes.relevant, true);
  assert.equal(diffAttention(current, current).relevant, false);
});
