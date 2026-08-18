<script lang="ts">
  import { onMount } from "svelte";
  import { save as saveDialog } from "@tauri-apps/plugin-dialog";
  import { api, type LibraryTrack, type Playlist, type GeminiPlaylistResult } from "../api";
  import { player } from "./player.svelte";

  interface Props {
    onplaylistSaved?: (pl: Playlist) => void;
    onopenDownload?: () => void;
  }

  let { onplaylistSaved, onopenDownload }: Props = $props();

  // State
  let loading = $state(true);
  let allTracks = $state<LibraryTrack[]>([]);
  let playlists = $state<Playlist[]>([]);
  let playlistTrackMap = $state<Record<string, LibraryTrack[]>>({});

  // Browser Tabs & Filter
  type CatalogTab = "tracks" | "albums" | "artists" | "playlists" | "ai";
  let activeTab = $state<CatalogTab>("tracks");
  let searchQuery = $state("");
  let selectedCatalogItems = $state<Set<string>>(new Set());

  // AI Assistant State
  let aiPrompt = $state("");
  let aiTargetCount = $state(20);
  let aiLibraryOnly = $state(false);
  let aiCurating = $state(false);
  let aiError = $state<string | null>(null);
  let aiResult = $state<GeminiPlaylistResult | null>(null);
  let aiDownloadingBatch = $state(false);
  let aiDownloadMessage = $state<string | null>(null);

  // Staged Playlist
  let playlistName = $state("");
  let playlistDescription = $state("");
  let stagedTracks = $state<LibraryTrack[]>([]);
  let duplicateWarning = $state<string | null>(null);

  // Saving / Exporting
  let saving = $state(false);
  let saveSuccess = $state(false);
  let saveError = $state<string | null>(null);

  // 60fps Virtual Scrolling for Catalog Tracks
  let trackContainerEl = $state<HTMLDivElement | null>(null);
  let trackScrollTop = $state(0);
  let trackViewportHeight = $state(600);
  const trackRowHeight = 52;
  const trackBuffer = 8;

  onMount(async () => {
    if (trackContainerEl) {
      trackViewportHeight = trackContainerEl.clientHeight;
      const ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
          trackViewportHeight = entry.contentRect.height;
        }
      });
      ro.observe(trackContainerEl);
    }
    loading = true;
    try {
      const [trackList, plList, libMap] = await Promise.all([
        api.allLibraryTracks(),
        api.playlists(),
        api.library(),
      ]);
      allTracks = trackList;
      playlists = plList;
      playlistTrackMap = libMap as Record<string, LibraryTrack[]>;
    } catch (e) {
      console.error("Failed to load catalog for playlist creator:", e);
    } finally {
      loading = false;
    }
  });

  // Derived Catalog aggregations
  let filteredTracks = $derived(() => {
    if (!searchQuery.trim()) return allTracks;
    const q = searchQuery.toLowerCase();
    return allTracks.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        t.album.toLowerCase().includes(q),
    );
  });

  let currentTracksList = $derived(filteredTracks());
  let totalTrackListHeight = $derived(currentTracksList.length * trackRowHeight);
  let trackStartIndex = $derived(Math.max(0, Math.floor(trackScrollTop / trackRowHeight) - trackBuffer));
  let trackEndIndex = $derived(Math.min(currentTracksList.length, Math.ceil((trackScrollTop + trackViewportHeight) / trackRowHeight) + trackBuffer));
  let visibleTrackSlice = $derived(
    currentTracksList.slice(trackStartIndex, trackEndIndex).map((track, i) => ({
      track,
      top: (trackStartIndex + i) * trackRowHeight,
    }))
  );

  let albumGroups = $derived(() => {
    const map = new Map<string, { artist: string; album: string; tracks: LibraryTrack[]; artwork_url?: string | null }>();
    for (const t of allTracks) {
      const key = `${t.artist} — ${t.album}`;
      if (!map.has(key)) {
        map.set(key, { artist: t.artist, album: t.album, tracks: [], artwork_url: t.artwork_url });
      }
      map.get(key)!.tracks.push(t);
    }
    let list = Array.from(map.values());
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (a) => a.album.toLowerCase().includes(q) || a.artist.toLowerCase().includes(q),
      );
    }
    return list.sort((a, b) => a.album.localeCompare(b.album));
  });

  let artistGroups = $derived(() => {
    const map = new Map<string, { artist: string; tracks: LibraryTrack[]; albums: Set<string> }>();
    for (const t of allTracks) {
      if (!map.has(t.artist)) {
        map.set(t.artist, { artist: t.artist, tracks: [], albums: new Set() });
      }
      const item = map.get(t.artist)!;
      item.tracks.push(t);
      item.albums.add(t.album);
    }
    let list = Array.from(map.values());
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter((a) => a.artist.toLowerCase().includes(q));
    }
    return list.sort((a, b) => a.artist.localeCompare(b.artist));
  });

  let filteredPlaylists = $derived(() => {
    if (!searchQuery.trim()) return playlists;
    const q = searchQuery.toLowerCase();
    return playlists.filter((p) => p.name.toLowerCase().includes(q));
  });

  // Staged Summary calculations
  let totalDurationSeconds = $derived(() => {
    return stagedTracks.length * 210; // estimate 3.5 min avg
  });

  let totalSizeMB = $derived(() => {
    const bytes = stagedTracks.reduce((acc, t) => acc + (t.file_size || 35_000_000), 0);
    return (bytes / (1024 * 1024)).toFixed(1);
  });

  function formatTime(secs: number): string {
    const m = Math.floor(secs / 60);
    const h = Math.floor(m / 60);
    const remM = m % 60;
    if (h > 0) return `${h} hr ${remM} min`;
    return `${m} min`;
  }

  // Selection & Staging Actions
  function toggleItemSelection(id: string) {
    const next = new Set(selectedCatalogItems);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedCatalogItems = next;
  }

  function selectAllFiltered() {
    const next = new Set(selectedCatalogItems);
    if (activeTab === "tracks") {
      filteredTracks().forEach((t) => next.add(t.track_id));
    } else if (activeTab === "albums") {
      albumGroups().forEach((a) => next.add(`${a.artist} — ${a.album}`));
    } else if (activeTab === "artists") {
      artistGroups().forEach((a) => next.add(a.artist));
    } else if (activeTab === "playlists") {
      filteredPlaylists().forEach((p) => next.add(p.name));
    }
    selectedCatalogItems = next;
  }

  function clearSelection() {
    selectedCatalogItems = new Set();
  }

  function addSelectedToStaged(allowDuplicates = true) {
    duplicateWarning = null;
    let tracksToAdd: LibraryTrack[] = [];

    if (activeTab === "tracks") {
      tracksToAdd = allTracks.filter((t) => selectedCatalogItems.has(t.track_id));
    } else if (activeTab === "albums") {
      for (const a of albumGroups()) {
        if (selectedCatalogItems.has(`${a.artist} — ${a.album}`)) {
          tracksToAdd.push(...a.tracks);
        }
      }
    } else if (activeTab === "artists") {
      for (const a of artistGroups()) {
        if (selectedCatalogItems.has(a.artist)) {
          tracksToAdd.push(...a.tracks);
        }
      }
    } else if (activeTab === "playlists") {
      for (const p of playlists) {
        if (selectedCatalogItems.has(p.name)) {
          tracksToAdd.push(...(playlistTrackMap[p.name] || []));
        }
      }
    }

    if (tracksToAdd.length === 0) return;

    // Check for duplicates with already staged tracks
    const currentTrackIds = new Set(stagedTracks.map((t) => t.track_id));
    const duplicates = tracksToAdd.filter((t) => currentTrackIds.has(t.track_id));

    if (duplicates.length > 0 && !allowDuplicates) {
      tracksToAdd = tracksToAdd.filter((t) => !currentTrackIds.has(t.track_id));
      duplicateWarning = `Skipped ${duplicates.length} duplicate track(s). Added ${tracksToAdd.length} new track(s).`;
    } else if (duplicates.length > 0 && allowDuplicates) {
      duplicateWarning = `${duplicates.length} of the added tracks were already in the playlist.`;
    }

    stagedTracks = [...stagedTracks, ...tracksToAdd];
    clearSelection();
  }

  function addSingleTrack(track: LibraryTrack) {
    if (stagedTracks.some((t) => t.track_id === track.track_id)) {
      duplicateWarning = `"${track.title}" is already staged. Added anyway.`;
    }
    stagedTracks = [...stagedTracks, track];
  }

  function removeStagedTrack(index: number) {
    stagedTracks = stagedTracks.filter((_, i) => i !== index);
  }

  function moveTrack(index: number, direction: "up" | "down") {
    if (direction === "up" && index > 0) {
      const next = [...stagedTracks];
      const temp = next[index - 1];
      next[index - 1] = next[index];
      next[index] = temp;
      stagedTracks = next;
    } else if (direction === "down" && index < stagedTracks.length - 1) {
      const next = [...stagedTracks];
      const temp = next[index + 1];
      next[index + 1] = next[index];
      next[index] = temp;
      stagedTracks = next;
    }
  }

  function clearStaged() {
    stagedTracks = [];
    duplicateWarning = null;
    saveSuccess = false;
  }

  // Export & Save Actions
  async function handleSavePlaylist() {
    if (!playlistName.trim()) {
      saveError = "Please enter a playlist name";
      return;
    }
    if (stagedTracks.length === 0) {
      saveError = "Please add at least one track to the playlist";
      return;
    }

    saving = true;
    saveError = null;
    try {
      const name = playlistName.trim();
      const res = await api.saveGeminiPlaylist(
        name,
        stagedTracks.map((t) => ({ track_id: t.track_id })),
        playlistDescription.trim() || "Created in Playlist Workstation",
      );
      saveSuccess = true;
      if (onplaylistSaved) onplaylistSaved(res);
      setTimeout(() => {
        saveSuccess = false;
      }, 3000);
    } catch (e) {
      saveError = e instanceof Error ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

  async function handleCurateAi() {
    if (!aiPrompt.trim()) return;
    aiCurating = true;
    aiError = null;
    aiResult = null;
    aiDownloadMessage = null;
    try {
      const res = await api.curateGemini(aiPrompt.trim(), aiTargetCount, undefined, aiLibraryOnly);
      aiResult = res;
    } catch (e) {
      aiError = e instanceof Error ? e.message : String(e);
    } finally {
      aiCurating = false;
    }
  }

  async function handleAiDownloadMissing() {
    if (!aiResult || !aiResult.tracks) return;
    const missing = aiResult.tracks.filter((t) => !t.in_library);
    if (missing.length === 0) return;

    aiDownloadingBatch = true;
    try {
      const res = await api.downloadGeminiTracks(missing);
      aiDownloadMessage = `Queued ${res.queued} track(s) for download!`;
    } catch (e) {
      aiError = `Download failed: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      aiDownloadingBatch = false;
    }
  }

  function stageAiTracks() {
    if (!aiResult) return;
    if (aiResult.playlist_title && !playlistName.trim()) {
      playlistName = aiResult.playlist_title;
    }
    if (aiResult.description && !playlistDescription.trim()) {
      playlistDescription = aiResult.description;
    }

    const mapped: LibraryTrack[] = [];
    for (const item of aiResult.tracks) {
      const match = allTracks.find(
        (t) =>
          t.title.toLowerCase() === item.title.toLowerCase() ||
          (t.title.toLowerCase().includes(item.title.toLowerCase()) &&
            t.artist.toLowerCase().includes(item.artist.toLowerCase())),
      );

      if (match) {
        mapped.push(match);
      } else {
        mapped.push({
          track_id: item.am_track?.id || `ai-${item.artist}-${item.title}`,
          title: item.title,
          artist: item.artist,
          album: item.album || "AI Curated",
          local_path: "",
          downloaded_at: "",
          artwork_url: null,
          playlists: [],
          has_lyrics: false,
          format: "ALAC",
          file_size: 35_000_000,
          exists_on_disk: false,
        });
      }
    }

    if (mapped.length > 0) {
      stagedTracks = [...stagedTracks, ...mapped];
    }
  }

  async function handleExportM3U8() {
    if (stagedTracks.length === 0) return;
    const lines = ["#EXTM3U", ""];
    for (const t of stagedTracks) {
      lines.push(`#EXTINF:-1,${t.artist} - ${t.title}`);
      lines.push(t.local_path);
    }
    const content = lines.join("\n") + "\n";
    const defaultFilename = `${playlistName.trim() || "staged-playlist"}.m3u8`;

    try {
      const filePath = await saveDialog({
        defaultPath: defaultFilename,
        filters: [{ name: "M3U8 Playlist", extensions: ["m3u8", "m3u"] }],
      });
      if (filePath) {
        // Save via server or blob fallback
        const blob = new Blob([content], { type: "audio/x-mpegurl" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filePath.split(/[/\\]/).pop() || defaultFilename;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      // Fallback to direct download
      const blob = new Blob([content], { type: "audio/x-mpegurl" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = defaultFilename;
      a.click();
      URL.revokeObjectURL(url);
    }
  }

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }
</script>

<div class="h-full flex flex-col overflow-hidden" style="background:var(--bg);color:var(--text-primary);">
  <!-- Top Header -->
  <div class="p-6 border-b flex items-center justify-between flex-shrink-0" style="border-color:var(--border);background:var(--surface);">
    <div class="space-y-1">
      <div class="flex items-center gap-2.5">
        <span class="text-xl">🔀</span>
        <h1 class="text-xl font-bold tracking-tight text-white">Playlist Creator Workstation</h1>
        <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 uppercase tracking-wider">
          Supercharged
        </span>
      </div>
      <p class="text-xs text-zinc-400">
        Stage, reorder, mix and match albums, artists, and existing playlists with duplicate guards.
      </p>
    </div>

    <!-- Actions Bar -->
    <div class="flex items-center gap-3">
      {#if saveSuccess}
        <span class="text-xs font-semibold text-green-400 bg-green-950/40 border border-green-500/30 px-3 py-1.5 rounded-lg flex items-center gap-1.5">
          <span>✓</span> Saved to Library!
        </span>
      {/if}
      <button
        onclick={handleExportM3U8}
        disabled={stagedTracks.length === 0}
        class="px-3.5 py-1.5 rounded-lg text-xs font-semibold border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 disabled:opacity-40 transition-colors flex items-center gap-1.5"
      >
        <span>⬇️</span> Export .M3U8
      </button>
      <button
        onclick={handleSavePlaylist}
        disabled={saving || stagedTracks.length === 0}
        class="px-4 py-1.5 rounded-lg text-xs font-bold bg-amber-500 hover:bg-amber-400 text-black shadow-lg disabled:opacity-40 transition-all flex items-center gap-1.5"
      >
        <span>💾</span> {saving ? "Saving…" : "Save to Library"}
      </button>
    </div>
  </div>

  {#if saveError}
    <div class="px-6 py-2 bg-red-950/40 border-b border-red-500/30 text-red-400 text-xs flex items-center justify-between">
      <span>{saveError}</span>
      <button onclick={() => (saveError = null)} class="text-red-400 hover:text-white">✕</button>
    </div>
  {/if}

  <!-- Split Pane Body -->
  <div class="flex-1 flex overflow-hidden">
    <!-- LEFT PANE: Library Catalog Browser -->
    <div class="w-1/2 border-r flex flex-col overflow-hidden" style="border-color:var(--border);">
      <!-- Catalog Tabs & Search -->
      <div class="p-4 border-b space-y-3 flex-shrink-0" style="border-color:var(--border);background:#12100e;">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 bg-black/40 p-1 rounded-lg border border-zinc-800">
            {#each [
              { id: "tracks", label: "Tracks", icon: "♫" },
              { id: "albums", label: "Albums", icon: "💿" },
              { id: "artists", label: "Artists", icon: "👤" },
              { id: "playlists", label: "Playlists", icon: "📋" },
              { id: "ai", label: "AI Assistant", icon: "✨" },
            ] as tab}
              <button
                onclick={() => { activeTab = tab.id as CatalogTab; clearSelection(); }}
                class="px-2.5 py-1 rounded text-xs font-medium transition-all {activeTab === tab.id ? 'bg-amber-400 text-black font-bold shadow' : 'text-zinc-400 hover:text-zinc-200'}"
              >
                <span class="mr-1">{tab.icon}</span>{tab.label}
              </button>
            {/each}
          </div>

          <div class="text-[11px] text-zinc-500 font-mono">
            {allTracks.length} tracks cataloged
          </div>
        </div>

        <div class="flex items-center gap-2">
          <div class="relative flex-1">
            <input
              type="text"
              bind:value={searchQuery}
              placeholder={`Search ${activeTab}…`}
              class="w-full bg-[#1c1917] border border-zinc-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-zinc-500 outline-none focus:border-amber-500"
            />
            <span class="absolute left-2.5 top-2 text-xs text-zinc-500">🔍</span>
          </div>
          {#if selectedCatalogItems.size > 0}
            <button
              onclick={clearSelection}
              class="text-xs text-zinc-400 hover:text-white px-2 py-1"
            >
              Clear ({selectedCatalogItems.size})
            </button>
          {/if}
          <button
            onclick={selectAllFiltered}
            class="text-xs text-amber-400 hover:text-amber-300 font-medium px-2 py-1"
          >
            Select All
          </button>
        </div>
      </div>

      <!-- Selection Batch Bar -->
      {#if selectedCatalogItems.size > 0}
        <div class="px-4 py-2 bg-amber-950/30 border-b border-amber-500/30 flex items-center justify-between flex-shrink-0 animate-fadeIn">
          <span class="text-xs font-semibold text-amber-200">
            {selectedCatalogItems.size} {activeTab} selected
          </span>
          <div class="flex items-center gap-2">
            <button
              onclick={() => addSelectedToStaged(false)}
              class="px-2.5 py-1 rounded text-xs font-medium bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
            >
              Skip Duplicates & Add
            </button>
            <button
              onclick={() => addSelectedToStaged(true)}
              class="px-3 py-1 rounded text-xs font-bold bg-amber-500 hover:bg-amber-400 text-black shadow"
            >
              + Stage Selected
            </button>
          </div>
        </div>
      {/if}

      <!-- Catalog List -->
      {#if loading}
        <div class="flex-1 flex items-center justify-center text-xs text-zinc-500">
          Loading library tracks…
        </div>
      {:else if activeTab === "tracks"}
        <div
          bind:this={trackContainerEl}
          onscroll={(e) => (trackScrollTop = (e.currentTarget as HTMLDivElement).scrollTop)}
          class="flex-1 overflow-y-auto p-4 relative"
        >
          <div style="height: {totalTrackListHeight}px; position: relative; width: 100%;">
            {#each visibleTrackSlice as item (item.track.track_id)}
              {@const track = item.track}
              {@const isSelected = selectedCatalogItems.has(track.track_id)}
              <div
                role="button"
                tabindex="0"
                style="position: absolute; top: {item.top}px; left: 0; right: 0; height: 48px;"
                class="group flex items-center justify-between px-3 py-1.5 rounded-lg border transition-all cursor-pointer {isSelected ? 'bg-amber-950/20 border-amber-500/40' : 'bg-black/20 border-zinc-800/60 hover:border-zinc-700'}"
                onclick={() => toggleItemSelection(track.track_id)}
                onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleItemSelection(track.track_id); } }}
              >
                <div class="flex items-center gap-3 min-w-0 flex-1">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    class="accent-amber-500 rounded"
                    onclick={(e) => e.stopPropagation()}
                    onchange={() => toggleItemSelection(track.track_id)}
                  />
                  {#if track.artwork_url}
                    <img
                      src={thumbUrl(track.artwork_url, "64x64")}
                      alt=""
                      class="w-8 h-8 rounded object-cover flex-shrink-0 bg-zinc-900"
                    />
                  {:else}
                    <div class="w-8 h-8 rounded bg-zinc-800 flex items-center justify-center text-xs text-zinc-500 flex-shrink-0">
                      ♫
                    </div>
                  {/if}
                  <div class="min-w-0 flex-1">
                    <div class="text-xs font-semibold text-white truncate">{track.title}</div>
                    <div class="text-[11px] text-zinc-400 truncate">{track.artist} &middot; {track.album}</div>
                  </div>
                </div>

                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    onclick={(e) => { e.stopPropagation(); addSingleTrack(track); }}
                    class="px-2 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-amber-500 hover:text-black text-zinc-300 opacity-0 group-hover:opacity-100 transition-all"
                    title="Stage single track"
                  >
                    + Add
                  </button>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {:else}
        <div class="flex-1 overflow-y-auto p-4 space-y-1">
          {#if activeTab === "albums"}
            {#each albumGroups() as album}
            {@const id = `${album.artist} — ${album.album}`}
            {@const isSelected = selectedCatalogItems.has(id)}
            <div
              role="button"
              tabindex="0"
              class="group flex items-center justify-between p-2.5 rounded-lg border transition-all cursor-pointer {isSelected ? 'bg-amber-950/20 border-amber-500/40' : 'bg-black/20 border-zinc-800/60 hover:border-zinc-700'}"
              onclick={() => toggleItemSelection(id)}
              onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleItemSelection(id); } }}
            >
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <input
                  type="checkbox"
                  checked={isSelected}
                  class="accent-amber-500 rounded"
                  onclick={(e) => e.stopPropagation()}
                  onchange={() => toggleItemSelection(id)}
                />
                {#if album.artwork_url}
                  <img
                    src={thumbUrl(album.artwork_url, "64x64")}
                    alt=""
                    class="w-10 h-10 rounded object-cover flex-shrink-0 bg-zinc-900"
                  />
                {:else}
                  <div class="w-10 h-10 rounded bg-zinc-800 flex items-center justify-center text-sm text-zinc-500 flex-shrink-0">
                    💿
                  </div>
                {/if}
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-semibold text-white truncate">{album.album}</div>
                  <div class="text-[11px] text-zinc-400 truncate">{album.artist} &middot; {album.tracks.length} tracks</div>
                </div>
              </div>
              <button
                type="button"
                onclick={(e) => { e.stopPropagation(); stagedTracks = [...stagedTracks, ...album.tracks]; }}
                class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-amber-500 hover:text-black text-zinc-300 opacity-0 group-hover:opacity-100 transition-all"
              >
                + Add Album ({album.tracks.length})
              </button>
            </div>
          {/each}
        {:else if activeTab === "artists"}
          {#each artistGroups() as artist}
            {@const isSelected = selectedCatalogItems.has(artist.artist)}
            <div
              role="button"
              tabindex="0"
              class="group flex items-center justify-between p-2.5 rounded-lg border transition-all cursor-pointer {isSelected ? 'bg-amber-950/20 border-amber-500/40' : 'bg-black/20 border-zinc-800/60 hover:border-zinc-700'}"
              onclick={() => toggleItemSelection(artist.artist)}
              onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleItemSelection(artist.artist); } }}
            >
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <input
                  type="checkbox"
                  checked={isSelected}
                  class="accent-amber-500 rounded"
                  onclick={(e) => e.stopPropagation()}
                  onchange={() => toggleItemSelection(artist.artist)}
                />
                <div class="w-9 h-9 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-xs text-zinc-400 flex-shrink-0">
                  👤
                </div>
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-semibold text-white truncate">{artist.artist}</div>
                  <div class="text-[11px] text-zinc-400 truncate">{artist.albums.size} albums &middot; {artist.tracks.length} tracks</div>
                </div>
              </div>
              <button
                type="button"
                onclick={(e) => { e.stopPropagation(); stagedTracks = [...stagedTracks, ...artist.tracks]; }}
                class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-amber-500 hover:text-black text-zinc-300 opacity-0 group-hover:opacity-100 transition-all"
              >
                + Add All ({artist.tracks.length})
              </button>
            </div>
          {/each}
        {:else if activeTab === "playlists"}
          {#each filteredPlaylists() as pl}
            {@const count = (playlistTrackMap[pl.name] || []).length}
            {@const isSelected = selectedCatalogItems.has(pl.name)}
            <div
              role="button"
              tabindex="0"
              class="group flex items-center justify-between p-2.5 rounded-lg border transition-all cursor-pointer {isSelected ? 'bg-amber-950/20 border-amber-500/40' : 'bg-black/20 border-zinc-800/60 hover:border-zinc-700'}"
              onclick={() => toggleItemSelection(pl.name)}
              onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleItemSelection(pl.name); } }}
            >
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <input
                  type="checkbox"
                  checked={isSelected}
                  class="accent-amber-500 rounded"
                  onclick={(e) => e.stopPropagation()}
                  onchange={() => toggleItemSelection(pl.name)}
                />
                <div class="w-9 h-9 rounded-lg bg-zinc-800 border border-zinc-700 flex items-center justify-center text-xs text-zinc-400 flex-shrink-0">
                  📋
                </div>
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-semibold text-white truncate">{pl.name}</div>
                  <div class="text-[11px] text-zinc-400 truncate">{count} tracks &middot; Library playlist</div>
                </div>
              </div>
              <button
                type="button"
                onclick={(e) => { e.stopPropagation(); stagedTracks = [...stagedTracks, ...(playlistTrackMap[pl.name] || [])]; }}
                class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-amber-500 hover:text-black text-zinc-300 opacity-0 group-hover:opacity-100 transition-all"
              >
                + Merge All ({count})
              </button>
            </div>
          {/each}
        {:else if activeTab === "ai"}
          <div class="p-4 space-y-4">
            <div class="space-y-1.5">
              <label for="ai-prompt-input" class="text-xs font-bold text-white flex items-center gap-1.5">
                <span>✨</span> Gemini AI Mix Prompt
              </label>
              <textarea
                id="ai-prompt-input"
                bind:value={aiPrompt}
                rows={3}
                placeholder="Describe your desired vibe or mix (e.g., 'Late night chill electronic and downtempo beats with warm bass')..."
                class="w-full bg-[#1c1917] border border-zinc-800 rounded-lg p-3 text-xs text-white placeholder-zinc-500 outline-none focus:border-amber-500 resize-none"
              ></textarea>
            </div>

            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <label class="flex items-center gap-1.5 text-xs font-semibold text-amber-300 cursor-pointer bg-amber-400/10 px-2.5 py-1 rounded border border-amber-400/30 hover:bg-amber-400/20 transition-colors">
                  <input
                    type="checkbox"
                    bind:checked={aiLibraryOnly}
                    class="accent-amber-400 rounded"
                  />
                  <span>📚 Library Only</span>
                </label>

                <div class="flex items-center gap-2">
                  <span class="text-xs text-zinc-400">Target tracks:</span>
                  <input
                    type="number"
                    bind:value={aiTargetCount}
                    min={5}
                    max={100}
                    class="w-16 bg-[#1c1917] border border-zinc-800 rounded px-2 py-1 text-xs text-white text-center"
                  />
                </div>
              </div>

              <button
                onclick={handleCurateAi}
                disabled={aiCurating || !aiPrompt.trim()}
                class="px-4 py-1.5 rounded-lg text-xs font-bold bg-amber-400 hover:bg-amber-300 text-black shadow disabled:opacity-40 transition-all"
              >
                {aiCurating ? "Generating Mix…" : "✨ Generate AI Mix"}
              </button>
            </div>

            {#if aiError}
              <div class="p-3 rounded-lg bg-red-950/40 border border-red-500/30 text-xs text-red-300">
                {aiError}
              </div>
            {/if}

            {#if aiDownloadMessage}
              <div class="p-2.5 rounded-lg bg-amber-950/40 border border-amber-500/30 text-amber-200 text-xs flex items-center justify-between">
                <span>{aiDownloadMessage}</span>
                <button onclick={() => (aiDownloadMessage = null)} class="text-xs text-zinc-400 hover:text-white">✕</button>
              </div>
            {/if}

            {#if aiResult}
              <div class="p-4 rounded-xl border border-zinc-800 bg-black/40 space-y-3">
                <div class="flex items-start justify-between gap-2">
                  <div>
                    <div class="text-sm font-bold text-white">{aiResult.playlist_title}</div>
                    <div class="text-xs text-zinc-400 mt-0.5">{aiResult.description}</div>
                  </div>
                  <div class="flex items-center gap-2 flex-shrink-0">
                    {#if aiResult.tracks.some((t) => !t.in_library)}
                      {@const missingCount = aiResult.tracks.filter((t) => !t.in_library).length}
                      <button
                        onclick={handleAiDownloadMissing}
                        disabled={aiDownloadingBatch}
                        class="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 shadow flex items-center gap-1 disabled:opacity-50"
                      >
                        {#if aiDownloadingBatch}
                          <span class="w-3 h-3 border-2 border-amber-300 border-t-transparent rounded-full animate-spin"></span>
                          <span>Queuing...</span>
                        {:else}
                          <span>⚡ Download ({missingCount})</span>
                        {/if}
                      </button>
                    {/if}
                    <button
                      onclick={stageAiTracks}
                      class="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-400 hover:bg-amber-300 text-black shadow flex items-center gap-1"
                    >
                      <span>+</span> Stage Mix ({aiResult.tracks.length})
                    </button>
                  </div>
                </div>

                <div class="space-y-1.5 max-h-60 overflow-y-auto pr-1">
                  {#each aiResult.tracks as track}
                    <div class="flex items-center justify-between p-2 rounded bg-zinc-900/60 border border-zinc-800 text-xs">
                      <div class="min-w-0 flex-1 pr-2">
                        <div class="font-semibold text-white truncate">{track.title}</div>
                        <div class="text-[11px] text-zinc-400 truncate">{track.artist} &middot; {track.album}</div>
                      </div>
                      {#if track.in_library}
                        <span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-green-950/60 text-green-400 border border-green-500/30">In Library</span>
                      {:else}
                        <span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-950/60 text-amber-400 border border-amber-500/30">AI Curated</span>
                      {/if}
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        {/if}
      </div>
      {/if}
    </div>

    <!-- RIGHT PANE: Staged Playlist Workstation -->
    <div class="w-1/2 flex flex-col overflow-hidden bg-[#0d0c0a]">
      <!-- Metadata & Info Inputs -->
      <div class="p-4 border-b space-y-3 flex-shrink-0" style="border-color:var(--border);background:#14120f;">
        <div class="space-y-2">
          <input
            type="text"
            bind:value={playlistName}
            placeholder="Playlist Name (e.g. Late Night Drives)"
            class="w-full bg-[#1c1917] border border-zinc-800 rounded-lg px-3 py-2 text-sm font-bold text-white placeholder-zinc-500 outline-none focus:border-amber-500"
          />
          <input
            type="text"
            bind:value={playlistDescription}
            placeholder="Description / notes (optional)…"
            class="w-full bg-[#1c1917] border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-300 placeholder-zinc-600 outline-none focus:border-amber-500"
          />
        </div>

        <!-- Summary Bar -->
        <div class="flex items-center justify-between pt-1 text-xs text-zinc-400 border-t border-zinc-800/80">
          <div class="flex items-center gap-3">
            <span class="font-semibold text-white">{stagedTracks.length} tracks</span>
            <span>&bull;</span>
            <span>~{formatTime(totalDurationSeconds())}</span>
            <span>&bull;</span>
            <span>~{totalSizeMB()} MB</span>
          </div>
          {#if stagedTracks.length > 0}
            <button
              onclick={clearStaged}
              class="text-[11px] text-red-400 hover:text-red-300 hover:underline"
            >
              Clear Staged
            </button>
          {/if}
        </div>
      </div>

      {#if duplicateWarning}
        <div class="px-4 py-2 bg-amber-950/30 border-b border-amber-500/30 text-amber-300 text-xs flex items-center justify-between flex-shrink-0">
          <span>⚠️ {duplicateWarning}</span>
          <button onclick={() => (duplicateWarning = null)} class="text-amber-400 hover:text-white">✕</button>
        </div>
      {/if}

      <!-- Staged Tracklist -->
      <div class="flex-1 overflow-y-auto p-4 space-y-1.5">
        {#if stagedTracks.length === 0}
          <div class="h-full flex flex-col items-center justify-center text-center p-8 text-zinc-500 space-y-3">
            <span class="text-3xl">🔀</span>
            <div class="text-sm font-semibold text-zinc-300">Staged Playlist is Empty</div>
            <p class="text-xs max-w-xs leading-relaxed text-zinc-500">
              Select tracks, full albums, artist catalogs, or existing playlists from the left catalog browser to start assembling.
            </p>
          </div>
        {:else}
          {#each stagedTracks as track, idx (track.track_id + '-' + idx)}
            <div
              class="group flex items-center justify-between p-2 rounded-lg bg-black/30 border border-zinc-800/80 hover:border-zinc-700 transition-all"
            >
              <!-- Index & Info -->
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <span class="text-xs font-mono text-zinc-500 w-5 text-right">{idx + 1}</span>
                {#if track.artwork_url}
                  <img
                    src={thumbUrl(track.artwork_url, "64x64")}
                    alt=""
                    class="w-7 h-7 rounded object-cover flex-shrink-0 bg-zinc-900"
                  />
                {:else}
                  <div class="w-7 h-7 rounded bg-zinc-800 flex items-center justify-center text-[10px] text-zinc-500 flex-shrink-0">
                    ♫
                  </div>
                {/if}
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-semibold text-white truncate">{track.title}</div>
                  <div class="text-[11px] text-zinc-400 truncate">{track.artist} &middot; {track.album}</div>
                </div>
              </div>

              <!-- Reorder / Remove Controls -->
              <div class="flex items-center gap-1 opacity-60 group-hover:opacity-100 transition-opacity">
                <button
                  onclick={() => moveTrack(idx, "up")}
                  disabled={idx === 0}
                  class="w-6 h-6 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-20 text-zinc-300 text-xs flex items-center justify-center"
                  title="Move track up"
                >
                  ↑
                </button>
                <button
                  onclick={() => moveTrack(idx, "down")}
                  disabled={idx === stagedTracks.length - 1}
                  class="w-6 h-6 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-20 text-zinc-300 text-xs flex items-center justify-center"
                  title="Move track down"
                >
                  ↓
                </button>
                <button
                  onclick={() => removeStagedTrack(idx)}
                  class="w-6 h-6 rounded bg-red-950/40 hover:bg-red-900 border border-red-500/20 text-red-300 text-xs flex items-center justify-center ml-1"
                  title="Remove from playlist"
                >
                  ✕
                </button>
              </div>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  </div>
</div>
