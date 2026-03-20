import type { FixJob, FixJobLogEvent, FixJobStep, FixRunner } from "../../types";
import { runnerLabel } from "../../lib/runners";

export interface ChatRow {
  id: string;
  role: "assistant" | "tool" | "error" | "status";
  text: string;
  timestamp: string;
  mergeKey?: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function asString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  return value.length > 0 ? value : null;
}

function readPath(record: Record<string, unknown>, path: string): unknown {
  const keys = path.split(".");
  let cursor: unknown = record;
  for (const key of keys) {
    const next = asRecord(cursor);
    if (!next || !(key in next)) {
      return undefined;
    }
    cursor = next[key];
  }
  return cursor;
}

function parseLineAsJsonRecord(line: string): Record<string, unknown> | null {
  const trimmed = line.trim();
  if (!trimmed || !trimmed.startsWith("{")) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    return asRecord(parsed);
  } catch {
    return null;
  }
}

function collectText(value: unknown, depth = 0): string[] {
  if (value === null || value === undefined || depth > 4) {
    return [];
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => collectText(item, depth + 1));
  }

  if (typeof value === "object") {
    const record = asRecord(value);
    if (!record) {
      return [];
    }

    const priorityKeys = [
      "text",
      "content",
      "message",
      "output_text",
      "delta",
      "summary",
      "result",
      "error",
    ];
    for (const key of priorityKeys) {
      if (key in record) {
        const found = collectText(record[key], depth + 1);
        if (found.length > 0) {
          return found;
        }
      }
    }

    const ignored = new Set([
      "type",
      "id",
      "sessionID",
      "sessionId",
      "messageID",
      "messageId",
      "timestamp",
      "time",
      "tokens",
      "cost",
      "snapshot",
      "reason",
    ]);
    const fallback: string[] = [];
    for (const [key, child] of Object.entries(record)) {
      if (ignored.has(key)) {
        continue;
      }
      fallback.push(...collectText(child, depth + 1));
    }
    return fallback;
  }

  return [];
}

function joinCollectedText(value: unknown): string | null {
  const lines = collectText(value);
  if (lines.length === 0) {
    return null;
  }
  const joined = lines.join("\n").trim();
  return joined || null;
}

