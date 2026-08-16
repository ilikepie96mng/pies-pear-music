<script lang="ts">
  import { onMount } from "svelte";
  import { api, type GraveyardTrack } from "../api";
  import LyricsModal from "./LyricsModal.svelte";

  interface Props {
    onopenSettings?: () => void;
  }

  let { onopenSettings }: Props = $props();

  let tracks = $state<GraveyardTrack[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let searchQuery = $state("");
  let selectedPlaylistFilter = $state("all");

  // Lyrics modal state
  let activeLyricsTrack = $state<GraveyardTrack | null>(null);

  async function loadGraveyard() {
    loading = true;
    error = null;
    try {
      const res = await api.getStreamingGraveyard();
      tracks = res.tracks;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadGraveyard();
  });

  async function reveal(track: GraveyardTrack) {
    try {
      await api.revealTrack(track.local_path);
    } catch (e) {
      console.error("Reveal track failed:", e);
    }
  }

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  function formatDate(iso: string | null): string {
    if (!iso) return "Unknown";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  let playlistsList = $derived(() => {
    const set = new Set<string>();
    for (const t of tracks) {
      if (t.playlist_name) set.add(t.playlist_name);
    }
    return Array.from(set).sort();
  });

  let filteredTracks = $derived(() => {
    return tracks.filter(t => {
      if (selectedPlaylistFilter !== "all" && t.playlist_name !== selectedPlaylistFilter) {
        return false;
      }
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        t.title.toLowerCase().includes(q) ||
        t.artist.toLowerCase().includes(q) ||
        t.album.toLowerCase().includes(q) ||
        t.playlist_name.toLowerCase().includes(q)
      );
    });
  });
</script>

<div class="flex flex-col h-full overflow-hidden" style="background:var(--bg);color:var(--text-primary);">
  <!-- Top Banner / Header -->
  <div style="padding:22px 28px 18px;border-bottom:1px solid var(--border);flex-shrink:0;background:linear-gradient(180deg,rgba(196,181,253,0.06) 0%,rgba(0,0,0,0) 100%);">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;">
      <div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:20px;">🏛</span>
          <h1 style="font-size:24px;font-weight:800;letter-spacing:-.02em;margin:0;color:var(--text-primary);">
            Streaming Graveyard & Preservation
          </h1>
          <span style="font-size:11px;padding:3px 8px;border-radius:12px;background:rgba(239,68,68,0.12);color:#f87171;border:1px solid rgba(239,68,68,0.3);font-weight:700;">
            {tracks.length} Delisted Tracks
          </span>
        </div>
        <p style="font-size:13px;color:var(--text-secondary);margin:6px 0 0;max-width:640px;line-height:1.4;">
          Tracks removed upstream or delisted from Apple Music catalogs due to licensing expirations. Because they were synchronized before removal, they remain permanently safe in your local lossless archive.
        </p>
      </div>

      <div style="display:flex;align-items:center;gap:8px;">
        <button
          onclick={loadGraveyard}
          disabled={loading}
          style="padding:7px 14px;border-radius:8px;font-size:12px;font-weight:600;background:rgba(255,255,255,0.06);border:1px solid var(--border);color:var(--text-secondary);cursor:pointer;display:flex;align-items:center;gap:6px;transition:all .15s;"
        >
          {#if loading}
            <span style="width:12px;height:12px;border:2px solid #555;border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;"></span>
          {:else}
            <span>↺</span>
          {/if}
          Refresh
        </button>
      </div>
    </div>

    <!-- Filters & Search Toolbar -->
    <div style="display:flex;align-items:center;gap:12px;margin-top:16px;flex-wrap:wrap;">
      <div style="position:relative;flex:1;min-width:220px;max-width:360px;">
        <input
          type="text"
          bind:value={searchQuery}
          placeholder="Search preserved tracks, artists, albums…"
          style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:7px 12px;font-size:12px;color:white;outline:none;"
        />
        {#if searchQuery}
          <button
            onclick={() => (searchQuery = "")}
            style="position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:11px;color:var(--text-muted);background:transparent;border:none;cursor:pointer;"
          >
            ✕
          </button>
        {/if}
      </div>

      {#if playlistsList().length > 1}
        <div style="display:flex;align-items:center;gap:6px;">
          <label for="graveyard-playlist-filter" style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;font-weight:600;">
            Playlist:
          </label>
          <select
            id="graveyard-playlist-filter"
            bind:value={selectedPlaylistFilter}
            style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:12px;color:white;outline:none;"
          >
            <option value="all">All Playlists ({tracks.length})</option>
            {#each playlistsList() as pl}
              <option value={pl}>{pl}</option>
            {/each}
          </select>
        </div>
      {/if}
    </div>
  </div>

  <!-- Main Content -->
  <div style="flex:1;overflow-y:auto;padding:0;">
    {#if loading && tracks.length === 0}
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:240px;gap:12px;color:var(--text-muted);">
        <span style="width:24px;height:24px;border:2px solid #333;border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;"></span>
        <span style="font-size:13px;">Scanning digital preservation records…</span>
      </div>
    {:else if error}
      <div style="margin:24px;padding:18px;border-radius:12px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:#f87171;font-size:13px;">
        {error}
      </div>
    {:else if tracks.length === 0}
      <!-- Empty State -->
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:320px;text-align:center;padding:24px;color:var(--text-muted);gap:12px;">
        <span style="font-size:36px;opacity:0.8;">🛡</span>
        <div style="font-size:16px;font-weight:700;color:var(--text-primary);">Zero Catalog Removals Detected</div>
        <p style="font-size:13px;max-width:440px;line-height:1.5;color:var(--text-secondary);margin:0;">
          All songs in your tracked playlists are currently active on Apple Music. When any publisher pulls rights or delists songs, your local files will be immortalized here automatically.
        </p>
      </div>
    {:else if filteredTracks().length === 0}
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;text-align:center;color:var(--text-muted);">
        <div style="font-size:13px;">No delisted tracks match "{searchQuery}"</div>
      </div>
    {:else}
      <!-- Delisted Tracks Table -->
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead style="position:sticky;top:0;background:#0d0b12;border-bottom:1px solid var(--border);z-index:2;">
          <tr>
            <th style="width:40px;padding:10px 12px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">#</th>
            <th style="width:40px;padding:10px 4px;"></th>
            <th style="padding:10px 12px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Track Title</th>
            <th style="padding:10px 12px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Artist / Album</th>
            <th style="padding:10px 12px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Original Playlist</th>
            <th style="padding:10px 12px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Delisted</th>
            <th style="padding:10px 12px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Preservation Status</th>
            <th style="width:130px;padding:10px 12px;text-align:right;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each filteredTracks() as track, i}
            <tr
              style="border-bottom:1px solid rgba(255,255,255,0.04);transition:background .12s;"
              onmouseenter={e => { (e.currentTarget as HTMLElement).style.background='rgba(255,255,255,0.03)'; }}
              onmouseleave={e => { (e.currentTarget as HTMLElement).style.background='transparent'; }}
            >
              <td style="padding:8px 12px;color:var(--text-muted);font-size:11px;font-variant-numeric:tabular-nums;">{i + 1}</td>
              <td style="padding:8px 4px;">
                {#if track.artwork_url}
                  <img
                    src={thumbUrl(track.artwork_url, "56x56")}
                    alt=""
                    style="width:30px;height:30px;border-radius:4px;object-fit:cover;display:block;"
                    onerror={e => { (e.currentTarget as HTMLImageElement).style.display='none'; }}
                  />
                {:else}
                  <div style="width:30px;height:30px;border-radius:4px;background:#221d2b;display:flex;align-items:center;justify-content:center;font-size:12px;color:var(--text-muted);">♫</div>
                {/if}
              </td>
              <td style="padding:8px 12px;color:var(--text-primary);font-weight:600;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                <div title={track.title}>{track.title}</div>
              </td>
              <td style="padding:8px 12px;color:var(--text-secondary);max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                <div style="color:var(--text-secondary);font-size:12px;" title={track.artist}>{track.artist}</div>
                <div style="color:var(--text-muted);font-size:11px;" title={track.album}>{track.album}</div>
              </td>
              <td style="padding:8px 12px;">
                <span style="font-size:11px;padding:2px 7px;border-radius:4px;background:rgba(255,255,255,0.05);color:var(--text-secondary);border:1px solid var(--border);">
                  {track.playlist_name}
                </span>
              </td>
              <td style="padding:8px 12px;color:#a8a29e;font-size:11px;white-space:nowrap;">
                {formatDate(track.delisted_at)}
              </td>
              <td style="padding:8px 12px;">
                <span style="display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:2px 8px;border-radius:6px;background:rgba(34,197,94,0.1);color:#4ade80;border:1px solid rgba(34,197,94,0.25);font-weight:600;">
                  <span>✓</span> Preserved Locally in FLAC
                </span>
              </td>
              <td style="padding:8px 12px;text-align:right;white-space:nowrap;">
                <div style="display:inline-flex;align-items:center;gap:6px;">
                  <button
                    onclick={() => (activeLyricsTrack = track)}
                    title="View lyrics"
                    style="padding:4px 8px;border-radius:6px;font-size:11px;background:rgba(252,211,77,0.1);color:var(--accent);border:1px solid rgba(252,211,77,0.25);cursor:pointer;"
                  >
                    Lyrics
                  </button>
                  <button
                    onclick={() => reveal(track)}
                    title="Show file in file manager"
                    style="padding:4px 8px;border-radius:6px;font-size:11px;background:rgba(255,255,255,0.06);color:var(--text-secondary);border:1px solid var(--border);cursor:pointer;"
                  >
                    Reveal ↗
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

{#if activeLyricsTrack}
  <LyricsModal
    track={activeLyricsTrack}
    onclose={() => (activeLyricsTrack = null)}
  />
{/if}

<style>
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
