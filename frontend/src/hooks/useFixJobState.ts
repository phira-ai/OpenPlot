import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelFixJob as cancelFixJobRequest,
  fetchCurrentFixJob,
  startFixJob as startFixJobRequest,
} from "../api/fixJobs";
import type { FixJob, FixJobLogEvent, FixJobStatus, FixRunner, FixStepStatus } from "../types";

const MAX_FIX_STEP_LOG_EVENTS = 8000;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function normalizeEventType(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().toLowerCase().replaceAll("-", "_");
}

export function shouldStoreFixLogEvent(event: FixJobLogEvent): boolean {
  if (event.stream !== "stdout") {
    return true;
  }

  const parsed = asRecord(event.parsed);
  if (!parsed) {
    return true;
  }

  const rootType = normalizeEventType(parsed.type);
  if (rootType !== "stream_event") {
    return true;
  }

  const nestedEvent = asRecord(parsed.event);
  if (!nestedEvent) {
    return true;
  }

  const eventType = normalizeEventType(nestedEvent.type);
  if (
    eventType === "message_start" ||
    eventType === "message_delta" ||
    eventType === "message_stop" ||
    eventType === "content_block_stop"
  ) {
    return false;
  }

  if (eventType === "content_block_delta") {
    const delta = asRecord(nestedEvent.delta);
    const deltaType = normalizeEventType(delta?.type);
    if (
      deltaType === "input_json_delta" ||
      deltaType === "thinking_delta" ||
      deltaType === "signature_delta"
    ) {
      return false;
    }
  }

  return true;
}

const FIX_JOB_STATUS_ORDER: Record<FixJobStatus, number> = {
  queued: 0,
  running: 1,
  completed: 2,
  failed: 2,
  cancelled: 2,
};

const FIX_STEP_STATUS_ORDER: Record<FixStepStatus, number> = {
  queued: 0,
  running: 1,
  completed: 2,
  failed: 2,
  cancelled: 2,
};

export function mergeFixJobSnapshot(current: FixJob | null, incoming: FixJob | null): FixJob | null {
  if (!incoming) {
    return current;
  }
  if (!current || current.id !== incoming.id) {
    return incoming;
  }

  const incomingJobOrder = FIX_JOB_STATUS_ORDER[incoming.status];
  const currentJobOrder = FIX_JOB_STATUS_ORDER[current.status];
  if (incomingJobOrder > currentJobOrder) {
    return incoming;
  }
  if (incomingJobOrder < currentJobOrder) {
    return current;
  }

  if (incoming.steps.length > current.steps.length) {
    return incoming;
  }
  if (incoming.steps.length < current.steps.length) {
    return current;
  }

  const incomingLatestStep = incoming.steps[incoming.steps.length - 1] ?? null;
  const currentLatestStep = current.steps[current.steps.length - 1] ?? null;
  if (incomingLatestStep && currentLatestStep) {
    const incomingStepOrder = FIX_STEP_STATUS_ORDER[incomingLatestStep.status];
    const currentStepOrder = FIX_STEP_STATUS_ORDER[currentLatestStep.status];
    if (incomingStepOrder > currentStepOrder) {
      return incoming;
    }
    if (incomingStepOrder < currentStepOrder) {
      return current;
    }
  }

  if (incoming.completed_annotations > current.completed_annotations) {
    return incoming;
  }
  if (incoming.completed_annotations < current.completed_annotations) {
    return current;
  }

  return incoming;
}

interface UseFixJobStateOptions {
  activeSessionId: string | null;
}

export function useFixJobState({ activeSessionId }: UseFixJobStateOptions) {
  const [rawFixJob, setFixJob] = useState<FixJob | null>(null);
  const [fixStepLogsByKey, setFixStepLogsByKey] = useState<Record<string, FixJobLogEvent[]>>({});
  const activeSessionIdRef = useRef<string | null>(activeSessionId);
  const refreshRequestIdRef = useRef(0);

  const fixJob = useMemo(() => {
    if (!activeSessionId) {
      return null;
    }
    if (!rawFixJob || rawFixJob.session_id !== activeSessionId) {
      return null;
    }
    return rawFixJob;
  }, [activeSessionId, rawFixJob]);

  const refreshFixJob = useCallback(async () => {
    const targetSessionId = activeSessionId?.trim();
    if (!targetSessionId) {
      setFixJob(null);
      return;
    }

    const requestId = refreshRequestIdRef.current + 1;
    refreshRequestIdRef.current = requestId;

    try {
      const payload = await fetchCurrentFixJob(targetSessionId);

      if (
        refreshRequestIdRef.current !== requestId ||
        activeSessionIdRef.current?.trim() !== targetSessionId
      ) {
        return;
      }

      if (payload.job && payload.job.session_id !== targetSessionId) {
        setFixJob(null);
        return;
      }

      setFixJob((current) => mergeFixJobSnapshot(current, payload.job));
    } catch {
      // Ignore errors so existing annotation workflow remains unaffected.
    }
  }, [activeSessionId]);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const startFixJob = useCallback(async (
    runner: FixRunner,
    model: string,
    variant?: string,
  ) => {
    const targetSessionId = activeSessionId?.trim();
    const payload = await startFixJobRequest(runner, model, variant || null, targetSessionId || null);
    setFixJob((current) => mergeFixJobSnapshot(current, payload.job));
    return payload.job;
  }, [activeSessionId]);

  const cancelFixJob = useCallback(async (jobId: string) => {
    const payload = await cancelFixJobRequest(jobId);
    setFixJob((current) => mergeFixJobSnapshot(current, payload.job));
    return payload.job;
  }, []);

  const applyFixJobUpdate = useCallback((job: FixJob) => {
    setFixJob((current) => mergeFixJobSnapshot(current, job));
  }, []);

  const appendFixJobLog = useCallback((event: FixJobLogEvent) => {
    if (!shouldStoreFixLogEvent(event)) {
      return;
    }

    const stepKey = `${event.job_id}:${event.step_index}`;
    setFixStepLogsByKey((previous) => {
      const existing = previous[stepKey] || [];
      const nextEntries =
        existing.length + 1 > MAX_FIX_STEP_LOG_EVENTS
          ? [...existing.slice(-(MAX_FIX_STEP_LOG_EVENTS - 1)), event]
          : [...existing, event];
      return {
        ...previous,
        [stepKey]: nextEntries,
      };
    });
  }, []);

  useEffect(() => {
    const timerHandle = window.setTimeout(() => {
      void refreshFixJob();
    }, 0);

    return () => {
      window.clearTimeout(timerHandle);
    };
  }, [refreshFixJob]);

  useEffect(() => {
    if (!fixJob || (fixJob.status !== "queued" && fixJob.status !== "running")) {
      return;
    }
    if (!activeSessionId || fixJob.session_id !== activeSessionId) {
      return;
    }

    const intervalHandle = window.setInterval(() => {
      void refreshFixJob();
    }, 1000);

    return () => {
      window.clearInterval(intervalHandle);
    };
  }, [activeSessionId, fixJob, refreshFixJob]);

  return {
    fixJob,
    fixStepLogsByKey,
    refreshFixJob,
    startFixJob,
    cancelFixJob,
    applyFixJobUpdate,
    appendFixJobLog,
    setFixJob,
  };
}