function truncateRowText(text: string, limit = 1800): string {
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit)}\n...`;
}

function normalizeCodexLogEntry(
  parsed: Record<string, unknown>,
  log: FixJobLogEvent,
  index: number,
): ChatRow | null {
  const eventType = (asString(parsed.type) || asString(parsed.event) || "")
    .toLowerCase()
    .trim();
  if (!eventType) {
    return null;
  }

  if (eventType === "thread.started") {
    return {
      id: `status-${index}`,
      role: "status",
      text: "Session started",
      timestamp: log.timestamp,
    };
  }
  if (eventType === "turn.started") {
    return {
      id: `status-${index}`,
      role: "status",
      text: "Turn started",
      timestamp: log.timestamp,
    };
  }
  if (eventType === "turn.completed") {
    return {
      id: `status-${index}`,
      role: "status",
      text: "Turn completed",
      timestamp: log.timestamp,
    };
  }

  if (!eventType.startsWith("item.")) {
    return null;
  }

  const item = asRecord(parsed.item);
  if (!item) {
    return null;
  }

  const itemType = (asString(item.type) || "").toLowerCase().trim();
  const itemId = asString(item.id) || `${index}`;
  const phase = eventType.slice("item.".length);
  const isStarted = phase === "started";
  const isCompleted = phase === "completed";

  if (itemType === "agent_message") {
    const assistantText =
      asString(item.text) ||
      asString(readPath(item, "message")) ||
      asString(readPath(item, "output_text")) ||
      joinCollectedText(item.content) ||
      joinCollectedText(item.result);

    if (!assistantText) {
      if (!isStarted) {
        return null;
      }
      return {
        id: `status-${index}`,
        role: "status",
        text: "Assistant started responding",
        timestamp: log.timestamp,
      };
    }

    return {
      id: `assistant-${index}`,
      role: "assistant",
      text: truncateRowText(assistantText),
      timestamp: log.timestamp,
      mergeKey: `assistant:${itemId}`,
    };
  }

  if (itemType === "mcp_tool_call") {
    const serverName = asString(item.server);
    const toolName = asString(item.tool) || asString(item.name);
    const qualifiedName = [serverName, toolName].filter(Boolean).join(".") || "MCP tool";
    const errorText = asString(item.error);

    if (isStarted) {
      return {
        id: `tool-${index}`,
        role: "tool",
        text: `Calling \`${qualifiedName}\``,
        timestamp: log.timestamp,
      };
    }

    if (errorText) {
      return {
        id: `error-${index}`,
        role: "error",
        text: `Tool \`${qualifiedName}\` failed\n${truncateRowText(errorText)}`,
        timestamp: log.timestamp,
      };
    }

    return null;
  }

  if (itemType === "command_execution") {
    const command = asString(item.command) || "<command>";
    const exitCode =
      typeof item.exit_code === "number" && Number.isFinite(item.exit_code)
        ? item.exit_code
        : null;
    const outputText =
      asString(item.aggregated_output) ||
      joinCollectedText(readPath(item, "output")) ||
      joinCollectedText(readPath(item, "result"));

    if (isStarted) {
      return {
        id: `tool-${index}`,
        role: "tool",
        text: `Running command\n\`${command}\``,
        timestamp: log.timestamp,
      };
    }

    const statusText = isCompleted
      ? `Command completed (exit ${exitCode ?? "?"})\n\`${command}\``
      : `Command update\n\`${command}\``;

    return {
      id: `tool-${index}`,
      role: "tool",
      text: outputText ? `${statusText}\n${truncateRowText(outputText)}` : statusText,
      timestamp: log.timestamp,
    };
  }

  if (itemType === "reasoning") {
    return null;
  }

  const genericAssistantText =
    asString(item.text) ||
    asString(readPath(item, "message")) ||
    asString(readPath(item, "output_text")) ||
    joinCollectedText(item.content) ||
    joinCollectedText(item.result);

  if (genericAssistantText && !itemType.includes("tool")) {
    return {
      id: `assistant-${index}`,
      role: "assistant",
      text: truncateRowText(genericAssistantText),
      timestamp: log.timestamp,
      mergeKey: `assistant:${itemId}`,
    };
  }

  if (itemType.includes("tool") || itemType.includes("function")) {
    const name =
      asString(item.name) ||
      asString(readPath(item, "tool")) ||
      asString(readPath(item, "function.name")) ||
      itemType;
    return {
      id: `tool-${index}`,
      role: "tool",
      text: `${isStarted ? "Using" : "Used"} tool \`${name}\``,
      timestamp: log.timestamp,
    };
  }

  return null;
}

function extractAssistantText(
  parsed: Record<string, unknown>,
  part: Record<string, unknown>,
): string | null {
  const candidates = [
    readPath(part, "text"),
    readPath(part, "content"),
    readPath(part, "delta"),
    readPath(part, "message"),
    readPath(parsed, "text"),
    readPath(parsed, "content"),
    readPath(parsed, "message"),
    readPath(parsed, "output_text"),
  ];

  for (const candidate of candidates) {
    const lines = collectText(candidate);
    if (lines.length > 0) {
      return lines.join("\n").trim();
    }
  }
  return null;
}

function extractToolName(
  parsed: Record<string, unknown>,
  part: Record<string, unknown>,
): string | null {
  const candidates: unknown[] = [
    readPath(parsed, "part.tool_name"),
    readPath(parsed, "part.toolName"),
    readPath(parsed, "part.tool"),
    readPath(parsed, "part.tool.name"),
    readPath(parsed, "part.function.name"),
    readPath(parsed, "part.call.name"),
    readPath(parsed, "part.toolCall.name"),
    readPath(parsed, "tool_name"),
    readPath(parsed, "toolName"),
    readPath(parsed, "tool"),
    readPath(parsed, "tool.name"),
    readPath(part, "name"),
  ];

  const banned = new Set([
    "tool_use",
    "tool-use",
    "tool_result",
    "tool-result",
    "function_call",
    "function-call",
  ]);

  for (const candidate of candidates) {
    if (typeof candidate === "string") {
      const trimmed = candidate.trim();
      if (trimmed && !banned.has(trimmed.toLowerCase())) {
        return trimmed;
      }
      continue;
    }

    const record = asRecord(candidate);
    if (!record) {
      continue;
    }

    const byName = asString(record.name) || asString(record.id);
    if (byName && !banned.has(byName.toLowerCase())) {
      return byName;
    }
  }

  return null;
}

