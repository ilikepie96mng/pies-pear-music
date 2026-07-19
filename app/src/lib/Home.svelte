<script lang="ts">
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { onMount } from "svelte";
  import { api, type HomeData, type RecentTrack } from "../api";

  function appleMusicSearch(term: string): string {
    return `https://music.apple.com/us/search?term=${encodeURIComponent(term)}`;
  }

  function openExternal(event: MouseEvent, url: string) {
    event.preventDefault();
    void openUrl(url).catch(() => {});
  }

  interface Props {
    onopenSettings: () => void;
  }

  let { onopenSettings }: Props = $props();

  let data = $state<HomeData | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let profileMessage = $state<string | null>(null);
  let recommendationsLoading = $state(false);
  let hiddenArtistsOpen = $state(false);
  let hiddenArtists = $state<string[]>([]);

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

  async function exportLibraryProfile() {
    try {
      const profile = await api.libraryProfile();
      const url = URL.createObjectURL(new Blob([JSON.stringify(profile, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "pies-pear-music-library-profile.json";
      link.click();
      URL.revokeObjectURL(url);
      profileMessage = "Profile exported — it contains no file paths or credentials.";
    } catch {
      profileMessage = "Could not export the library profile.";
    }
  }

  async function hideRecommendation(artist: string) {
    try {
      await api.excludeRecommendationArtist(artist);
      if (data) data = { ...data, recommendations: data.recommendations.filter((rec) => rec.artist !== artist) };
    } catch {}
  }

  async function refreshRecommendations() {
    recommendationsLoading = true;
    try {
      data = await api.home();
    } catch {
      profileMessage = "Could not refresh recommendations.";
    } finally {
      recommendationsLoading = false;
    }
  }

  async function toggleHiddenArtists() {
    hiddenArtistsOpen = !hiddenArtistsOpen;
    if (hiddenArtistsOpen) hiddenArtists = await api.recommendationExclusions();
  }

  async function restoreRecommendation(artist: string) {
    await api.includeRecommendationArtist(artist);
    hiddenArtists = hiddenArtists.filter((item) => item !== artist);
  }
</script>

<div class="relative h-full overflow-y-auto">
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
        <div class="flex items-center gap-3">
          <button onclick={refreshRecommendations} disabled={recommendationsLoading} class="text-[10px] text-zinc-500 hover:text-amber-400 transition-colors disabled:opacity-40">{recommendationsLoading ? "Refreshing…" : "Refresh"}</button>
          <button onclick={toggleHiddenArtists} class="text-[10px] text-zinc-500 hover:text-amber-400 transition-colors">Hidden artists</button>
          <button onclick={exportLibraryProfile} class="text-[10px] text-zinc-500 hover:text-amber-400 transition-colors">Export profile</button>
          <span class="text-zinc-600 text-[10px]">{data.recommendation_source === "cached" ? "cached — offline" : "via Last.fm"}</span>
        </div>
      </div>
      {#if profileMessage}<div class="px-4 pt-3 text-[11px] text-zinc-500">{profileMessage}</div>{/if}
      {#if hiddenArtistsOpen}
        <div class="px-4 py-3 border-b border-[rgba(255,255,255,0.06)] bg-[#0e0d0c]">
          <div class="text-[10px] uppercase tracking-widest text-zinc-600 mb-2">Hidden artists</div>
          {#if hiddenArtists.length === 0}
            <div class="text-xs text-zinc-600">No hidden artists.</div>
          {:else}
            <div class="flex flex-wrap gap-2">
              {#each hiddenArtists as artist}
                <button onclick={() => restoreRecommendation(artist)} class="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-400 hover:text-white hover:border-zinc-600">{artist} ×</button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

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
        <div class="px-4 pt-3 text-[11px] text-zinc-600">Based on artists already in your library; Last.fm similar artists you own or hide are filtered out.</div>
        <div class="divide-y divide-[#181818]">
          {#each data.recommendations as rec}
            <div class="flex items-center gap-3 px-4 py-3">
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <a href={rec.lastfm_url} onclick={(event) => openExternal(event, rec.lastfm_url)}
                    class="text-sm text-white font-medium hover:text-[#c4b5fd] transition-colors truncate">
                    {rec.artist}
                  </a>
                  <a href={appleMusicSearch(rec.artist)} onclick={(event) => openExternal(event, appleMusicSearch(rec.artist))}
                    class="flex-shrink-0 text-[9px] text-zinc-600 hover:text-[#5eead4] transition-colors border border-zinc-800 hover:border-[#5eead4]/40 rounded px-1.5 py-0.5">
                    ♫ Apple Music
                  </a>
                </div>
                <div class="text-zinc-600 text-xs mt-0.5">{rec.reason}</div>
              </div>
              <div class="text-zinc-500 text-xs flex-shrink-0">{matchPct(rec.match)} match</div>
              <button onclick={() => hideRecommendation(rec.artist)} class="text-zinc-700 hover:text-zinc-300 text-xs" title="Hide this artist from recommendations" aria-label={`Hide ${rec.artist}`}>×</button>
            </div>
          {/each}
        </div>
      {/if}
    </div>

    <!-- Recommended Tracks -->
    {#if data.recommended_tracks && data.recommended_tracks.length > 0}
      <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden mt-4">
        <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between">
          <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Recommended Tracks</span>
          <span class="text-zinc-600 text-[10px]">via Last.fm</span>
        </div>
        <div class="divide-y divide-[#181818]">
          {#each data.recommended_tracks as track}
            <div class="flex items-center gap-3 px-4 py-2.5">
              <div class="flex-1 min-w-0">
                <a href={track.url} onclick={(event) => openExternal(event, track.url)}
                  class="text-sm text-white font-medium hover:text-[#fde68a] transition-colors truncate block">
                  {track.name}
                </a>
                <div class="text-zinc-600 text-xs mt-0.5">{track.artist}</div>
              </div>
              <a href={appleMusicSearch(`${track.name} ${track.artist}`)} onclick={(event) => openExternal(event, appleMusicSearch(`${track.name} ${track.artist}`))}
                class="flex-shrink-0 text-[9px] text-zinc-600 hover:text-[#5eead4] transition-colors border border-zinc-800 hover:border-[#5eead4]/40 rounded px-1.5 py-0.5">
                ♫ Apple Music
              </a>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Recommended Albums -->
    {#if data.recommended_albums && data.recommended_albums.length > 0}
      <div class="border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden mt-4 mb-6">
        <div class="px-4 py-2.5 bg-[#12100e] border-b border-[rgba(255,255,255,0.06)] flex items-center justify-between">
          <span class="text-zinc-400 text-xs uppercase tracking-widest font-semibold">Recommended Albums</span>
          <span class="text-zinc-600 text-[10px]">via Last.fm</span>
        </div>
        <div class="divide-y divide-[#181818]">
          {#each data.recommended_albums as album}
            <div class="flex items-center gap-3 px-4 py-2.5">
              {#if album.image_url}
                <img src={album.image_url} alt="" class="w-9 h-9 rounded flex-shrink-0 object-cover" />
              {:else}
                <div class="w-9 h-9 rounded flex-shrink-0 bg-[#1e1e1e]"></div>
              {/if}
              <div class="flex-1 min-w-0">
                <a href={album.url} onclick={(event) => openExternal(event, album.url)}
                  class="text-sm text-white font-medium hover:text-[#fde68a] transition-colors truncate block">
                  {album.name}
                </a>
                <div class="text-zinc-600 text-xs mt-0.5">{album.artist}</div>
              </div>
              <a href={appleMusicSearch(`${album.name} ${album.artist}`)} onclick={(event) => openExternal(event, appleMusicSearch(`${album.name} ${album.artist}`))}
                class="flex-shrink-0 text-[9px] text-zinc-600 hover:text-[#5eead4] transition-colors border border-zinc-800 hover:border-[#5eead4]/40 rounded px-1.5 py-0.5">
                ♫ Apple Music
              </a>
            </div>
          {/each}
        </div>
      </div>
    {/if}

  {/if}
  </div>
</div>

{#if runTracksOpen}
  <div role="dialog" aria-modal="true"
    onclick={e => { if (e.target === e.currentTarget) runTracksOpen = false; }}
    onkeydown={e => { if (e.key === 'Escape') runTracksOpen = false; }}
    tabindex="-1"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div role="document"
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
