<script lang="ts">
  import { onMount, onDestroy, tick } from "svelte";
  import { api, type SyncEvent } from "../api";

  interface Props {
    playlistName: string;
    ondone: () => void;
  }
  let { playlistName, ondone }: Props = $props();

  type Status = "running" | "done" | "error";
  type Phase = "processing" | "done" | string;
  type LogLine = {
    id: number;
    text: string;
    kind: "info" | "add" | "skip" | "err" | "done";
  };
  const MAX_RENDERED_LOGS = 800;
  const LOG_FLUSH_MS = 60;

  let status = $state<Status>("running");
  let phase = $state<Phase>("processing");
  let logs = $state<LogLine[]>([]);
  let result = $state<{ new: number; skipped: number; errors: number } | null>(null);
  let errorMessage = $state<string | null>(null);
  let logEl = $state<HTMLElement | null>(null);
  let source: EventSource | null = null;
  let copied = $state(false);
  let copiedLogPath = $state(false);
  let autoFollow = $state(true);
  let latestMessage = $state("Waiting for output…");
  let logPath = $state<string | null>(null);

  // Live counters during processing
  let liveNew = $state(0);
  let liveSkipped = $state(0);
  let liveErrors = $state(0);
  let progressCurrent = $state(0);
  let progressTotal = $state(0);
  let totalLogCount = $state(0);

  let nextLogId = 0;
  let allLogText = "";
  let pendingLogs: LogLine[] = [];
  let flushTimer: ReturnType<typeof setTimeout> | null = null;

  // Phase timeline
  const PHASES = [
    { key: "processing", label: "Processing" },
    { key: "done",       label: "Complete" },
  ] as const;

  const PHASE_ORDER: Record<string, number> = {
    processing: 0, done: 1,
  };

  let phaseIndex = $derived(PHASE_ORDER[phase] ?? 0);

  function classifyLine(text: string): "add" | "skip" | "err" | "done" | "info" {
    if (text.includes("added:")) return "add";
    if (text.includes("skipped")) return "skip";
    if (text.includes("error processing") || text.startsWith("[!")) return "err";
    if (text.startsWith("Sync complete")) return "done";
    return "info";
  }

  function parseProgress(text: string) {
    const m = text.match(/^\[(\d+)\/(\d+)\]/);
    if (m) {
      progressCurrent = parseInt(m[1]);
      progressTotal = parseInt(m[2]);
    }
  }

  let progressPct = $derived(
    progressTotal > 0 ? Math.round((progressCurrent / progressTotal) * 100) : 0
  );

  function classifyError(msg: string): { headline: string; detail: string } {
    const m = msg.toLowerCase();
    if (m.includes("no .m4a files")) {
      return { headline: "No files to process", detail: msg };
    }
    if (m.includes("timed out") || m.includes("timeout")) {
      return { headline: "Connection timed out", detail: "Check your network and try again." };
    }
    if (m.includes("paused")) {
      return { headline: "Playlist is paused", detail: "Resume the playlist before syncing." };
    }
    return { headline: "Sync failed", detail: msg };
  }

  async function scrollToBottom() {
    await tick();
    if (logEl && autoFollow) logEl.scrollTop = logEl.scrollHeight;
  }

  async function flushPendingLogs() {
    if (flushTimer !== null) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (pendingLogs.length === 0) return;
    logs = [...logs, ...pendingLogs].slice(-MAX_RENDERED_LOGS);
    pendingLogs = [];
    await scrollToBottom();
  }

  function scheduleLogFlush() {
    if (flushTimer !== null) return;
    flushTimer = setTimeout(() => {
      flushTimer = null;
      void flushPendingLogs();
    }, LOG_FLUSH_MS);
  }

  function appendLog(text: string, kind: LogLine["kind"]) {
    pendingLogs.push({ id: nextLogId++, text, kind });
    totalLogCount += 1;
    allLogText = allLogText ? `${allLogText}\n${text}` : text;
    scheduleLogFlush();
  }

  function handleLogScroll() {
    if (!logEl) return;
    const distanceFromBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
    autoFollow = distanceFromBottom < 24;
  }

  async function copyLog() {
    const text = allLogText || logs.map(l => l.text).join("\n");
    await navigator.clipboard.writeText(text);
    copied = true;
    setTimeout(() => (copied = false), 2000);
  }

  async function copyLogPath() {
    if (!logPath) return;
    await navigator.clipboard.writeText(logPath);
    copiedLogPath = true;
    setTimeout(() => (copiedLogPath = false), 2000);
  }

  onMount(() => {
    source = new EventSource(api.syncUrl(playlistName));

    source.onmessage = async (e) => {
      const data: SyncEvent = JSON.parse(e.data);
      status = data.status;
      if (data.log_path) logPath = data.log_path;

      if (data.status === "running") {
        if (data.phase) phase = data.phase;
        if (data.message) {
          latestMessage = data.message;
          const kind = classifyLine(data.message);
          appendLog(data.message, kind);
          parseProgress(data.message);
          if (kind === "add") liveNew++;
          else if (kind === "skip") liveSkipped++;
          else if (kind === "err") liveErrors++;
        }
      } else if (data.status === "done") {
        await flushPendingLogs();
        phase = "done";
        latestMessage = `Sync complete: ${data.new ?? 0} new, ${data.skipped ?? 0} skipped, ${data.errors ?? 0} errors`;
        result = { new: data.new ?? 0, skipped: data.skipped ?? 0, errors: data.errors ?? 0 };
        source?.close();
      } else if (data.status === "error") {
        await flushPendingLogs();
        errorMessage = data.message ?? "Unknown error";
        latestMessage = errorMessage;
        source?.close();
      }
    };

    source.onerror = () => {
      if (status === "running") {
        status = "error";
        errorMessage = "Lost connection to sync server.";
      }
      source?.close();
    };
  });

  onDestroy(() => {
    if (flushTimer !== null) clearTimeout(flushTimer);
    source?.close();
  });