export function formatClock(isoLike: string): string {
  const parsed = Date.parse(isoLike);
  if (Number.isNaN(parsed)) {
    return "--:--:--";
  }
  return new Date(parsed).toLocaleTimeString();
}

export function fallbackLogs(job: FixJob, step: FixJobStep): FixJobLogEvent[] {
  const baseTimestamp = step.started_at || job.started_at || job.created_at;
  const rows: FixJobLogEvent[] = [];

  const stdoutLines = step.stdout ? step.stdout.split(/\r?\n/) : [];
  for (const line of stdoutLines.slice(-5000)) {
    if (!line.trim()) {
      continue;
    }
    rows.push({
      type: "fix_job_log",
      job_id: job.id,
      step_index: step.index,
      annotation_id: step.annotation_id,
      stream: "stdout",
      chunk: `${line}\n`,
      timestamp: baseTimestamp,
      parsed: parseLineAsJsonRecord(line),
    });
  }

  const stderrLines = step.stderr ? step.stderr.split(/\r?\n/) : [];
  for (const line of stderrLines.slice(-3000)) {
    if (!line.trim()) {
      continue;
    }
    rows.push({
      type: "fix_job_log",
      job_id: job.id,
      step_index: step.index,
      annotation_id: step.annotation_id,
      stream: "stderr",
      chunk: `${line}\n`,
      timestamp: baseTimestamp,
      parsed: null,
    });
  }

  return rows;
}

function normalizeOpenCodeLogEntry(
  parsed: Record<string, unknown>,
  log: FixJobLogEvent,
  index: number,
): ChatRow | null {
  const part = asRecord(parsed.part) || parsed;
  const eventTypeRaw =
    asString(parsed.type) || asString(parsed.event) || asString(part.type) || "event";
  const eventType = eventTypeRaw.toLowerCase().replaceAll("_", "-");

  const messageId =
    asString(part.messageID) ||
    asString(part.messageId) ||
    asString(parsed.messageID) ||
    asString(parsed.messageId);

  if (eventType.includes("error") || eventType.includes("fail")) {
    const errorText =
      asString(parsed.error) || asString(parsed.message) || joinCollectedText(parsed);
    return {
      id: `error-${index}`,
      role: "error",
      text: truncateRowText(errorText || `OpenCode error (${eventTypeRaw})`),
      timestamp: log.timestamp,
    };
  }

  if (eventType.includes("tool")) {
    const toolName = extractToolName(parsed, part);
    const assistantText = extractAssistantText(parsed, part);
    const base = toolName ? `Using tool \`${toolName}\`` : "Using tool";
    const extra = assistantText && assistantText !== toolName ? assistantText : null;
    return {
      id: `tool-${index}`,
      role: "tool",
      text: extra ? `${base}\n${truncateRowText(extra)}` : base,
      timestamp: log.timestamp,
    };
  }

  if (eventType.includes("thinking") || eventType.includes("reasoning")) {
    return null;
  }

  const assistantText = extractAssistantText(parsed, part);
  if (assistantText) {
    return {
      id: `assistant-${index}`,
      role: "assistant",
      text: truncateRowText(assistantText),
      timestamp: log.timestamp,
      mergeKey: messageId ? `assistant:${messageId}` : undefined,
    };
  }

  if (eventType === "step-start") {
    return {
      id: `status-${index}`,
      role: "status",
      text: "Step started",
      timestamp: log.timestamp,
    };
  }

  if (eventType === "step-finish") {
    return {
      id: `status-${index}`,
      role: "status",
      text: "Step finished",
      timestamp: log.timestamp,
    };
  }

  return null;
}

