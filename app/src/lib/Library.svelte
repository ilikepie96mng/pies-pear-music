<script lang="ts">
  import { onMount } from "svelte";
  import {
    api,
    type LibraryTrack,
    type LibraryStats,
    type LibraryAuditReport,
    type LibraryIntegrityReport,
    type LibraryRepairResult,
  } from "../api";
  import LyricsModal from "./LyricsModal.svelte";
  import DapExportModal from "./DapExportModal.svelte";
  import { notifyIntegrityCompleted } from "./notifications";

  interface Props {
    onselectPlaylist?: (name: string) => void;
    onstartSync?: (name: string) => void;
  }

  let { onselectPlaylist, onstartSync }: Props = $props();

  type Tab = "tracks" | "albums" | "artists" | "health";
  let activeTab = $state<Tab>("tracks");

  // State
  let loading = $state(true);
  let error = $state<string | null>(null);
  let tracks = $state<LibraryTrack[]>([]);
  let stats = $state<LibraryStats | null>(null);

  // Search & Filters
  let searchQuery = $state("");
  let selectedPlaylistFilter = $state<string>("all");
  let selectedFormatFilter = $state<string>("all");
  let selectedLyricsFilter = $state<string>("all");
  let selectedStatusFilter = $state<string>("all");
  type SortKey = "downloaded_at" | "title" | "artist" | "album" | "file_size";
  let sortKey = $state<SortKey>("downloaded_at");
  let sortAsc = $state(false);

  // Modals
  let activeLyricsTrack = $state<LibraryTrack | null>(null);
  let dapExportPlaylist = $state<string | null>(null);
  let dapExportTrackCount = $state<number>(0);

  // Health Audit & Repair State
  let auditLoading = $state(false);
  let auditReport = $state<LibraryAuditReport | null>(null);
  let auditError = $state<string | null>(null);

  let integrityLoading = $state(false);
  let integrityReport = $state<LibraryIntegrityReport | null>(null);
  let integrityError = $state<string | null>(null);

  let repairLoading = $state(false);
  let repairMessage = $state<{ type: "success" | "error"; text: string } | null>(null);

  function formatBytes(bytes: number): string {
    if (!bytes || bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  async function loadLibraryData() {
    loading = true;
    error = null;
    try {
      const [tracksData, statsData] = await Promise.all([
        api.allLibraryTracks(),
        api.libraryStats(),
      ]);
      tracks = tracksData;
      stats = statsData;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadLibraryData();
  });

  // Derived unique playlists and formats for filter dropdowns
  let allPlaylists = $derived(
    Array.from(new Set(tracks.flatMap((t) => t.playlists || []))).sort()
  );

  let allFormats = $derived(
    Array.from(new Set(tracks.map((t) => t.format).filter(Boolean))).sort()
  );

  // Filtered & Sorted Tracks
  let filteredTracks = $derived(
    tracks.filter((t) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesTitle = t.title.toLowerCase().includes(q);
        const matchesArtist = t.artist.toLowerCase().includes(q);
        const matchesAlbum = t.album.toLowerCase().includes(q);
        const matchesPlaylist = (t.playlists || []).some((p) => p.toLowerCase().includes(q));
        if (!matchesTitle && !matchesArtist && !matchesAlbum && !matchesPlaylist) {
          return false;
        }
      }
      if (selectedPlaylistFilter !== "all" && !(t.playlists || []).includes(selectedPlaylistFilter)) {
        return false;
      }
      if (selectedFormatFilter !== "all" && t.format !== selectedFormatFilter) {
        return false;
      }
      if (selectedLyricsFilter === "has_lyrics" && !t.has_lyrics) {
        return false;
      }
      if (selectedLyricsFilter === "no_lyrics" && t.has_lyrics) {
        return false;
      }
      if (selectedStatusFilter === "on_disk" && !t.exists_on_disk) {
        return false;
      }
      if (selectedStatusFilter === "missing" && t.exists_on_disk) {
        return false;
      }
      return true;
    })
  );

  let sortedTracks = $derived(
    [...filteredTracks].sort((a, b) => {
      let comp = 0;
      if (sortKey === "downloaded_at") {
        comp = (a.downloaded_at || "").localeCompare(b.downloaded_at || "");
      } else if (sortKey === "title") {
        comp = a.title.localeCompare(b.title);
      } else if (sortKey === "artist") {
        comp = a.artist.localeCompare(b.artist);
      } else if (sortKey === "album") {
        comp = a.album.localeCompare(b.album);
      } else if (sortKey === "file_size") {
        comp = (a.file_size || 0) - (b.file_size || 0);
      }
      return sortAsc ? comp : -comp;
    })
  );

  // Album Groupings
  interface AlbumGroup {
    album: string;
    artist: string;
    artwork_url: string | null;
    tracks: LibraryTrack[];
    total_size: number;
    playlists: Set<string>;
  }

  let albumGroups = $derived.by(() => {
    const map = new Map<string, AlbumGroup>();
    for (const t of filteredTracks) {
      const key = `${t.artist} — ${t.album}`;
      let group = map.get(key);
      if (!group) {
        group = {
          album: t.album,
          artist: t.artist,
          artwork_url: t.artwork_url,
          tracks: [],
          total_size: 0,
          playlists: new Set<string>(),
        };
        map.set(key, group);
      }
      group.tracks.push(t);
      group.total_size += t.file_size || 0;
      (t.playlists || []).forEach((p) => group!.playlists.add(p));
      if (!group.artwork_url && t.artwork_url) {
        group.artwork_url = t.artwork_url;
      }
    }
    return Array.from(map.values()).sort((a, b) => a.album.localeCompare(b.album));
  });

  // Artist Groupings
  interface ArtistGroup {
    artist: string;
    albums: Set<string>;
    tracks: LibraryTrack[];
    total_size: number;
  }

  let artistGroups = $derived.by(() => {
    const map = new Map<string, ArtistGroup>();
    for (const t of filteredTracks) {
      let group = map.get(t.artist);
      if (!group) {
        group = {
          artist: t.artist,
          albums: new Set<string>(),
          tracks: [],
          total_size: 0,
        };
        map.set(t.artist, group);
      }
      group.albums.add(t.album);
      group.tracks.push(t);
      group.total_size += t.file_size || 0;
    }
    return Array.from(map.values()).sort((a, b) => a.artist.localeCompare(b.artist));
  });

  // Health Actions
  async function runAudit() {
    auditLoading = true;
    auditError = null;
    repairMessage = null;
    try {
      auditReport = await api.auditLibrary();
    } catch (e) {
      auditError = String(e);
    } finally {
      auditLoading = false;
    }
  }

  async function runIntegrityCheck() {
    integrityLoading = true;
    integrityError = null;
    repairMessage = null;
    try {
      integrityReport = await api.verifyIntegrity();
      if (integrityReport) {
        void notifyIntegrityCompleted(integrityReport.corrupted?.length ?? 0);
      }
    } catch (e) {
      integrityError = String(e);
    } finally {
      integrityLoading = false;
    }
  }

  async function handlePruneMissing() {
    if (!confirm("Are you sure you want to prune database references for missing tracks? This cannot be undone.")) {
      return;
    }
    repairLoading = true;
    repairMessage = null;
    try {
      const res = await api.repairLibrary("prune_missing");
      repairMessage = {
        type: "success",
        text: `Pruned ${res.pruned_count ?? 0} missing track record(s) from database.`,
      };
      await Promise.all([loadLibraryData(), runAudit()]);
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      repairLoading = false;
    }
  }

  async function handleAdoptOrphans() {
    repairLoading = true;
    repairMessage = null;
    try {
      const res = await api.repairLibrary("adopt_orphans");
      repairMessage = {
        type: "success",
        text: `Successfully imported ${res.adopted_count ?? 0} untracked audio file(s) into the library.`,
      };
      await Promise.all([loadLibraryData(), runAudit()]);
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      repairLoading = false;
    }
  }

  async function handleRegenerateM3u8() {
    repairLoading = true;
    repairMessage = null;
    try {
      const res = await api.repairLibrary("regenerate_m3u8");
      repairMessage = {
        type: "success",
        text: `Regenerated ${(res.playlists || []).length} playlist .m3u8 file(s).`,
      };
    } catch (e) {
      repairMessage = { type: "error", text: String(e) };
    } finally {
      repairLoading = false;
    }
  }

  function filterByPlaylist(pl: string) {
    selectedPlaylistFilter = pl;
    activeTab = "tracks";
  }

  function filterByArtist(art: string) {
    searchQuery = art;
    activeTab = "tracks";
  }

  function filterByAlbum(alb: string) {
    searchQuery = alb;
    activeTab = "tracks";
  }
