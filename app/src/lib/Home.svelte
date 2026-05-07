<script lang="ts">
  import { onMount } from "svelte";
  import { api, type HomeData, type RecentTrack } from "../api";

  interface Props {
    onopenSettings: () => void;
  }

  let { onopenSettings }: Props = $props();

  let data = $state<HomeData | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Modal state for "+N tracks" expansion
  let runTracksOpen = $state(false);
  let runTracksLoading = $state(false);
  let runTracks = $state<RecentTrack[]>([]);
  let runTracksError = $state<string | null>(null);

  async function openRunTracks() {
    if (!data?.last_sync) return;
    runTracksOpen = true;
    runTracksLoading = true;
    runTracksError = null;
    try {
      const r = await api.syncRunTracks(data.last_sync.run_id);
      runTracks = r.tracks;
    } catch (e) {
      runTracksError = String(e);
    } finally {
      runTracksLoading = false;
    }
  }

  async function reveal(track: RecentTrack) {
    try { await api.revealTrack(track.local_path); }
    catch (e) { console.error("reveal failed:", e); }
  }

  onMount(async () => {
    try {
      data = await api.home();
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
    const diffH = (now.getTime() - d.getTime()) / 3_600_000;
    if (diffH < 1) return "Less than an hour ago";
    if (diffH < 24) return `${Math.floor(diffH)}h ago`;
    if (diffH < 48) return "Yesterday";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function matchPct(match: number): string {
    return `${Math.round(match * 100)}%`;
  }
</script>

<div class="relative">
  <!-- Hero gradient backdrop (brighter, pastel) -->
  <div aria-hidden="true" class="pointer-events-none absolute inset-x-0 top-0 h-60"
    style="background:radial-gradient(ellipse at 20% 0%,rgba(252,211,77,0.5) 0%,rgba(196,181,253,0.42) 38%,rgba(94,234,212,0.28) 70%,transparent 100%);"></div>
  <div aria-hidden="true" class="pointer-events-none absolute inset-x-0 top-0 h-60"
    style="background:linear-gradient(180deg,transparent 55%,var(--bg) 100%);"></div>

  <div class="relative p-6 pt-5 max-w-3xl">
    <div class="mb-6">
      <div class="text-[#fde68a] text-[10px] font-bold tracking-[0.18em] uppercase mb-1.5">Welcome back</div>
      <h1 class="text-white text-3xl font-extrabold tracking-tight leading-none"
        style="background:linear-gradient(135deg,#fff 0%,#fde68a 50%,#c4b5fd 100%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">Home</h1>
      <p class="text-zinc-400 text-xs mt-2">Your library at a glance</p>
    </div>

  {#if loading}
    <div class="flex flex-col gap-4">
      {#each [1,2,3] as _}
        <div class="h-20 rounded-xl bg-[#12100e] animate-pulse border border-[rgba(255,255,255,0.06)]"></div>
      {/each}
    </div>

  {:else if error}
    <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 text-red-400 text-sm">{error}</div>

  {:else if data}

    <!-- Last sync strip -->
    {#if data.last_sync}
      <div class="rounded-xl px-4 py-3 mb-6 flex items-center justify-between border bg-[#12100e] border-[rgba(255,255,255,0.06)]">
        <div class="text-sm text-zinc-400">
          Last sync: <span class="text-white font-medium">{data.last_sync.playlist_name}</span>
          <span class="text-zinc-600 ml-2">{formatDate(data.last_sync.synced_at)}</span>
        </div>
        {#if data.last_sync.new_tracks > 0}
          <button onclick={openRunTracks}
            class="text-xs text-amber-500 font-semibold hover:text-amber-400 hover:underline transition-colors cursor-pointer">
            +{data.last_sync.new_tracks} tracks
          </button>
        {/if}
      </div>
    {/if}

    <!-- Recently added tracks -->
    <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden mb-6">
      <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)]">
        <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Recently Added</span>
      </div>
      {#if data.recent_tracks.length === 0}
        <div class="px-4 py-8 text-center">
          <div class="text-zinc-600 text-sm">No tracks yet</div>
          <div class="text-zinc-700 text-xs mt-1">Sync a playlist to get started</div>
        </div>
      {:else}
        <div class="divide-y divide-[#181818]">
          {#each data.recent_tracks as track}
            <button type="button" onclick={() => reveal(track)}
              class="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-amber-500/5 transition-colors cursor-pointer"
              title="Show file in file manager">
              {#if track.artwork_url}
                <img
                  src={track.artwork_url.replace("{w}x{h}", "96x96")}
                  alt=""
                  class="w-9 h-9 rounded flex-shrink-0 object-cover"
                  onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                />
              {:else}
                <div class="w-9 h-9 rounded flex-shrink-0 bg-[#1e1e1e]"></div>
              {/if}
              <div class="flex-1 min-w-0">
                <div class="text-sm text-white font-medium truncate">{track.title}</div>
                <div class="text-zinc-500 text-xs truncate">{track.artist} — {track.album}</div>
              </div>
              <div class="text-zinc-600 text-xs flex-shrink-0">{formatDate(track.downloaded_at)}</div>
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- Recommendations -->
    <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden">
      <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between">
        <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Recommended Artists</span>
        <span class="text-zinc-600 text-[10px]">via Last.fm</span>
      </div>

      {#if !data.recommendations_available}
        <div class="px-4 py-6 text-center">
          <div class="text-zinc-500 text-sm">Add a Last.fm API key to get recommendations</div>
          <button
            onclick={onopenSettings}
            class="mt-3 text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-amber-500 hover:text-amber-400 hover:bg-[#222] transition-colors">
            Open Settings →
          </button>
        </div>

      {:else if data.recommendations.length === 0}
        <div class="px-4 py-8 text-center">
          <div class="text-zinc-600 text-sm">No recommendations yet</div>
          <div class="text-zinc-700 text-xs mt-1">Sync some playlists to build your artist profile</div>
        </div>

      {:else}
        <div class="divide-y divide-[#181818]">
          {#each data.recommendations as rec}
            <div class="flex items-center gap-3 px-4 py-3">
              <div class="flex-1 min-w-0">
                <a
                  href={rec.lastfm_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-sm text-white font-medium hover:text-amber-400 transition-colors truncate block">
                  {rec.artist}
                </a>
                <div class="text-zinc-600 text-xs mt-0.5">Similar to {rec.similar_to}</div>
              </div>
              <div class="text-zinc-500 text-xs flex-shrink-0">{matchPct(rec.match)} match</div>
            </div>
          {/each}
        </div>
      {/if}
    </div>

  {/if}
  </div>
</div>

{#if runTracksOpen}
  <div role="dialog" aria-modal="true"
    onclick={() => (runTracksOpen = false)}
    onkeydown={e => { if (e.key === 'Escape') runTracksOpen = false; }}
    tabindex="-1"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div onclick={e => e.stopPropagation()} role="document"
      class="w-[min(640px,90vw)] max-h-[80vh] flex flex-col rounded-2xl border border-[rgba(255,255,255,0.08)] bg-[#0e0c0a] shadow-2xl overflow-hidden">
      <div class="flex items-center justify-between px-5 py-3 border-b border-[rgba(255,255,255,0.06)]">
        <div>
          <div class="text-amber-500 text-[10px] font-bold tracking-[0.18em] uppercase">Last Sync</div>
          <div class="text-white font-semibold mt-0.5">{data?.last_sync?.playlist_name ?? ""} — {data?.last_sync?.new_tracks ?? 0} new tracks</div>
        </div>
        <button onclick={() => (runTracksOpen = false)} class="text-zinc-500 hover:text-white text-lg leading-none w-8 h-8 rounded-full hover:bg-white/5 transition-colors">×</button>
      </div>
      <div class="flex-1 overflow-y-auto">
        {#if runTracksLoading}
          <div class="px-5 py-10 text-center text-zinc-500 text-sm">Loading…</div>
        {:else if runTracksError}
          <div class="px-5 py-6 text-red-400 text-sm">{runTracksError}</div>
        {:else if runTracks.length === 0}
          <div class="px-5 py-10 text-center text-zinc-500 text-sm">No tracks in this run</div>
        {:else}
          <div class="divide-y divide-[#181818]">
            {#each runTracks as track}
              <button type="button" onclick={() => reveal(track)}
                class="w-full text-left flex items-center gap-3 px-5 py-2.5 hover:bg-amber-500/5 transition-colors cursor-pointer"
                title="Show file in file manager">
                {#if track.artwork_url}
                  <img src={track.artwork_url.replace("{w}x{h}", "96x96")} alt=""
                    class="w-9 h-9 rounded flex-shrink-0 object-cover"
                    onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                {:else}
                  <div class="w-9 h-9 rounded flex-shrink-0 bg-[#1e1e1e]"></div>
                {/if}
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-white font-medium truncate">{track.title}</div>
                  <div class="text-zinc-500 text-xs truncate">{track.artist} — {track.album}</div>
                </div>
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}