function normalizeClaudeLogEntry(
  parsed: Record<string, unknown>,
  log: FixJobLogEvent,
  index: number,
): ChatRow | null {
  const rootType = (asString(parsed.type) || "").toLowerCase().replaceAll("_", "-");

  if (rootType === "system") {
    const subtype = (asString(parsed.subtype) || "").toLowerCase().replaceAll("_", "-");
    if (subtype === "init" || subtype === "start") {
      return {
        id: `status-${index}`,
        role: "status",
        text: "Session started",
        timestamp: log.timestamp,
      };
    }
    if (subtype) {
      return {
        id: `status-${index}`,
        role: "status",
        text: `System: ${subtype.replaceAll("-", " ")}`,
        timestamp: log.timestamp,
      };
    }
    return null;
  }

  if (rootType === "stream-event") {
    const event = asRecord(parsed.event);
    if (!event) {
      return null;
    }

    const eventTypeRaw = asString(event.type) || "event";
    const eventType = eventTypeRaw.toLowerCase().replaceAll("_", "-");
    const contentBlock = asRecord(event.content_block);
    const delta = asRecord(event.delta);
    const blockType = (asString(contentBlock?.type) || "").toLowerCase().replaceAll("_", "-");
    const deltaType = (asString(delta?.type) || "").toLowerCase().replaceAll("_", "-");

    const sessionId = asString(parsed.session_id) || asString(parsed.sessionId) || "session";
    const parentToolUseId =
      asString(parsed.parent_tool_use_id) || asString(parsed.parentToolUseId) || "root";
    const blockIndex =
      typeof event.index === "number" && Number.isFinite(event.index) ? String(event.index) : "0";

    if (eventType.includes("error") || eventType.includes("fail")) {
      const errorText =
        asString(readPath(event, "error.message")) ||
        asString(readPath(event, "error")) ||
        joinCollectedText(event);
      return {
        id: `error-${index}`,
        role: "error",
        text: truncateRowText(errorText || `Claude event: ${eventTypeRaw}`),
        timestamp: log.timestamp,
      };
    }

    if (eventType === "content-block-start") {
      if (blockType === "tool-use") {
        const toolName = asString(contentBlock?.name) || "tool";
        return {
          id: `tool-${index}`,
          role: "tool",
          text: `Calling \`${toolName}\``,
          timestamp: log.timestamp,
        };
      }

      if (blockType === "thinking") {
        return null;
      }

      return null;
    }

    if (eventType === "content-block-delta") {
      if (deltaType === "input-json-delta") {
        return null;
      }

      if (deltaType === "thinking-delta") {
        return null;
      }

      if (deltaType === "text-delta") {
        const text = asNonEmptyString(delta?.text);
        if (!text) {
          return null;
        }
        return {
          id: `assistant-${index}`,
          role: "assistant",
          text: truncateRowText(text),
          timestamp: log.timestamp,
          mergeKey: `assistant:claude:${sessionId}:${parentToolUseId}:${blockIndex}`,
        };
      }

      return null;
    }

    if (
      eventType === "content-block-stop" ||
      eventType === "message-start" ||
      eventType === "message-delta" ||
      eventType === "message-stop"
    ) {
      return null;
    }

    return {
      id: `status-${index}`,
      role: "status",
      text: `Claude event: ${eventTypeRaw}`,
      timestamp: log.timestamp,
    };
  }

  if (rootType === "assistant") {
    const message = asRecord(parsed.message);
    if (!message) {
      return null;
    }

    const messageId =
      asString(readPath(parsed, "message.id")) ||
      asString(parsed.messageID) ||
      asString(parsed.messageId) ||
      asString(parsed.message_id);

    const content = Array.isArray(message.content) ? message.content : [];
    const textParts: string[] = [];
    for (const blockValue of content) {
      const block = asRecord(blockValue);
      if (!block) {
        continue;
      }
      const blockType = (asString(block.type) || "").toLowerCase().replaceAll("_", "-");
      if (blockType !== "text") {
        continue;
      }
      const text = asNonEmptyString(block.text) || joinCollectedText(block);
      if (text) {
        textParts.push(text);
      }
    }

    if (textParts.length === 0) {
      return null;
    }

    return {
      id: `assistant-${index}`,
      role: "assistant",
      text: truncateRowText(textParts.join("")),
      timestamp: log.timestamp,
      mergeKey: messageId ? `assistant:claude:message:${messageId}` : undefined,
    };
  }

  if (rootType === "user") {
    const message = asRecord(parsed.message);
    const firstContent =
      message && Array.isArray(message.content) ? asRecord(message.content[0]) : null;
    const isToolError =
      firstContent?.type === "tool_result" &&
      (firstContent.is_error === true || asString(readPath(parsed, "tool_use_result.stderr")));

    if (isToolError) {
      const errorText =
        asString(readPath(parsed, "tool_use_result.stderr")) ||
        asString(firstContent?.content) ||
        "Tool execution failed";
      return {
        id: `error-${index}`,
        role: "error",
        text: truncateRowText(errorText),
        timestamp: log.timestamp,
      };
    }

    return null;
  }

  if (rootType === "result") {
    if (parsed.is_error === true) {
      const errorText =
        asString(parsed.result) ||
        asString(parsed.error) ||
        (parsed.result != null ? JSON.stringify(parsed.result) : null) ||
        "Claude result reported an error";
      return {
        id: `error-${index}`,
        role: "error",
        text: truncateRowText(errorText),
        timestamp: log.timestamp,
      };
    }
    return null;
  }

  const message = asRecord(parsed.message);
  const contentBlock = asRecord(parsed.content_block);
  const part = asRecord(parsed.part) || contentBlock || message || parsed;
  const eventTypeRaw =
    asString(parsed.type) || asString(parsed.event) || asString(part.type) || "event";
  const eventType = eventTypeRaw.toLowerCase().replaceAll("_", "-");
  const partType = (asString(part.type) || "").toLowerCase().replaceAll("_", "-");

  if (eventType.includes("tool") || partType.includes("tool")) {
    const toolName =
      extractToolName(parsed, part) ||
      asString(readPath(parsed, "name")) ||
      asString(readPath(parsed, "content_block.name")) ||
      "tool";
    return {
      id: `tool-${index}`,
      role: "tool",
      text: `Calling \`${toolName}\``,
      timestamp: log.timestamp,
    };
  }

  const assistantText =
    asString(readPath(parsed, "delta.text")) ||
    asString(readPath(parsed, "content_block.text")) ||
    asString(readPath(parsed, "text")) ||
    joinCollectedText(readPath(parsed, "message.content")) ||
    extractAssistantText(parsed, part);
  if (assistantText) {
    return {
      id: `assistant-${index}`,
      role: "assistant",
      text: truncateRowText(assistantText),
      timestamp: log.timestamp,
    };
  }

  return null;
}

