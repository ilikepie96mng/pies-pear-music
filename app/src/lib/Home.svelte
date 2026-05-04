<script lang="ts">
  import { onMount } from "svelte";
  import { api, type HomeData } from "../api";

  interface Props {
    onopenSettings: () => void;
  }

  let { onopenSettings }: Props = $props();

  let data = $state<HomeData | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

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

<div class="p-8 max-w-2xl">
  <div class="mb-8">
    <h1 class="text-white text-2xl font-bold tracking-tight">Home</h1>
    <p class="text-zinc-500 text-sm mt-1">Your library at a glance</p>
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
          <span class="text-xs text-amber-500 font-semibold">+{data.last_sync.new_tracks} tracks</span>
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
            <div class="flex items-center gap-3 px-4 py-3">
              {#if track.artwork_url}
                <img
                  src={track.artwork_url.replace("{w}x{h}", "48x48bb")}
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
            </div>
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
