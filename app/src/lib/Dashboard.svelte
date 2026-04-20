<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Stats, type DiagnosticCheck } from "../api";

  interface Props {
    onstartSync: (name: string) => void;
    onselectPlaylist: (name: string) => void;
    onopenDiagnostics: () => void;
  }

  let { onstartSync, onselectPlaylist, onopenDiagnostics }: Props = $props();

  let stats = $state<Stats | null>(null);
  let checks = $state<DiagnosticCheck[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  const CRITICAL = new Set(["Config file", "Music directory", "State directory"]);

  let criticalIssues = $derived(checks.filter(c => CRITICAL.has(c.label) && !c.ok));
  let healthOk = $derived(criticalIssues.length === 0);

  onMount(async () => {
    try {
      [stats, checks] = await Promise.all([api.stats(), api.diagnostics()]);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  });

  function formatDate(iso: string | null): string {
    if (!iso) return "Never";
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffH = diffMs / 3_600_000;
    if (diffH < 1) return "Less than an hour ago";
    if (diffH < 24) return `${Math.floor(diffH)}h ago`;
    if (diffH < 48) return "Yesterday";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
</script>

<div class="p-8 max-w-2xl">
  <div class="mb-8">
    <h1 class="text-white text-2xl font-bold tracking-tight">Dashboard</h1>
    <p class="text-zinc-500 text-sm mt-1">Overview of your local archive</p>
  </div>

  {#if loading}
    <div class="flex flex-col gap-4">
      {#each [1,2,3] as _}
        <div class="h-20 rounded-xl bg-[#111] animate-pulse border border-[#1e1e1e]"></div>
      {/each}
    </div>
  {:else if error}
    <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 text-red-400 text-sm">{error}</div>
  {:else if stats}

    <!-- Health banner -->
    <div class="rounded-xl px-4 py-3 mb-6 flex items-center justify-between border
      {healthOk
        ? 'bg-green-950/20 border-green-900/40'
        : 'bg-red-950/20 border-red-900/40'}">
      <div class="flex items-center gap-3">
        <span class="text-lg {healthOk ? 'text-green-500' : 'text-red-500'}">{healthOk ? "✓" : "✗"}</span>
        <div>
          <div class="text-sm font-semibold {healthOk ? 'text-green-400' : 'text-red-400'}">
            {healthOk ? "System healthy" : `${criticalIssues.length} critical issue${criticalIssues.length > 1 ? "s" : ""}`}
          </div>
          {#if !healthOk}
            <div class="text-zinc-500 text-xs mt-0.5">{criticalIssues.map(c => c.label).join(", ")}</div>
          {/if}
        </div>
      </div>
      {#if !healthOk}
        <button onclick={onopenDiagnostics}
          class="text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-zinc-400 hover:text-white transition-colors">
          View details →
        </button>
      {/if}
    </div>

    <!-- Stat cards -->
    <div class="grid grid-cols-3 gap-3 mb-6">
      <div class="bg-[#111] border border-[#1e1e1e] rounded-xl px-4 py-4">
        <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Playlists</div>
        <div class="text-white text-3xl font-bold tracking-tight">{stats.playlist_count}</div>
        <div class="text-zinc-600 text-xs mt-1">tracked</div>
      </div>
      <div class="bg-[#111] border border-[#1e1e1e] rounded-xl px-4 py-4">
        <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Tracks</div>
        <div class="text-white text-3xl font-bold tracking-tight">{stats.total_tracks.toLocaleString()}</div>
        <div class="text-zinc-600 text-xs mt-1">downloaded</div>
      </div>
      <div class="bg-[#111] border border-[#1e1e1e] rounded-xl px-4 py-4">
        <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Last sync</div>
        <div class="text-white text-lg font-bold tracking-tight leading-tight mt-1">{formatDate(stats.last_sync)}</div>
      </div>
    </div>

    <!-- Playlist table -->
    {#if stats.playlists.length > 0}
      <div class="border border-[#1e1e1e] rounded-xl overflow-hidden mb-6">
        <div class="px-4 py-2.5 bg-[#111] border-b border-[#1e1e1e]">
          <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Playlists</span>
        </div>
        <div class="divide-y divide-[#181818]">
          {#each stats.playlists as pl}
            <div class="flex items-center gap-3 px-4 py-3 hover:bg-[#111] transition-colors group">
              <div class="flex-1 min-w-0">
                <button
                  onclick={() => onselectPlaylist(pl.name)}
                  class="text-sm text-white font-medium hover:text-amber-400 transition-colors text-left truncate block max-w-[200px]">
                  {pl.name}
                </button>
                <div class="text-zinc-600 text-xs mt-0.5">{formatDate(pl.last_synced)}</div>
              </div>
              <div class="text-zinc-500 text-sm tabular-nums">{pl.track_count.toLocaleString()} tracks</div>
              <button
                onclick={() => onstartSync(pl.name)}
                class="opacity-0 group-hover:opacity-100 transition-opacity px-2.5 py-1 rounded-lg text-xs bg-[#1a1a1a] text-zinc-400 hover:text-white hover:bg-[#222]">
                Sync →
              </button>
            </div>
          {/each}
        </div>
      </div>
    {:else}
      <div class="border border-[#1e1e1e] rounded-xl px-6 py-10 text-center bg-[#111]">
        <div class="text-zinc-600 text-sm">No playlists added yet</div>
        <div class="text-zinc-700 text-xs mt-1">Add one from the sidebar to get started</div>
      </div>
    {/if}

  {/if}
</div>