function normalizeUnknownParsedLogEntry(
  runner: FixRunner,
  parsed: Record<string, unknown>,
  log: FixJobLogEvent,
  index: number,
): ChatRow {
  const part = asRecord(parsed.part) || parsed;
  const claudeEventType = runner === "claude" ? asString(readPath(parsed, "event.type")) : null;
  const eventTypeRaw =
    claudeEventType || asString(parsed.type) || asString(parsed.event) || asString(part.type) || "event";
  const detail =
    asString(readPath(parsed, "event.error.message")) ||
    asString(readPath(parsed, "event.delta.text")) ||
    asString(parsed.message) ||
    asString(parsed.error) ||
    joinCollectedText(readPath(parsed, "result"));

  const isError = eventTypeRaw.toLowerCase().includes("error");
  if (detail) {
    return {
      id: `${isError ? "error" : "status"}-${index}`,
      role: isError ? "error" : "status",
      text: `${runnerLabel(runner)} event: ${eventTypeRaw}\n${truncateRowText(detail, 320)}`,
      timestamp: log.timestamp,
    };
  }

  return {
    id: `status-${index}`,
    role: "status",
    text: `${runnerLabel(runner)} event: ${eventTypeRaw}`,
    timestamp: log.timestamp,
  };
}

function normalizeRawStdoutChunk(
  runner: FixRunner,
  text: string,
  log: FixJobLogEvent,
  index: number,
): ChatRow | null {
  const trimmed = text.trim();
  if (!trimmed) {
    return null;
  }
  return {
    id: `raw-${index}`,
    role: "assistant",
    text: truncateRowText(trimmed),
    timestamp: log.timestamp,
    mergeKey: `raw:${runner}:${index}`,
  };
}

