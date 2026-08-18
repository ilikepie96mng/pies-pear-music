<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type Stats, type DiagnosticCheck, type SyncRun, type IntegrationsHealth } from "../api";

  interface Props {
    onstartSync: (name: string) => void;
    onselectPlaylist: (name: string) => void;
    onopenDiagnostics: () => void;
    onopenSettings?: () => void;
  }

  let { onstartSync, onselectPlaylist, onopenDiagnostics, onopenSettings }: Props = $props();

  let stats = $state<Stats | null>(null);
  let checks = $state<DiagnosticCheck[]>([]);
  let recentRuns = $state<SyncRun[]>([]);
  let integrationsHealth = $state<IntegrationsHealth | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Widget customizer toggles
  let showStatsWidget = $state(true);
  let showHealthWidget = $state(true);
  let showAppleMusicWidget = $state(true);
  let showPlaylistsWidget = $state(true);
  let showActivityWidget = $state(true);
  let showCustomizer = $state(false);

  const CRITICAL = new Set(["Config file", "Music directory", "State directory"]);

  let criticalIssues = $derived(checks.filter(c => CRITICAL.has(c.label) && !c.ok));
  let healthOk = $derived(criticalIssues.length === 0);

  // ── Wrapper auth state ──────────────────────────────────────────────────────
  let wrapperRunning = $state(false);
  let wrapperNeeds2fa = $state(false);
  let wrapper2faType = $state("");
  let wrapperLogs = $state<string[]>([]);
  let wrapperEmail = $state("");
  let wrapperPassword = $state("");
  let twoFaCode = $state("");
  let wrapperBusy = $state(false);
  let wrapperError = $state<string | null>(null);
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function pollWrapper() {
    try {
      const s = await api.wrapper.status();
      wrapperRunning = s.running;
      wrapperNeeds2fa = s.needs_2fa;
      wrapper2faType = s["2fa_type"];
      wrapperLogs = s.logs;
    } catch {}
  }

  async function loginWrapper() {
    if (!wrapperEmail || !wrapperPassword) return;
    wrapperBusy = true;
    wrapperError = null;
    try {
      const res = await api.wrapper.login(wrapperEmail, wrapperPassword);
      if (res.status === "error") wrapperError = res.msg;
    } catch (e) {
      wrapperError = String(e);
    } finally {
      wrapperBusy = false;
    }
  }

  async function stopWrapper() {
    wrapperBusy = true;
    try { await api.wrapper.stop(); } catch {}
    wrapperBusy = false;
  }

  async function submit2fa() {
    if (!twoFaCode) return;
    wrapperBusy = true;
    try {
      await api.wrapper.submit2fa(twoFaCode);
      twoFaCode = "";
    } catch {}
    wrapperBusy = false;
  }

  onMount(async () => {
    try {
      // Load saved widget preferences
      try {
        const savedWidgets = localStorage.getItem("pies_dashboard_widgets");
        if (savedWidgets) {
          const parsed = JSON.parse(savedWidgets);
          if (parsed.showStats !== undefined) showStatsWidget = parsed.showStats;
          if (parsed.showHealth !== undefined) showHealthWidget = parsed.showHealth;
          if (parsed.showAppleMusic !== undefined) showAppleMusicWidget = parsed.showAppleMusic;
          if (parsed.showPlaylists !== undefined) showPlaylistsWidget = parsed.showPlaylists;
          if (parsed.showActivity !== undefined) showActivityWidget = parsed.showActivity;
        }
      } catch {}

      const [s, c, r, ih] = await Promise.all([
        api.stats(),
        api.diagnostics(),
        api.syncHistory(undefined, 10),
        api.getIntegrationsHealth(),
      ]);
      stats = s;
      checks = c;
      recentRuns = r;
      integrationsHealth = ih;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
    pollWrapper();
    pollTimer = setInterval(pollWrapper, 2000);
  });

  function saveWidgetPreferences() {
    try {
      localStorage.setItem(
        "pies_dashboard_widgets",
        JSON.stringify({
          showStats: showStatsWidget,
          showHealth: showHealthWidget,
          showAppleMusic: showAppleMusicWidget,
          showPlaylists: showPlaylistsWidget,
          showActivity: showActivityWidget,
        }),
      );
    } catch {}
  }

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
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

  function formatDuration(start: string, end: string): string {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 1000) return "<1s";
    if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
    return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
  }
