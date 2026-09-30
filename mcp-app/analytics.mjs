const ATTENTION_STATUS = new Set(["FAILED", "TIMEOUT", "MISSED"]);
const FAILURE_STATUS = new Set(["FAILED", "TIMEOUT", "MISSED"]);

function asDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

function round(value, digits = 2) {
  if (!Number.isFinite(value)) return 0;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function percentile(values, percentileValue) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const rank = Math.max(1, Math.ceil((percentileValue / 100) * sorted.length));
  return sorted[rank - 1];
}

export function buildAttentionQueue(jobs, now = new Date()) {
  const queue = [];
  for (const job of jobs) {
    const item = {
      jobId: job.jobId,
      name: job.name,
      status: job.status,
      severity: "medium",
      score: 0,
      reason: "",
      since: job.lastPingAt,
      nextExpectedAt: job.nextExpectedAt,
    };

    if (job.status === "TIMEOUT") {
      Object.assign(item, { severity: "critical", score: 100, reason: "Execução excedeu o tempo limite." });
    } else if (job.status === "FAILED") {
      Object.assign(item, { severity: "critical", score: 95, reason: "A última execução terminou com falha." });
    } else if (job.status === "MISSED") {
      Object.assign(item, { severity: "high", score: 90, reason: "A automação não executou no prazo esperado." });
    } else if (job.status === "RUNNING") {
      const startedAt = asDate(job.lastPingAt);
      const limitMs = Number(job.maxDurationMinutes) * 60_000;
      if (startedAt && limitMs > 0 && now - startedAt > limitMs) {
        Object.assign(item, { severity: "high", score: 85, reason: "Execução em andamento acima do limite configurado." });
      }
    } else {
      const expectedAt = asDate(job.nextExpectedAt);
      const graceMs = Math.max(0, Number(job.gracePeriodMinutes) || 0) * 60_000;
      if (expectedAt && now.getTime() > expectedAt.getTime() + graceMs) {
        Object.assign(item, { severity: "high", score: 80, reason: "Próxima execução esperada está atrasada além da tolerância." });
      }
    }

    if (item.score > 0) queue.push(item);
  }
  return queue.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name, "pt-BR"));
}

function normalizeError(message) {
  return String(message ?? "")
    .toLowerCase()
    .replace(/\b[0-9a-f]{8,}\b/gi, "#")
    .replace(/\b\d+\b/g, "#")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 240);
}

export function diagnoseJob(job, executions) {
  const ordered = [...executions].sort((a, b) => b.id - a.id);
  let consecutiveFailures = 0;
  for (const execution of ordered) {
    if (!FAILURE_STATUS.has(execution.status)) break;
    consecutiveFailures += 1;
  }

  const errors = new Map();
  for (const execution of ordered) {
    if (!execution.errorMessage) continue;
    const key = normalizeError(execution.errorMessage);
    const current = errors.get(key) ?? { pattern: key, count: 0, example: execution.errorMessage };
    current.count += 1;
    errors.set(key, current);
  }

  const recurringErrors = [...errors.values()]
    .filter((item) => item.count > 1)
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  const failures = ordered.filter((execution) => execution.status === "FAILED").length;
  const missed = ordered.filter((execution) => execution.status === "MISSED").length;
  const timeouts = ordered.filter((execution) => execution.status === "TIMEOUT").length;
  const successes = ordered.filter((execution) => execution.status === "SUCCESS").length;
  const totalFinished = successes + failures + missed + timeouts;
  const successRate = totalFinished ? round((successes / totalFinished) * 100) : 0;

  let severity = "ok";
  const findings = [];
  if (job.status === "TIMEOUT" || consecutiveFailures >= 3) severity = "critical";
  else if (ATTENTION_STATUS.has(job.status) || consecutiveFailures > 0) severity = "high";
  else if (missed > 0 || recurringErrors.length) severity = "medium";
  if (consecutiveFailures) findings.push(`${consecutiveFailures} falha(s) consecutiva(s).`);
  if (missed) findings.push(`${missed} ausência(s) no histórico analisado.`);
  if (timeouts) findings.push(`${timeouts} violação(ões) explícita(s) de tempo.`);
  if (recurringErrors.length) findings.push(`${recurringErrors.length} padrão(ões) recorrente(s) de erro.`);
  if (!findings.length) findings.push("Nenhuma anomalia objetiva encontrada no histórico analisado.");

  return {
    job,
    analyzedExecutions: ordered.length,
    severity,
    consecutiveFailures,
    failures,
    missed,
    timeouts,
    successes,
    successRate,
    recurringErrors,
    findings,
    latestExecutions: ordered.slice(0, 10),
  };
}

