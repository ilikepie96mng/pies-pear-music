<script lang="ts">
  import { onDestroy } from "svelte";
  import { streamEvents, type SyncEvent } from "../api";

  type Status = "idle" | "queued" | "running" | "done" | "error";
  type Phase = "downloading" | "organizing";

  let url = $state("");
  let format = $state("ALAC");
  let status = $state<Status>("idle");
  let phase = $state<Phase>("downloading");
  let logs = $state<{ id: number; text: string; kind: "info" | "add" | "skip" | "err" }[]>([]);
  let result = $state<{ new: number; skipped: number; errors: number } | null>(null);
  let errorMessage = $state<string | null>(null);
  let queuePosition = $state(0);
  let logEl = $state<HTMLElement | null>(null);
  let streamAbort: AbortController | null = null;
  let nextId = 0;

  const PHASES: { key: Phase; label: string }[] = [
    { key: "downloading", label: "Downloading" },
    { key: "organizing", label: "Organizing" },
  ];

  const PHASE_ORDER: Record<Phase, number> = { downloading: 0, organizing: 1 };

  let phaseIndex = $derived(PHASE_ORDER[phase] ?? 0);

  function classifyLine(text: string): "add" | "skip" | "err" | "info" {
    if (text.includes("added:")) return "add";
    if (text.includes("skipped")) return "skip";
    if (text.includes("error")) return "err";
    return "info";
  }

  function startDownload() {
    if (!url.trim() || status === "running" || status === "queued") return;
    status = "queued";
    phase = "downloading";
    logs = [];
    result = null;
    errorMessage = null;

    streamAbort = new AbortController();
    void streamEvents(`/download/one-off?url=${encodeURIComponent(url.trim())}&format=${encodeURIComponent(format)}`, (data: SyncEvent) => {

      if (data.status === "queued") {
        status = "queued";
        queuePosition = (data as any).position ?? 0;
      } else if (data.status === "running") {
        status = "running";
        if (data.phase === "organizing") phase = "organizing";
        if (data.message) {
          logs = [...logs, { id: nextId++, text: data.message, kind: classifyLine(data.message) }].slice(-800);
          if (logEl) logEl.scrollTop = logEl.scrollHeight;
        }
      } else if (data.status === "done") {
        status = "done";
        result = { new: data.new ?? 0, skipped: data.skipped ?? 0, errors: data.errors ?? 0 };
      } else if (data.status === "error") {
        status = "error";
        errorMessage = data.message ?? "Unknown error";
      }
    }, streamAbort.signal).catch((error) => {
      if (error.name !== "AbortError" && (status === "running" || status === "queued")) {
        status = "error";
        errorMessage = "Lost connection to server.";
      }
    });
  }

  function reset() {
    status = "idle";
    logs = [];
    result = null;
    errorMessage = null;
  }

  onDestroy(() => streamAbort?.abort());
</script>