function shouldSuppressClaudeFallback(parsed: Record<string, unknown>): boolean {
  const rootType = (asString(parsed.type) || "").toLowerCase().replaceAll("_", "-");
  if (rootType === "assistant" || rootType === "user" || rootType === "result") {
    return true;
  }
  if (rootType === "rate-limit-event") {
    return true;
  }
  if (rootType !== "stream-event") {
    return false;
  }

  const eventType =
    (asString(readPath(parsed, "event.type")) || "").toLowerCase().replaceAll("_", "-");
  if (
    eventType === "message-start" ||
    eventType === "message-delta" ||
    eventType === "message-stop" ||
    eventType === "content-block-start" ||
    eventType === "content-block-delta" ||
    eventType === "content-block-stop"
  ) {
    return true;
  }

  return false;
}

function normalizeLogEntry(
  runner: FixRunner,
  log: FixJobLogEvent,
  index: number,
): ChatRow | null {
  const trimmedChunk = log.chunk.trim();
  if (log.stream === "stderr") {
    if (!trimmedChunk) {
      return null;
    }
    return {
      id: `err-${index}`,
      role: "error",
      text: trimmedChunk,
      timestamp: log.timestamp,
    };
  }

  const parsed = log.parsed || parseLineAsJsonRecord(log.chunk);
  if (!parsed) {
    return normalizeRawStdoutChunk(runner, trimmedChunk, log, index);
  }

  if (runner === "codex") {
    const codexRow = normalizeCodexLogEntry(parsed, log, index);
    if (codexRow) {
      return codexRow;
    }

    const codexEventType =
      (asString(parsed.type) || asString(parsed.event) || "").toLowerCase().trim();
    if (codexEventType.startsWith("item.")) {
      const item = asRecord(parsed.item);
      const itemType = (asString(item?.type) || "").toLowerCase().trim();
      const phase = codexEventType.slice("item.".length);
      const hasError = !!asString(item?.error);

      if (itemType === "mcp_tool_call" && phase === "completed" && !hasError) {
        return null;
      }
    }
  } else if (runner === "claude") {
    const claudeRow = normalizeClaudeLogEntry(parsed, log, index);
    if (claudeRow) {
      return claudeRow;
    }
    if (shouldSuppressClaudeFallback(parsed)) {
      return null;
    }
  } else {
    const openCodeRow = normalizeOpenCodeLogEntry(parsed, log, index);
    if (openCodeRow) {
      return openCodeRow;
    }
  }

  return normalizeUnknownParsedLogEntry(runner, parsed, log, index);
}

function joinStreamingText(previous: string, incoming: string): string {
  if (!incoming) {
    return previous;
  }
  if (!previous) {
    return incoming;
  }
  if (previous.endsWith(incoming)) {
    return previous;
  }
  if (incoming.startsWith(previous)) {
    return incoming;
  }
  return `${previous}\n${incoming}`;
}

export function buildChatRows(runner: FixRunner, sourceLogs: FixJobLogEvent[]): ChatRow[] {
  const items: ChatRow[] = [];
  const mergeRowIndex = new Map<string, number>();

  sourceLogs.forEach((log, index) => {
    const normalized = normalizeLogEntry(runner, log, index);
    if (!normalized) {
      return;
    }

    if (normalized.role === "assistant" && normalized.mergeKey) {
      const existingIndex = mergeRowIndex.get(normalized.mergeKey);
      if (existingIndex !== undefined && existingIndex === items.length - 1) {
        const existing = items[existingIndex];
        if (normalized.mergeKey.startsWith("assistant:claude:")) {
          existing.text = `${existing.text}${normalized.text}`;
        } else {
          existing.text = joinStreamingText(existing.text, normalized.text);
        }
        existing.timestamp = normalized.timestamp;
        return;
      }
      mergeRowIndex.set(normalized.mergeKey, items.length);
    }

    if (
      items.length > 0 &&
      normalized.role === "status" &&
      items[items.length - 1].role === "status" &&
      items[items.length - 1].text === normalized.text
    ) {
      return;
    }

    if (
      items.length > 0 &&
      normalized.role === "assistant" &&
      items[items.length - 1].role === "assistant" &&
      items[items.length - 1].text.trim() === normalized.text.trim()
    ) {
      items[items.length - 1].timestamp = normalized.timestamp;
      return;
    }

    items.push(normalized);
  });

  return items;
}
