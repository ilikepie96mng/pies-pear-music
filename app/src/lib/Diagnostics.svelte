<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type DiagnosticCheck } from "../api";

  interface Props {
    onopenSettings?: () => void;
  }
  let { onopenSettings }: Props = $props();

  const GROUPS: { title: string; labels: string[]; critical?: boolean }[] = [
    { title: "System tools", labels: ["Podman", "Go", "FFmpeg", "MP4Box", "mp4decrypt"] },
    { title: "Configuration", labels: ["Config file", "Music directory", "State directory", "alac-rip directory"], critical: true },
    { title: "External sources", labels: ["Downloader source", "Wrapper source"], critical: true },
  ];

  const CRITICAL = new Set([
    "Config file", "Music directory", "State directory", "alac-rip directory",
    "Downloader source", "Wrapper source",
  ]);

  let checks = $state<DiagnosticCheck[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastRefreshed = $state<Date | null>(null);
  let autoRefresh = $state(true);
  let intervalId: ReturnType<typeof setInterval> | null = null;

  function checksForGroup(labels: string[]): DiagnosticCheck[] {
    return labels.map(l => checks.find(c => c.label === l) ?? { label: l, ok: false, detail: "not checked" });
  }

  let overallOk = $derived(checks.length > 0 && checks.every(c => !CRITICAL.has(c.label) || c.ok));
  let criticalCount = $derived(checks.filter(c => CRITICAL.has(c.label) && !c.ok).length);
  let warnCount = $derived(checks.filter(c => !CRITICAL.has(c.label) && !c.ok).length);

  async function refresh() {
    loading = true;
    error = null;
    try {
      checks = await api.diagnostics();
      lastRefreshed = new Date();
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function toggleAutoRefresh() {
    autoRefresh = !autoRefresh;
    if (autoRefresh) startInterval();
    else stopInterval();
  }

  function startInterval() {
    intervalId = setInterval(refresh, 30_000);
  }

  function stopInterval() {
    if (intervalId !== null) { clearInterval(intervalId); intervalId = null; }
  }

  onMount(() => {
    refresh();
    startInterval();
  });

  onDestroy(stopInterval);

  let now = $state(Date.now());
  const ticker = setInterval(() => { now = Date.now(); }, 5000);
  onDestroy(() => clearInterval(ticker));

  function timeAgo(d: Date): string {
    const s = Math.floor((now - d.getTime()) / 1000);
    if (s < 5) return "just now";
    if (s < 60) return `${s}s ago`;
    return `${Math.floor(s / 60)}m ago`;
  }
</script>

<div class="p-8 max-w-2xl h-full overflow-y-auto">
  <!-- Header -->
  <div class="flex items-start justify-between mb-6">
    <div>
      <h1 class="text-white text-2xl font-bold tracking-tight">Diagnostics</h1>
      <p class="text-zinc-500 text-sm mt-1">Environment health and dependency status</p>
    </div>
    <div class="flex items-center gap-2 mt-1">
      {#if lastRefreshed}
        <span class="text-zinc-600 text-xs">{timeAgo(lastRefreshed)}</span>
      {/if}
      <button onclick={refresh} disabled={loading}
        class="px-3 py-1.5 rounded-lg text-xs text-zinc-400 hover:text-white bg-[#1a1a1a] hover:bg-[#222] transition-colors disabled:opacity-40 flex items-center gap-1.5">
        {#if loading}
          <span class="inline-block w-3 h-3 border border-zinc-600 border-t-amber-500 rounded-full animate-spin"></span>
        {:else}
          ↺
        {/if}
        Refresh
      </button>
      <button onclick={toggleAutoRefresh}
        class="px-3 py-1.5 rounded-lg text-xs transition-colors
          {autoRefresh ? 'bg-amber-900/40 text-amber-400 border border-amber-800/50' : 'bg-[#1a1a1a] text-zinc-500 hover:text-zinc-300'}">
        Auto {autoRefresh ? "on" : "off"}
      </button>
    </div>
  </div>

  <!-- Summary banner -->
  {#if !loading && checks.length}
    <div class="rounded-xl px-4 py-3 mb-6 flex items-center gap-3 border
      {overallOk
        ? 'bg-amber-950/30 border-amber-900/50 text-amber-400'
        : criticalCount > 0
          ? 'bg-red-950/30 border-red-900/50 text-red-400'
          : 'bg-amber-950/30 border-amber-900/50 text-amber-400'}">
      <span class="text-lg">{overallOk ? "✓" : "✗"}</span>
      <div>
        {#if overallOk}
          <span class="font-semibold">All checks passing</span>
          <span class="text-xs opacity-70 ml-2">— ready to sync</span>
        {:else if criticalCount > 0}
          <span class="font-semibold">{criticalCount} critical {criticalCount === 1 ? "issue" : "issues"}</span>
          {#if warnCount > 0}<span class="text-xs opacity-70 ml-2">+ {warnCount} warning{warnCount === 1 ? "" : "s"}</span>{/if}
        {:else}
          <span class="font-semibold">{warnCount} {warnCount === 1 ? "warning" : "warnings"}</span>
          <span class="text-xs opacity-70 ml-2">— non-critical, sync should work</span>
        {/if}
      </div>
    </div>
  {:else if error}
    <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 mb-6 text-red-400 text-sm">{error}</div>
  {/if}

  <!-- Check groups -->
  <div class="flex flex-col gap-4">
    {#each GROUPS as group}
      {@const groupChecks = checksForGroup(group.labels)}
      {@const groupFailing = groupChecks.filter(c => !c.ok).length}
      <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden">
        <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between">
          <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">{group.title}</span>
          {#if !loading}
            {#if groupFailing === 0}
              <span class="text-amber-500 text-xs">✓ all clear</span>
            {:else if group.critical}
              <span class="text-red-400 text-xs">{groupFailing} critical</span>
            {:else}
              <span class="text-amber-500 text-xs">{groupFailing} warning{groupFailing > 1 ? "s" : ""}</span>
            {/if}
          {/if}
        </div>

        <div class="divide-y divide-[#181818]">
          {#each groupChecks as check}
            <div class="flex items-start gap-3 px-4 py-3">
              {#if loading && checks.length === 0}
                <div class="w-4 h-4 mt-0.5 rounded-full bg-[#222] animate-pulse flex-shrink-0"></div>
              {:else}
                <span class="flex-shrink-0 mt-0.5 text-sm font-bold
                  {check.ok ? 'text-amber-500' : CRITICAL.has(check.label) ? 'text-red-500' : 'text-amber-500'}">
                  {check.ok ? "✓" : "✗"}
                </span>
              {/if}
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm text-white">{check.label}</span>
                  {#if !check.ok && CRITICAL.has(check.label)}
                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-red-950 text-red-400 border border-red-900/50 uppercase tracking-wider font-semibold">critical</span>
                  {/if}
                </div>
                {#if check.detail}
                  <div class="text-zinc-600 text-xs mt-0.5 font-mono truncate" title={check.detail}>{check.detail}</div>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </div>
    {/each}
  </div>

  {#if !loading && checks.some(c => !c.ok) && onopenSettings}
    <div class="mt-4 flex justify-end">
      <button onclick={onopenSettings}
        class="text-[10px] px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-zinc-400 hover:text-white transition-colors uppercase tracking-widest font-semibold">
        Go to Settings →
      </button>
    </div>
  {/if}
</div>