</script>

<div class="relative h-full overflow-y-auto">
  <div aria-hidden="true" class="pointer-events-none absolute inset-x-0 top-0 h-52"
    style="background:radial-gradient(ellipse at 80% 0%,rgba(94,234,212,0.36) 0%,rgba(252,211,77,0.34) 45%,transparent 85%);"></div>
  <div aria-hidden="true" class="pointer-events-none absolute inset-x-0 top-0 h-52"
    style="background:linear-gradient(180deg,transparent 60%,var(--bg) 100%);"></div>
  <div class="relative p-6 pt-5 max-w-3xl">
    <div class="mb-6 flex items-start justify-between">
      <div>
        <div class="text-[#5eead4] text-[10px] font-bold tracking-[0.18em] uppercase mb-1.5">Overview</div>
        <h1 class="text-white text-3xl font-extrabold tracking-tight leading-none"
          style="background:linear-gradient(135deg,#fff 0%,#a7f3d0 50%,#fde68a 100%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">Dashboard</h1>
        <p class="text-zinc-400 text-xs mt-2">Your local archive & connected ecosystem at a glance</p>
      </div>

      <button
        onclick={() => (showCustomizer = !showCustomizer)}
        class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-zinc-800 bg-zinc-900/80 hover:bg-zinc-800 text-zinc-300 transition-colors flex items-center gap-1.5"
      >
        <span>⚙️</span> Customize Widgets
      </button>
    </div>

    <!-- Widget Visibility Customizer Dropdown -->
    {#if showCustomizer}
      <div class="mb-6 p-4 rounded-xl border border-zinc-800 bg-[#141210] space-y-3 animate-fadeIn">
        <div class="text-xs font-bold text-white flex items-center justify-between">
          <span>Customize Dashboard Widgets</span>
          <span class="text-[10px] font-normal text-zinc-500">Changes saved automatically</span>
        </div>
        <div class="grid grid-cols-2 gap-2.5 text-xs text-zinc-300">
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showStatsWidget} onchange={saveWidgetPreferences} class="accent-amber-500 rounded" />
            <span>Library Stats Overview</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showHealthWidget} onchange={saveWidgetPreferences} class="accent-amber-500 rounded" />
            <span>Integration Health Status</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showAppleMusicWidget} onchange={saveWidgetPreferences} class="accent-amber-500 rounded" />
            <span>Apple Music Session</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showPlaylistsWidget} onchange={saveWidgetPreferences} class="accent-amber-500 rounded" />
            <span>Tracked Playlists</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showActivityWidget} onchange={saveWidgetPreferences} class="accent-amber-500 rounded" />
            <span>Recent Sync Activity</span>
          </label>
        </div>
      </div>
    {/if}

  {#if loading}
    <div class="flex flex-col gap-4">
      {#each [1,2,3] as _}
        <div class="h-20 rounded-xl bg-[#12100e] animate-pulse border border-[rgba(255,255,255,0.06)]"></div>
      {/each}
    </div>
  {:else if error}
    <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 text-red-400 text-sm">{error}</div>
  {:else if stats}

    <!-- Live Integration Health Card -->
    {#if showHealthWidget && integrationsHealth}
      <div class="border border-[rgba(255,255,255,0.08)] rounded-xl overflow-hidden mb-6 bg-[#12100e]">
        <div class="px-4 py-2.5 bg-[#171412] border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between">
          <span class="text-zinc-300 text-xs uppercase tracking-widest font-semibold flex items-center gap-1.5">
            <span>🔌</span> Integration Health & Ecosystem
          </span>
          {#if onopenSettings}
            <button onclick={onopenSettings} class="text-[11px] text-amber-400 hover:underline">
              Configure Settings &rarr;
            </button>
          {/if}
        </div>

        <div class="p-4 grid grid-cols-5 gap-3">
          <!-- Gemini AI -->
          <div class="p-3 rounded-lg bg-black/30 border border-zinc-800/80 flex flex-col items-center text-center space-y-1.5">
            <span class="text-lg">✨</span>
            <div class="text-xs font-semibold text-white">Gemini AI</div>
            <span class="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider {integrationsHealth.gemini ? 'bg-green-950/60 text-green-400 border border-green-500/30' : 'bg-zinc-800 text-zinc-500'}">
              {integrationsHealth.gemini ? "Connected" : "Unset"}
            </span>
          </div>

          <!-- Last.fm -->
          <div class="p-3 rounded-lg bg-black/30 border border-zinc-800/80 flex flex-col items-center text-center space-y-1.5">
            <span class="text-lg">📻</span>
            <div class="text-xs font-semibold text-white">Last.fm</div>
            <span class="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider {integrationsHealth.lastfm ? 'bg-green-950/60 text-green-400 border border-green-500/30' : 'bg-zinc-800 text-zinc-500'}">
              {integrationsHealth.lastfm ? "Connected" : "Unset"}
            </span>
          </div>

          <!-- Jellyfin -->
          <div class="p-3 rounded-lg bg-black/30 border border-zinc-800/80 flex flex-col items-center text-center space-y-1.5">
            <span class="text-lg">🍇</span>
            <div class="text-xs font-semibold text-white">Jellyfin</div>
            <span class="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider {integrationsHealth.jellyfin ? 'bg-green-950/60 text-green-400 border border-green-500/30' : 'bg-zinc-800 text-zinc-500'}">
              {integrationsHealth.jellyfin ? "Active" : "Disabled"}
            </span>
          </div>

          <!-- Navidrome -->
          <div class="p-3 rounded-lg bg-black/30 border border-zinc-800/80 flex flex-col items-center text-center space-y-1.5">
            <span class="text-lg">🚢</span>
            <div class="text-xs font-semibold text-white">Navidrome</div>
            <span class="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider {integrationsHealth.navidrome ? 'bg-green-950/60 text-green-400 border border-green-500/30' : 'bg-zinc-800 text-zinc-500'}">
              {integrationsHealth.navidrome ? "Active" : "Disabled"}
            </span>
          </div>

          <!-- Strawberry -->
          <div class="p-3 rounded-lg bg-black/30 border border-zinc-800/80 flex flex-col items-center text-center space-y-1.5">
            <span class="text-lg">🍓</span>
            <div class="text-xs font-semibold text-white">Strawberry</div>
            <span class="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider {integrationsHealth.strawberry ? 'bg-green-950/60 text-green-400 border border-green-500/30' : 'bg-zinc-800 text-zinc-500'}">
              {integrationsHealth.strawberry ? "Detected" : "Not Found"}
            </span>
          </div>
        </div>
      </div>
    {/if}

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

    <!-- Apple Music connection panel -->
    <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden mb-6">
      <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between">
        <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Apple Music</span>
        <span class="flex items-center gap-1.5 text-xs {wrapperRunning ? 'text-green-400' : 'text-zinc-600'}">
          <span class="w-1.5 h-1.5 rounded-full {wrapperRunning ? 'bg-green-500' : 'bg-zinc-600'}"></span>
          {wrapperRunning ? "Connected" : "Disconnected"}
        </span>
      </div>

      <div class="px-4 py-3">
        {#if wrapperRunning}
          <div class="flex items-center justify-between">
            <span class="text-sm text-zinc-400">Wrapper is running and ready for downloads.</span>
            <button onclick={stopWrapper} disabled={wrapperBusy}
              class="px-3 py-1.5 rounded-lg text-xs bg-[#1a1a1a] text-zinc-400 hover:text-red-400 hover:bg-red-950/30 transition-colors disabled:opacity-50">
              Disconnect
            </button>
          </div>

        {:else if wrapperNeeds2fa}
          <div class="flex flex-col gap-2">
            {#if wrapper2faType === "device"}
              <p class="text-sm text-amber-400">Apple sent a verification code to your trusted device — enter it below.</p>
            {:else}
              <p class="text-sm text-amber-400">Two-factor authentication required.</p>
            {/if}
            <div class="flex gap-2">
              <input bind:value={twoFaCode} type="text" placeholder="Enter 2FA code"
                class="flex-1 bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-700 rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors" />
              <button onclick={submit2fa} disabled={wrapperBusy || !twoFaCode}
                class="px-4 py-2 rounded-lg text-sm font-bold bg-amber-700 hover:bg-amber-600 text-white transition-colors disabled:opacity-50">
                Submit
              </button>
            </div>
          </div>

        {:else}
          <div class="flex flex-col gap-2">
            <div class="flex gap-2">
              <input bind:value={wrapperEmail} type="email" placeholder="Apple ID email"
                class="flex-1 bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-700 rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors" />
              <input bind:value={wrapperPassword} type="password" placeholder="Password"
                class="flex-1 bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-700 rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors" />
              <button onclick={loginWrapper} disabled={wrapperBusy || !wrapperEmail || !wrapperPassword}
                class="px-4 py-2 rounded-lg text-sm font-bold bg-amber-700 hover:bg-amber-600 text-white transition-colors disabled:opacity-50">
                {wrapperBusy ? "…" : "Connect"}
              </button>
            </div>
            {#if wrapperError}
              <p class="text-red-400 text-xs">{wrapperError}</p>
            {/if}
          </div>
        {/if}

        {#if wrapperLogs.length > 0}
          <div class="mt-2 bg-[#0a0a0a] border border-[#181818] rounded-lg px-3 py-2 max-h-24 overflow-y-auto">
            {#each wrapperLogs.slice(-10) as line}
              <div class="text-zinc-600 text-[10px] font-mono leading-relaxed">{line}</div>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    <!-- Stat cards -->
    <div class="grid grid-cols-3 gap-3 mb-6">
      <div class="bg-[#12100e] border border-[rgba(255,255,255,0.06)] rounded-xl px-4 py-4">
        <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Playlists</div>
        <div class="text-white text-3xl font-bold tracking-tight">{stats.playlist_count}</div>
        <div class="text-zinc-600 text-xs mt-1">tracked</div>
      </div>
      <div class="bg-[#12100e] border border-[rgba(255,255,255,0.06)] rounded-xl px-4 py-4">
        <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Tracks</div>
        <div class="text-white text-3xl font-bold tracking-tight">{stats.total_tracks.toLocaleString()}</div>
        <div class="text-zinc-600 text-xs mt-1">downloaded</div>
      </div>
      <div class="bg-[#12100e] border border-[rgba(255,255,255,0.06)] rounded-xl px-4 py-4">
        <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Last sync</div>
        <div class="text-white text-lg font-bold tracking-tight leading-tight mt-1">{formatDate(stats.last_sync)}</div>
      </div>
    </div>

    <!-- Playlist table -->
    {#if stats.playlists.length > 0}
      <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden mb-6">
        <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)]">
          <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Playlists</span>
        </div>
        <div class="divide-y divide-[#181818]">
          {#each stats.playlists as pl}
            <div class="flex items-center gap-3 px-4 py-3 hover:bg-[#12100e] transition-colors group">
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
      <div class="border border-[rgba(255,255,255,0.06)] rounded-xl px-6 py-10 text-center bg-[#12100e]">
        <div class="text-zinc-600 text-sm">No playlists added yet</div>
        <div class="text-zinc-700 text-xs mt-1">Add one from the sidebar to get started</div>
      </div>
    {/if}

    <!-- Recent sync runs -->
    <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden">
      <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)]">
        <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Recent Activity</span>
      </div>
      {#if recentRuns.length === 0}
        <div class="px-4 py-8 text-center">
          <div class="text-zinc-600 text-sm">No sync runs yet</div>
        </div>
      {:else}
        <div class="divide-y divide-[#181818]">
          {#each recentRuns as run}
            <div class="flex items-center gap-3 px-4 py-2.5">
              <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 {run.status === 'success' ? 'bg-green-500' : 'bg-red-500'}"></span>
              <div class="flex-1 min-w-0">
                <button onclick={() => onselectPlaylist(run.playlist_name)}
                  class="text-sm text-white font-medium hover:text-amber-400 transition-colors text-left truncate block max-w-[200px]">
                  {run.playlist_name}
                </button>
                {#if run.status === 'error' && run.error_message}
                  <div class="text-red-400 text-[10px] mt-0.5 truncate max-w-[280px]">{run.error_message}</div>
                {:else}
                  <div class="text-zinc-600 text-[10px] mt-0.5">
                    {run.new_count} new · {run.skipped_count} skipped
                    {#if run.error_count > 0}<span class="text-red-500"> · {run.error_count} errors</span>{/if}
                  </div>
                {/if}
              </div>
              <div class="text-right flex-shrink-0">
                <div class="text-zinc-500 text-xs">{formatDate(run.started_at)}</div>
                <div class="text-zinc-700 text-[10px] mt-0.5">{formatDuration(run.started_at, run.ended_at)}</div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>

  {/if}
  </div>
</div>