<div class="flex flex-col h-full overflow-y-auto p-8 max-w-2xl">
  <div class="mb-6">
    <div class="text-amber-500 text-[10px] font-semibold uppercase tracking-widest mb-1">Library</div>
    <h2 class="text-white text-2xl font-bold tracking-tight">Download</h2>
    <p class="text-zinc-600 text-sm mt-1">Paste an Apple Music album or song URL to download and organize it.</p>
  </div>

  <div class="flex gap-2 mb-6">
    <input
      bind:value={url}
      placeholder="https://music.apple.com/…"
      disabled={status === "running" || status === "queued"}
      class="flex-1 bg-[#12100e] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-700 outline-none focus:border-amber-500 disabled:opacity-50"
    />
    <select
      bind:value={format}
      disabled={status === "running" || status === "queued"}
      class="bg-[#12100e] border border-[#2a2a2a] rounded-lg px-2 py-2 text-sm text-zinc-300 outline-none disabled:opacity-50"
    >
      <option value="ALAC">ALAC</option>
      <option value="AAC">AAC</option>
      <option value="ATMOS">ATMOS</option>
    </select>
    <button
      onclick={startDownload}
      disabled={status === "running" || status === "queued" || !url.trim()}
      class="text-sm font-bold px-4 rounded-lg hover:bg-amber-400 transition-colors disabled:opacity-50" style="background:var(--accent);color:black;"
    >
      ↓ Download
    </button>
  </div>

  {#if status === "queued"}
    <div class="flex items-center gap-3 text-zinc-400 text-sm mb-6">
      <span class="w-4 h-4 border border-zinc-600 border-t-zinc-300 rounded-full animate-spin flex-shrink-0"></span>
      Waiting in queue{queuePosition > 0 ? ` — position ${queuePosition}` : ""}…
    </div>
  {:else if status === "running"}
    <div class="flex items-center gap-0 mb-6">
      {#each PHASES as step, i}
        {@const done = phaseIndex > i}
        {@const active = phaseIndex === i}
        <div class="flex items-center gap-0">
          <div class="flex flex-col items-center gap-1">
            <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors
              {done   ? 'bg-amber-900/60 text-amber-400 border border-amber-800/50' :
               active  ? 'bg-amber-800/60 text-amber-300 border border-amber-700/50' :
                         'bg-[#1a1a1a] text-zinc-600 border border-[#2a2a2a]'}">
              {#if done}✓{:else if active}
                <span class="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse"></span>
              {:else}{i + 1}{/if}
            </div>
            <span class="text-[9px] uppercase tracking-widest font-semibold whitespace-nowrap
              {done ? 'text-amber-500' : active ? 'text-amber-400' : 'text-zinc-700'}">
              {step.label}
            </span>
          </div>
          {#if i < PHASES.length - 1}
            <div class="w-12 h-px mb-4 mx-1 transition-colors {done ? 'bg-amber-900/50' : 'bg-[#222]'}"></div>
          {/if}
        </div>
      {/each}
    </div>

    <div
      bind:this={logEl}
      class="flex-1 min-h-0 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 overflow-y-auto font-mono text-xs leading-relaxed"
    >
      {#each logs as line (line.id)}
        <div class="
          {line.kind === 'add'  ? 'text-amber-400' :
           line.kind === 'skip' ? 'text-zinc-600' :
           line.kind === 'err'  ? 'text-red-400' :
                                  'text-zinc-500'}">
          {line.text}
        </div>
      {/each}
      {#if logs.length === 0}
        <div class="text-zinc-700">Waiting for output…</div>
      {/if}
    </div>

  {:else if status === "done" && result}
    <div class="bg-[#12100e] rounded-xl p-6 border border-[rgba(255,255,255,0.06)]">
      <div class="text-amber-400 font-bold text-sm mb-4 flex items-center gap-2">✓ Download complete</div>
      <div class="flex gap-6">
        <div>
          <div class="text-white text-3xl font-bold tabular-nums">{result.new}</div>
          <div class="text-zinc-500 text-xs mt-1">new tracks</div>
        </div>
        <div>
          <div class="text-zinc-400 text-3xl font-bold tabular-nums">{result.skipped}</div>
          <div class="text-zinc-500 text-xs mt-1">already owned</div>
        </div>
        <div>
          <div class="text-3xl font-bold tabular-nums {result.errors > 0 ? 'text-red-400' : 'text-zinc-700'}">{result.errors}</div>
          <div class="text-zinc-500 text-xs mt-1">errors</div>
        </div>
      </div>
    </div>
    {#if logs.length > 0}
      <details class="mt-4 group">
        <summary class="text-zinc-600 text-xs cursor-pointer hover:text-zinc-400 flex items-center gap-1.5 select-none">
          <span class="group-open:rotate-90 transition-transform inline-block">▶</span>
          Log
        </summary>
        <div class="mt-2 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 font-mono text-xs text-zinc-600 max-h-48 overflow-y-auto leading-relaxed">
          {#each logs as line (line.id)}
            <div class="{line.kind === 'add' ? 'text-amber-500/70' : line.kind === 'err' ? 'text-red-400/70' : ''}">{line.text}</div>
          {/each}
        </div>
      </details>
    {/if}
    <button onclick={reset} class="mt-4 text-zinc-500 hover:text-white text-sm transition-colors">Download another</button>

  {:else if status === "error"}
    <div class="bg-red-950/30 border border-red-900/50 rounded-xl p-5">
      <div class="text-red-400 font-bold mb-1">Download failed</div>
      <div class="text-zinc-400 text-sm leading-relaxed">{errorMessage}</div>
    </div>
    {#if logs.length > 0}
      <div class="mt-4 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 font-mono text-xs text-zinc-600 max-h-48 overflow-y-auto leading-relaxed">
        {#each logs as line (line.id)}
          <div class="{line.kind === 'err' ? 'text-red-400' : ''}">{line.text}</div>
        {/each}
      </div>
    {/if}
    <button onclick={reset} class="mt-4 text-zinc-500 hover:text-white text-sm transition-colors">Try again</button>
  {/if}
</div>