</script>

<div class="flex flex-col h-full p-8 max-w-2xl">

  <!-- Header -->
  <div class="mb-6">
    <div class="text-amber-500 text-[10px] font-semibold uppercase tracking-widest mb-1">Syncing</div>
    <h2 class="text-white text-2xl font-bold tracking-tight">{playlistName}</h2>
  </div>

  {#if logPath}
    <div class="mb-4 flex items-center justify-between gap-3 rounded-xl border border-[#1a1a1a] bg-[#111] px-3 py-2">
      <div class="min-w-0">
        <div class="text-[10px] uppercase tracking-widest text-zinc-600 font-semibold">Session log</div>
        <div class="truncate font-mono text-[11px] text-zinc-400" title={logPath}>{logPath}</div>
      </div>
      <button
        onclick={copyLogPath}
        class="shrink-0 text-[10px] px-2 py-1 rounded bg-[#1a1a1a] text-zinc-500 hover:text-white transition-colors uppercase tracking-widest font-semibold"
      >
        {copiedLogPath ? "Copied" : "Copy Path"}
      </button>
    </div>
  {/if}

  <!-- Phase timeline -->
  <div class="flex items-center gap-0 mb-7">
    {#each PHASES as step, i}
      {@const done = status === "done" ? true : phaseIndex > i}
      {@const active = phaseIndex === i && status === "running"}
      <div class="flex items-center gap-0">
        <div class="flex flex-col items-center gap-1">
          <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors
            {done   ? 'bg-green-900/60 text-green-400 border border-green-800/50' :
             active  ? 'bg-amber-800/60 text-amber-300 border border-amber-700/50' :
                       'bg-[#1a1a1a] text-zinc-600 border border-[#2a2a2a]'}">
            {#if done}✓{:else if active}
              <span class="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse"></span>
            {:else}{i + 1}{/if}
          </div>
          <span class="text-[9px] uppercase tracking-widest font-semibold whitespace-nowrap
            {done ? 'text-green-500' : active ? 'text-amber-400' : 'text-zinc-700'}">
            {step.label}
          </span>
        </div>
        {#if i < PHASES.length - 1}
          <div class="w-12 h-px mb-4 mx-1 transition-colors {done ? 'bg-green-900/50' : 'bg-[#222]'}"></div>
        {/if}
      </div>
    {/each}
  </div>

  {#if status === "running"}
    <!-- Live counters (visible during processing) -->
    {#if phase === "processing" && progressTotal > 0}
      <div class="flex gap-4 mb-4">
        <div class="flex-1 bg-[#111] border border-[#1e1e1e] rounded-xl px-4 py-3">
          <div class="text-green-400 text-xl font-bold">{liveNew}</div>
          <div class="text-zinc-600 text-xs mt-0.5">new</div>
        </div>
        <div class="flex-1 bg-[#111] border border-[#1e1e1e] rounded-xl px-4 py-3">
          <div class="text-zinc-400 text-xl font-bold">{liveSkipped}</div>
          <div class="text-zinc-600 text-xs mt-0.5">skipped</div>
        </div>
        <div class="flex-1 bg-[#111] border border-[#1e1e1e] rounded-xl px-4 py-3">
          <div class="text-xl font-bold {liveErrors > 0 ? 'text-red-400' : 'text-zinc-600'}">{liveErrors}</div>
          <div class="text-zinc-600 text-xs mt-0.5">errors</div>
        </div>
      </div>
    {/if}

    <!-- Progress bar -->
    <div class="mb-3">
      <div class="flex justify-between text-xs text-zinc-600 mb-1.5">
        <span>
          {#if progressTotal > 0}
            {progressCurrent} / {progressTotal} tracks
          {:else}
            Working…
          {/if}
        </span>
        {#if progressTotal > 0}
          <span>{progressPct}%</span>
        {/if}
      </div>
      <div class="h-1 bg-[#1a1a1a] rounded-full overflow-hidden">
        {#if progressTotal > 0}
          <div class="h-full bg-[#1db954] rounded-full transition-all duration-300" style="width: {progressPct}%"></div>
        {:else}
          <div class="h-full bg-amber-700 rounded-full w-full animate-pulse"></div>
        {/if}
      </div>
    </div>

    <div class="mb-3">
      <div class="text-xs text-zinc-500 truncate" title={latestMessage}>{latestMessage}</div>
    </div>

    <!-- Log -->
    <div
      bind:this={logEl}
      onscroll={handleLogScroll}
      class="flex-1 min-h-0 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 overflow-y-auto font-mono text-xs leading-relaxed"
    >
      {#each logs as line (line.id)}
        <div class="
          {line.kind === 'add'  ? 'text-green-400' :
           line.kind === 'skip' ? 'text-zinc-600' :
           line.kind === 'err'  ? 'text-red-400' :
           line.kind === 'done' ? 'text-amber-400' :
                                  'text-zinc-500'}">
          {line.text}
        </div>
      {/each}
      {#if logs.length === 0}
        <div class="text-zinc-700">Waiting for output…</div>
      {/if}
    </div>

    {#if totalLogCount > logs.length}
      <div class="mt-2 text-[10px] text-zinc-700 uppercase tracking-widest">
        Showing latest {logs.length} of {totalLogCount} lines
      </div>
    {/if}

    {#if !autoFollow}
      <div class="mt-3 flex justify-end">
        <button
          onclick={() => {
            autoFollow = true;
            scrollToBottom();
          }}
          class="text-[10px] px-2.5 py-1 rounded-lg bg-[#1a1a1a] text-zinc-500 hover:text-white transition-colors uppercase tracking-widest font-semibold"
        >
          Jump To Latest
        </button>
      </div>
    {/if}

  {:else if status === "done" && result}
    <!-- Result -->
    <div class="bg-[#111] rounded-xl p-6 border border-[#1e1e1e] mb-4">
      <div class="text-green-400 font-bold text-sm mb-4 flex items-center gap-2">
        <span>✓</span> Sync complete
      </div>
      <div class="flex gap-6">
        <div>
          <div class="text-white text-3xl font-bold tabular-nums">{result.new}</div>
          <div class="text-zinc-500 text-xs mt-1">new tracks</div>
        </div>
        <div>
          <div class="text-zinc-400 text-3xl font-bold tabular-nums">{result.skipped}</div>
          <div class="text-zinc-500 text-xs mt-1">skipped</div>
        </div>
        <div>
          <div class="text-3xl font-bold tabular-nums {result.errors > 0 ? 'text-red-400' : 'text-zinc-700'}">{result.errors}</div>
          <div class="text-zinc-500 text-xs mt-1">errors</div>
        </div>
      </div>
    </div>

    {#if logs.length > 0}
      <details class="mb-4 group">
        <summary class="text-zinc-600 text-xs cursor-pointer hover:text-zinc-400 flex items-center gap-1.5 select-none">
          <span class="group-open:rotate-90 transition-transform inline-block">▶</span>
          Log ({totalLogCount} lines)
        </summary>
        <div class="mt-2 relative">
          <div class="bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 font-mono text-xs text-zinc-600 max-h-48 overflow-y-auto leading-relaxed">
            {#each logs as line (line.id)}
              <div class="{line.kind === 'add' ? 'text-green-500/70' : line.kind === 'err' ? 'text-red-400/70' : ''}">{line.text}</div>
            {/each}
          </div>
          <button onclick={copyLog}
            class="absolute top-2 right-2 text-[10px] px-2 py-1 rounded bg-[#1a1a1a] text-zinc-500 hover:text-white transition-colors">
            {copied ? "✓ copied" : "copy"}
          </button>
        </div>
      </details>
    {/if}

    <button onclick={ondone}
      class="w-full bg-[#1a1a1a] hover:bg-[#222] text-white font-semibold py-2.5 rounded-xl transition-colors text-sm">
      ← Back to playlist
    </button>

  {:else if status === "error"}
    {@const classified = classifyError(errorMessage ?? "")}
    <div class="bg-red-950/30 border border-red-900/50 rounded-xl p-5 mb-4">
      <div class="text-red-400 font-bold mb-1">{classified.headline}</div>
      <div class="text-zinc-400 text-sm leading-relaxed">{classified.detail}</div>
    </div>

    {#if logs.length > 0}
      <details open class="mb-4 group">
        <summary class="text-zinc-600 text-xs cursor-pointer hover:text-zinc-400 flex items-center gap-1.5 select-none">
          <span class="group-open:rotate-90 transition-transform inline-block">▶</span>
          Log ({totalLogCount} lines)
        </summary>
        <div class="mt-2 relative">
          <div class="bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 font-mono text-xs max-h-64 overflow-y-auto leading-relaxed">
            {#each logs as line (line.id)}
              <div class="
                {line.kind === 'err' ? 'text-red-400' :
                 line.kind === 'add' ? 'text-green-400/70' :
                                       'text-zinc-600'}">
                {line.text}
              </div>
            {/each}
          </div>
          <button onclick={copyLog}
            class="absolute top-2 right-2 text-[10px] px-2 py-1 rounded bg-[#1a1a1a] text-zinc-500 hover:text-white transition-colors">
            {copied ? "✓ copied" : "copy log"}
          </button>
        </div>
      </details>
    {/if}

    <button onclick={ondone} class="text-zinc-500 hover:text-white text-sm transition-colors">← Back</button>
  {/if}
</div>