export function calculateMetrics(jobs, executions, period) {
  const jobLimits = new Map(jobs.map((job) => [job.jobId, Number(job.maxDurationMinutes) * 60]));
  const counts = { SUCCESS: 0, FAILED: 0, MISSED: 0, TIMEOUT: 0, RUNNING: 0, PENDING: 0 };
  const durations = [];
  let durationViolations = 0;
  for (const execution of executions) {
    counts[execution.status] = (counts[execution.status] ?? 0) + 1;
    if (Number.isFinite(execution.durationSeconds) && execution.durationSeconds >= 0) {
      durations.push(execution.durationSeconds);
      const limitSeconds = jobLimits.get(execution.jobId);
      if (limitSeconds > 0 && execution.durationSeconds > limitSeconds && execution.status !== "TIMEOUT") {
        durationViolations += 1;
      }
    }
  }
  durationViolations += counts.TIMEOUT;
  const decided = counts.SUCCESS + counts.FAILED + counts.MISSED + counts.TIMEOUT;
  return {
    period,
    totalExecutions: executions.length,
    successCount: counts.SUCCESS,
    failureCount: counts.FAILED + counts.TIMEOUT,
    missedCount: counts.MISSED,
    timeoutCount: counts.TIMEOUT,
    runningCount: counts.RUNNING,
    successRate: decided ? round((counts.SUCCESS / decided) * 100) : 0,
    absenceRate: decided ? round((counts.MISSED / decided) * 100) : 0,
    averageDurationSeconds: durations.length
      ? round(durations.reduce((sum, value) => sum + value, 0) / durations.length)
      : null,
    p95DurationSeconds: percentile(durations, 95),
    durationViolations,
    statusCounts: counts,
  };
}

export function compareMetrics(current, previous) {
  const delta = (field) => round((current[field] ?? 0) - (previous[field] ?? 0));
  return {
    current,
    previous,
    delta: {
      totalExecutions: delta("totalExecutions"),
      successRate: delta("successRate"),
      absenceRate: delta("absenceRate"),
      averageDurationSeconds: delta("averageDurationSeconds"),
      p95DurationSeconds: delta("p95DurationSeconds"),
      durationViolations: delta("durationViolations"),
    },
  };
}

export function attentionFingerprint(queue) {
  return queue
    .map((item) => `${item.jobId}|${item.status}|${item.score}|${item.reason}`)
    .sort()
    .join("\n");
}

export function diffAttention(previousQueue, currentQueue) {
  const previous = new Map(previousQueue.map((item) => [item.jobId, item]));
  const current = new Map(currentQueue.map((item) => [item.jobId, item]));
  const added = [];
  const changed = [];
  const resolved = [];
  for (const [jobId, item] of current) {
    const before = previous.get(jobId);
    if (!before) added.push(item);
    else if (attentionFingerprint([before]) !== attentionFingerprint([item])) changed.push({ before, after: item });
  }
  for (const [jobId, item] of previous) {
    if (!current.has(jobId)) resolved.push(item);
  }
  return { added, changed, resolved, relevant: Boolean(added.length || changed.length || resolved.length) };
}
