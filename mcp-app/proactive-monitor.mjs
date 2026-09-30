import { createHmac } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import { attentionFingerprint, buildAttentionQueue, diffAttention } from "./analytics.mjs";

async function readState(statePath) {
  try {
    return JSON.parse(await readFile(statePath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function writeState(statePath, state) {
  await mkdir(dirname(statePath), { recursive: true });
  const temporaryPath = `${statePath}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  await rename(temporaryPath, statePath);
}

async function deliverWebhook(url, secret, payload, fetchImpl = fetch) {
  const body = JSON.stringify(payload);
  const headers = { "content-type": "application/json" };
  if (secret) {
    headers["x-sentinel-signature"] = `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
  }
  const response = await fetchImpl(url, {
    method: "POST",
    redirect: "error",
    headers,
    body,
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`Webhook respondeu HTTP ${response.status}`);
}

export function createProactiveMonitor({
  fetchJobs,
  statePath,
  intervalSeconds = 60,
  webhookUrl,
  webhookSecret,
  fetchImpl = fetch,
  logger = console,
} = {}) {
  let timer = null;
  let running = false;
  let lastCheckAt = null;
  let lastChangeAt = null;
  let lastError = null;
  let lastQueue = [];

  async function check({ notify = true } = {}) {
    if (running) return { skipped: true, reason: "check_in_progress" };
    running = true;
    try {
      const jobs = await fetchJobs();
      const queue = buildAttentionQueue(jobs);
      const previousState = await readState(statePath);
      const previousQueue = previousState?.queue ?? [];
      const changes = diffAttention(previousQueue, queue);
      const checkedAt = new Date().toISOString();
      const isBaseline = !previousState;
      const state = {
        checkedAt,
        changedAt: changes.relevant && !isBaseline ? checkedAt : previousState?.changedAt ?? null,
        fingerprint: attentionFingerprint(queue),
        queue,
      };
      if (changes.relevant && !isBaseline) {
        lastChangeAt = checkedAt;
        const payload = {
          type: "sentinel.attention.changed",
          timestamp: checkedAt,
          data: { ...changes, current: queue },
        };
        if (notify && webhookUrl) await deliverWebhook(webhookUrl, webhookSecret, payload, fetchImpl);
        logger.info(`[Sentinel MCP] Mudança relevante: +${changes.added.length} ~${changes.changed.length} -${changes.resolved.length}`);
      }
      // Persiste depois da entrega: se o webhook falhar, a mudança continua pendente para nova tentativa.
      await writeState(statePath, state);
      lastCheckAt = checkedAt;
      lastQueue = queue;
      lastError = null;
      return { isBaseline, checkedAt, queue, changes, notified: Boolean(notify && webhookUrl && changes.relevant && !isBaseline) };
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
      logger.error(`[Sentinel MCP] Falha no monitor proativo: ${lastError}`);
      throw error;
    } finally {
      running = false;
    }
  }

  function start() {
    if (timer) return;
    void check().catch(() => {});
    timer = setInterval(() => void check().catch(() => {}), Math.max(15, intervalSeconds) * 1000);
    timer.unref?.();
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  function status() {
    return {
      enabled: Boolean(timer),
      intervalSeconds: Math.max(15, intervalSeconds),
      webhookConfigured: Boolean(webhookUrl),
      lastCheckAt,
      lastChangeAt,
      lastError,
      attentionCount: lastQueue.length,
    };
  }

  return { check, start, stop, status };
}