</script>

<div class="h-full flex flex-col overflow-hidden" style="background:var(--bg);color:var(--text-primary);">
  <!-- Header Bar -->
  <div class="p-6 pb-4 border-b flex flex-col gap-4" style="border-color:var(--border);">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <span>♫</span> Library Stewardship
        </h1>
        <span class="text-xs px-2.5 py-0.5 rounded-full font-medium" style="background:var(--accent-dim);color:var(--accent);border:1px solid rgba(252,211,77,0.2);">
          Workstation
        </span>
      </div>

      <div class="flex items-center gap-3">
        <button
          onclick={loadLibraryData}
          disabled={loading}
          class="px-3 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-colors"
          style="background:var(--surface);color:var(--text-secondary);border:1px solid var(--border);"
        >
          <span>↻</span> {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
    </div>

    <!-- Stats Ribbon -->
    {#if stats}
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Tracks</span>
          <span class="text-lg font-bold text-white mt-0.5">{stats.total_tracks.toLocaleString()}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Albums</span>
          <span class="text-lg font-bold text-white mt-0.5">{stats.total_albums.toLocaleString()}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Artists</span>
          <span class="text-lg font-bold text-white mt-0.5">{stats.total_artists.toLocaleString()}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Storage Size</span>
          <span class="text-lg font-bold text-white mt-0.5">{formatBytes(stats.total_bytes)}</span>
        </div>
        <div class="p-3 rounded-xl flex flex-col justify-center" style="background:var(--surface);border:1px solid var(--border);">
          <span class="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Playlists / Graveyard</span>
          <div class="flex items-center gap-1.5 text-lg font-bold text-white mt-0.5">
            <span>{stats.total_playlists}</span>
            <span class="text-xs font-normal text-zinc-500">({stats.delisted_count} delisted)</span>
          </div>
        </div>
      </div>
    {/if}

    <!-- Tab Navigation -->
    <div class="flex items-center gap-2 pt-1 border-t" style="border-color:var(--border);">
      {#each [
        { id: "tracks", label: "Tracks", count: tracks.length },
        { id: "albums", label: "Albums", count: albumGroups.length },
        { id: "artists", label: "Artists", count: artistGroups.length },
        { id: "health", label: "Health & Diagnostics", badge: auditReport?.summary.missing_files_count ? `! ${auditReport.summary.missing_files_count}` : null },
      ] as tab}
        <button
          onclick={() => (activeTab = tab.id as Tab)}
          class="px-4 py-2 text-xs font-semibold rounded-lg transition-colors flex items-center gap-2"
          style={activeTab === tab.id
            ? "background:var(--accent);color:black;"
            : "background:transparent;color:var(--text-secondary);"}
        >
          <span>{tab.label}</span>
          {#if tab.count !== undefined && activeTab !== tab.id}
            <span class="opacity-60 text-[10px]">({tab.count})</span>
          {/if}
          {#if tab.badge}
            <span class="px-1.5 py-0.2 rounded text-[10px] bg-red-500 text-white font-bold">{tab.badge}</span>
          {/if}
        </button>
      {/each}
    </div>
  </div>

  <!-- Content Area -->
  <div class="flex-1 overflow-y-auto p-6">
    {#if error}
      <div class="p-4 rounded-xl mb-4 text-xs bg-red-950/50 border border-red-800 text-red-300">
        Failed to load library: {error}
      </div>
    {/if}

    <!-- TAB: TRACKS / ALBUMS / ARTISTS (Share Search & Filter Bar) -->
    {#if activeTab !== "health"}
      <div class="flex flex-wrap items-center gap-3 mb-6">
        <!-- Search bar -->
        <div class="flex-1 min-w-[240px] relative">
          <input
            bind:value={searchQuery}
            placeholder="Search tracks, artists, albums, or playlists…"
            class="w-full px-3.5 py-2 text-xs rounded-lg outline-none transition-all placeholder:text-zinc-500"
            style="background:var(--surface);border:1px solid var(--border);color:white;"
          />
          {#if searchQuery}
            <button
              onclick={() => (searchQuery = "")}
              class="absolute right-3 top-2.5 text-xs text-zinc-500 hover:text-white"
            >✕</button>
          {/if}
        </div>

        <!-- Playlist Filter -->
        <select
          bind:value={selectedPlaylistFilter}
          class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
          style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
        >
          <option value="all">All Playlists ({allPlaylists.length})</option>
          {#each allPlaylists as pl}
            <option value={pl}>{pl}</option>
          {/each}
        </select>

        <!-- Format Filter -->
        <select
          bind:value={selectedFormatFilter}
          class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
          style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
        >
          <option value="all">All Formats</option>
          {#each allFormats as fmt}
            <option value={fmt}>{fmt}</option>
          {/each}
        </select>

        <!-- Lyrics Filter -->
        <select
          bind:value={selectedLyricsFilter}
          class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
          style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
        >
          <option value="all">All Lyrics</option>
          <option value="has_lyrics">With .lrc Lyrics</option>
          <option value="no_lyrics">Missing Lyrics</option>
        </select>

        <!-- Sort Control -->
        <div class="flex items-center gap-1">
          <select
            bind:value={sortKey}
            class="px-3 py-2 text-xs rounded-lg outline-none cursor-pointer"
            style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
          >
            <option value="downloaded_at">Date Downloaded</option>
            <option value="title">Title</option>
            <option value="artist">Artist</option>
            <option value="album">Album</option>
            <option value="file_size">File Size</option>
          </select>
          <button
            onclick={() => (sortAsc = !sortAsc)}
            title={sortAsc ? "Sort Ascending" : "Sort Descending"}
            class="p-2 text-xs rounded-lg transition-colors"
            style="background:var(--surface);border:1px solid var(--border);color:var(--text-secondary);"
          >
            {sortAsc ? "▲" : "▼"}
          </button>
        </div>
      </div>
    {/if}

    <!-- TAB: TRACKS VIEW -->
    {#if activeTab === "tracks"}
      {#if loading}
        <div class="text-zinc-500 text-xs py-8 text-center">Loading library tracks…</div>
      {:else if sortedTracks.length === 0}
        <div class="text-zinc-500 text-xs py-12 text-center flex flex-col items-center gap-2">
          <span>No tracks found matching your query or filter.</span>
          {#if searchQuery || selectedPlaylistFilter !== "all" || selectedFormatFilter !== "all"}
            <button
              onclick={() => { searchQuery = ""; selectedPlaylistFilter = "all"; selectedFormatFilter = "all"; selectedLyricsFilter = "all"; }}
              class="text-amber-400 underline cursor-pointer"
            >Reset filters</button>
          {/if}
        </div>
      {:else}
        <div class="border rounded-xl overflow-hidden" style="border-color:var(--border);background:var(--surface);">
          <table class="w-full text-left text-xs border-collapse">
            <thead>
              <tr class="border-b text-zinc-500 font-medium uppercase text-[10px] tracking-wider" style="border-color:var(--border);background:rgba(0,0,0,0.2);">
                <th class="py-3 px-4 w-12 text-center">#</th>
                <th class="py-3 px-4">Title & Artist</th>
                <th class="py-3 px-4 hidden md:table-cell">Album</th>
                <th class="py-3 px-4">Provenance</th>
                <th class="py-3 px-4 hidden sm:table-cell">Format</th>
                <th class="py-3 px-4 hidden lg:table-cell">Size</th>
                <th class="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y" style="border-color:var(--border);">
              {#each sortedTracks as track, index (track.track_id)}
                <tr class="hover:bg-white/[0.03] transition-colors group">
                  <!-- Index & Art -->
                  <td class="py-2.5 px-4 text-center">
                    <div class="w-8 h-8 rounded overflow-hidden bg-black/40 flex items-center justify-center flex-shrink-0 mx-auto">
                      {#if track.artwork_url}
                        <img
                          src={thumbUrl(track.artwork_url, "64x64")}
                          alt=""
                          class="w-full h-full object-cover"
                          onerror={(e) => ((e.currentTarget as HTMLElement).style.display = "none")}
                        />
                      {:else}
                        <span class="text-zinc-600 text-[10px]">♪</span>
                      {/if}
                    </div>
                  </td>

                  <!-- Title & Artist -->
                  <td class="py-2.5 px-4">
                    <div class="font-semibold text-white truncate max-w-[260px]">{track.title}</div>
                    <button
                      onclick={() => filterByArtist(track.artist)}
                      class="text-zinc-400 text-[11px] truncate max-w-[260px] text-left hover:text-amber-400 transition-colors"
                    >
                      {track.artist}
                    </button>
                  </td>

                  <!-- Album -->
                  <td class="py-2.5 px-4 hidden md:table-cell">
                    <button
                      onclick={() => filterByAlbum(track.album)}
                      class="text-zinc-400 hover:text-amber-400 transition-colors truncate max-w-[200px] text-left"
                    >
                      {track.album}
                    </button>
                  </td>

                  <!-- Provenance Badges -->
                  <td class="py-2.5 px-4">
                    <div class="flex flex-wrap gap-1 max-w-[220px]">
                      {#each (track.playlists || []) as pl}
                        <button
                          onclick={() => filterByPlaylist(pl)}
                          class="text-[10px] px-2 py-0.5 rounded-md font-medium transition-colors hover:border-amber-400"
                          style="background:rgba(252,211,77,0.1);color:var(--accent);border:1px solid rgba(252,211,77,0.2);"
                        >
                          {pl}
                        </button>
                      {/each}
                      {#if (!track.playlists || track.playlists.length === 0)}
                        <span class="text-[10px] text-zinc-600 italic">Standalone</span>
                      {/if}
                    </div>
                  </td>

                  <!-- Format & Indicators -->
                  <td class="py-2.5 px-4 hidden sm:table-cell">
                    <div class="flex items-center gap-1.5">
                      <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
                        {track.format}
                      </span>
                      {#if track.has_lyrics}
                        <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 font-medium" title="Synced/Unsynced LRC lyrics available">
                          LRC
                        </span>
                      {/if}
                      {#if !track.exists_on_disk}
                        <span class="text-[10px] px-1.5 py-0.5 rounded bg-red-950 text-red-300 font-bold" title="File missing on disk!">
                          Missing
                        </span>
                      {/if}
                    </div>
                  </td>

                  <!-- Size -->
                  <td class="py-2.5 px-4 hidden lg:table-cell text-zinc-500 font-mono text-[11px]">
                    {formatBytes(track.file_size)}
                  </td>

                  <!-- Actions -->
                  <td class="py-2.5 px-4 text-right">
                    <div class="flex items-center justify-end gap-1.5 opacity-80 group-hover:opacity-100 transition-opacity">
                      {#if track.has_lyrics}
                        <button
                          onclick={() => (activeLyricsTrack = track)}
                          title="View Lyrics"
                          class="px-2 py-1 text-[11px] rounded hover:bg-zinc-700 text-zinc-300 transition-colors"
                        >
                          Lyrics
                        </button>
                      {/if}
                      {#if track.local_path && track.exists_on_disk}
                        <button
                          onclick={() => { api.revealTrack(track.local_path).catch(console.error); }}
                          title="Reveal in file explorer"
                          class="px-2 py-1 text-[11px] rounded hover:bg-zinc-700 text-zinc-300 transition-colors"
                        >
                          Reveal
                        </button>
                      {/if}
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {/if}

    <!-- TAB: ALBUMS VIEW -->
    {#if activeTab === "albums"}
      {#if albumGroups.length === 0}
        <div class="text-zinc-500 text-xs py-12 text-center">No albums found matching criteria.</div>
      {:else}
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {#each albumGroups as alb}
            <button
              type="button"
              class="rounded-xl overflow-hidden p-3 flex flex-col gap-2.5 cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-lg text-left"
              style="background:var(--surface);border:1px solid var(--border);"
              onclick={() => filterByAlbum(alb.album)}
            >
              <div class="aspect-square w-full rounded-lg overflow-hidden bg-black/40 flex items-center justify-center">
                {#if alb.artwork_url}
                  <img
                    src={thumbUrl(alb.artwork_url, "300x300")}
                    alt={alb.album}
                    class="w-full h-full object-cover"
                    onerror={(e) => ((e.currentTarget as HTMLElement).style.display = "none")}
                  />
                {:else}
                  <span class="text-4xl text-zinc-700">♪</span>
                {/if}
              </div>

              <div class="flex flex-col min-w-0 w-full">
                <div class="font-bold text-xs text-white truncate" title={alb.album}>{alb.album}</div>
                <div class="text-[11px] text-zinc-400 truncate mt-0.5" title={alb.artist}>{alb.artist}</div>
                <div class="flex items-center justify-between text-[10px] text-zinc-500 mt-2 pt-2 border-t" style="border-color:var(--border);">
                  <span>{alb.tracks.length} track{alb.tracks.length === 1 ? "" : "s"}</span>
                  <span class="font-mono">{formatBytes(alb.total_size)}</span>
                </div>
              </div>
            </button>
          {/each}
        </div>
      {/if}
    {/if}

    <!-- TAB: ARTISTS VIEW -->
    {#if activeTab === "artists"}
      {#if artistGroups.length === 0}
        <div class="text-zinc-500 text-xs py-12 text-center">No artists found matching criteria.</div>
      {:else}
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {#each artistGroups as art}
            <button
              type="button"
              class="p-4 rounded-xl flex items-center justify-between cursor-pointer transition-all hover:bg-white/[0.04] text-left w-full"
              style="background:var(--surface);border:1px solid var(--border);"
              onclick={() => filterByArtist(art.artist)}
            >
              <div class="flex flex-col min-w-0 pr-3">
                <span class="font-bold text-xs text-white truncate">{art.artist}</span>
                <span class="text-[11px] text-zinc-400 mt-0.5">
                  {art.albums.size} album{art.albums.size === 1 ? "" : "s"} • {art.tracks.length} track{art.tracks.length === 1 ? "" : "s"}
                </span>
              </div>
              <span class="text-[11px] font-mono text-zinc-500 flex-shrink-0">{formatBytes(art.total_size)}</span>
            </button>
          {/each}
        </div>
      {/if}
    {/if}

    <!-- TAB: HEALTH & REPAIR WORKSTATION -->
    {#if activeTab === "health"}
      <div class="flex flex-col gap-6 max-w-5xl mx-auto">
        <!-- Repair Message Banner -->
        {#if repairMessage}
          <div
            class="p-4 rounded-xl text-xs flex items-center justify-between font-medium"
            style={repairMessage.type === "success"
              ? "background:rgba(34,197,94,0.15);color:#4ade80;border:1px solid rgba(34,197,94,0.3);"
              : "background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.3);"}
          >
            <span>{repairMessage.text}</span>
            <button onclick={() => (repairMessage = null)} class="text-xs opacity-70 hover:opacity-100">✕</button>
          </div>
        {/if}

        <!-- Maintenance & Diagnostic Cards Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- Card 1: Library Filesystem & Database Health -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4" style="background:var(--surface);border:1px solid var(--border);">
            <div>
              <div class="flex items-center justify-between">
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>◈</span> Health & Discrepancy Audit
                </h3>
                {#if auditReport}
                  <span class="text-[10px] px-2 py-0.5 rounded font-mono" style="background:rgba(255,255,255,0.05);color:var(--text-muted);">
                    Scanned {auditReport.summary.total_db_tracks} DB tracks
                  </span>
                {/if}
              </div>
              <p class="text-xs text-zinc-400 mt-2 leading-relaxed">
                Scan your library storage to identify database entries missing files on disk, unindexed audio files, and missing metadata.
              </p>

              {#if auditReport}
                <div class="grid grid-cols-2 gap-2 mt-4 text-xs font-mono">
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Missing Files:</span>
                    <span class={auditReport.summary.missing_files_count > 0 ? "text-red-400 font-bold text-sm" : "text-emerald-400 font-bold text-sm"}>
                      {auditReport.summary.missing_files_count}
                    </span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Orphaned Files:</span>
                    <span class={auditReport.summary.orphaned_files_count > 0 ? "text-amber-400 font-bold text-sm" : "text-zinc-300 font-bold text-sm"}>
                      {auditReport.summary.orphaned_files_count}
                    </span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Missing .lrc:</span>
                    <span class="text-zinc-300 font-bold text-sm">{auditReport.summary.missing_lyrics_count}</span>
                  </div>
                  <div class="p-2.5 rounded-lg bg-black/30 border border-white/5">
                    <span class="text-zinc-400 block text-[10px]">Missing Artwork:</span>
                    <span class="text-zinc-300 font-bold text-sm">{auditReport.summary.missing_art_count}</span>
                  </div>
                </div>
              {/if}

              {#if auditError}
                <div class="mt-3 text-xs text-red-400">{auditError}</div>
              {/if}
            </div>

            <div class="flex flex-wrap gap-2 pt-2 border-t" style="border-color:var(--border);">
              <button
                onclick={runAudit}
                disabled={auditLoading || repairLoading}
                class="px-3.5 py-2 text-xs font-bold rounded-lg transition-all"
                style="background:var(--accent);color:black;"
              >
                {auditLoading ? "Auditing Filesystem…" : "Run Health Scan"}
              </button>

              {#if auditReport?.summary.missing_files_count}
                <button
                  onclick={handlePruneMissing}
                  disabled={repairLoading}
                  class="px-3 py-2 text-xs font-semibold rounded-lg bg-red-900/60 hover:bg-red-800 text-red-200 border border-red-700 transition-colors"
                >
                  Prune Dead DB References ({auditReport.summary.missing_files_count})
                </button>
              {/if}

              {#if auditReport?.summary.orphaned_files_count}
                <button
                  onclick={handleAdoptOrphans}
                  disabled={repairLoading}
                  class="px-3 py-2 text-xs font-semibold rounded-lg bg-amber-900/60 hover:bg-amber-800 text-amber-200 border border-amber-700 transition-colors"
                >
                  Adopt Untracked Files ({auditReport.summary.orphaned_files_count})
                </button>
              {/if}
            </div>
          </div>

          <!-- Card 2: Audio Stream Integrity & FLAC Verification -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4" style="background:var(--surface);border:1px solid var(--border);">
            <div>
              <div class="flex items-center justify-between">
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>⚙</span> Audio Frame Integrity Verification
                </h3>
              </div>
              <p class="text-xs text-zinc-400 mt-2 leading-relaxed">
                Run batch stream decoding validation (`flac -t -s`) across your library tracks to ensure bit-perfect audio headers and lossless stream fidelity.
              </p>

              {#if integrityReport}
                <div class="mt-4 p-3 rounded-lg bg-black/30 border border-white/5 text-xs">
                  <div class="flex items-center justify-between">
                    <span class="text-zinc-400">Scanned Tracks:</span>
                    <span class="text-white font-mono font-bold">{integrityReport.checked_count}</span>
                  </div>
                  <div class="flex items-center justify-between mt-1">
                    <span class="text-zinc-400">Status:</span>
                    <span class={integrityReport.status === "ok" ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                      {integrityReport.status === "ok" ? "All Bitstreams Valid" : `${integrityReport.corrupted.length} Corrupted File(s)`}
                    </span>
                  </div>
                </div>
              {/if}

              {#if integrityError}
                <div class="mt-3 text-xs text-red-400">{integrityError}</div>
              {/if}
            </div>

            <div class="pt-2 border-t flex items-center gap-2" style="border-color:var(--border);">
              <button
                onclick={runIntegrityCheck}
                disabled={integrityLoading || repairLoading}
                class="px-3.5 py-2 text-xs font-bold rounded-lg transition-all"
                style="background:var(--surface-hover);color:white;border:1px solid var(--border);"
              >
                {integrityLoading ? "Decoding FLAC Frames…" : "Run Stream Integrity Scan"}
              </button>
            </div>
          </div>

          <!-- Card 3: Playlist Sync & M3U8 Regeneration -->
          <div class="p-5 rounded-2xl flex flex-col justify-between gap-4 md:col-span-2" style="background:var(--surface);border:1px solid var(--border);">
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <h3 class="font-bold text-sm text-white flex items-center gap-2">
                  <span>☰</span> Playlist Sync & M3U8 Regeneration
                </h3>
                <p class="text-xs text-zinc-400 mt-1 max-w-2xl leading-relaxed">
                  Safely reconstruct all `.m3u8` playlist files in your library `playlists/` folder from verified SQLite database track associations.
                </p>
              </div>

              <button
                onclick={handleRegenerateM3u8}
                disabled={repairLoading}
                class="px-4 py-2 text-xs font-semibold rounded-lg self-start md:self-auto transition-colors"
                style="background:var(--surface);color:white;border:1px solid var(--border);"
              >
                {repairLoading ? "Regenerating…" : "Regenerate All Playlists (.m3u8)"}
              </button>
            </div>
          </div>
        </div>

        <!-- Issue Detail Feed -->
        {#if auditReport?.missing_files?.length}
          <div class="p-5 rounded-2xl border border-red-900/50 bg-red-950/20">
            <h4 class="text-xs font-bold text-red-300 uppercase tracking-wider mb-3">
              Missing Track Files ({auditReport.missing_files.length})
            </h4>
            <div class="flex flex-col gap-2 max-h-60 overflow-y-auto font-mono text-xs">
              {#each auditReport.missing_files as item}
                <div class="p-2.5 rounded bg-black/40 flex items-center justify-between text-zinc-300">
                  <div class="flex flex-col min-w-0 pr-4">
                    <span class="font-bold text-white truncate">{item.title} — {item.artist}</span>
                    <span class="text-[10px] text-zinc-500 truncate">{item.local_path}</span>
                  </div>
                  <span class="text-[10px] text-red-400 px-2 py-0.5 rounded bg-red-950 border border-red-800">
                    Missing on disk
                  </span>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if auditReport?.orphaned_files?.length}
          <div class="p-5 rounded-2xl border border-amber-900/50 bg-amber-950/20">
            <h4 class="text-xs font-bold text-amber-300 uppercase tracking-wider mb-3">
              Untracked Audio Files on Disk ({auditReport.orphaned_files.length})
            </h4>
            <div class="flex flex-col gap-2 max-h-60 overflow-y-auto font-mono text-xs">
              {#each auditReport.orphaned_files as item}
                <div class="p-2.5 rounded bg-black/40 flex items-center justify-between text-zinc-300">
                  <div class="flex flex-col min-w-0 pr-4">
                    <span class="font-bold text-white truncate">{item.name}</span>
                    <span class="text-[10px] text-zinc-500 truncate">{item.relative_path}</span>
                  </div>
                  <span class="text-[10px] text-zinc-400">
                    {formatBytes(item.size)}
                  </span>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if integrityReport?.corrupted?.length}
          <div class="p-5 rounded-2xl border border-red-900/50 bg-red-950/20">
            <h4 class="text-xs font-bold text-red-300 uppercase tracking-wider mb-3">
              Corrupted FLAC Audio Files ({integrityReport.corrupted.length})
            </h4>
            <div class="flex flex-col gap-2 max-h-60 overflow-y-auto font-mono text-xs">
              {#each integrityReport.corrupted as item}
                <div class="p-2.5 rounded bg-black/40 flex flex-col gap-1 text-zinc-300">
                  <div class="flex items-center justify-between">
                    <span class="font-bold text-white">{item.title} — {item.artist}</span>
                    <span class="text-[10px] text-red-400 font-bold">Corrupted</span>
                  </div>
                  <span class="text-[10px] text-zinc-500 truncate">{item.local_path}</span>
                  <span class="text-[10px] text-red-300 bg-red-950/60 p-1 rounded font-mono">{item.error}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<!-- Lyrics Modal -->
{#if activeLyricsTrack}
  <LyricsModal
    track={activeLyricsTrack}
    onclose={() => (activeLyricsTrack = null)}
  />
{/if}

<!-- DAP Export Modal -->
{#if dapExportPlaylist}
  <DapExportModal
    playlistName={dapExportPlaylist}
    trackCount={dapExportTrackCount}
    onclose={() => (dapExportPlaylist = null)}
  />
{/if}
