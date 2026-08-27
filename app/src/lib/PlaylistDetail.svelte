<script lang="ts">
  import { save } from "@tauri-apps/plugin-dialog";
  import { openPath } from "@tauri-apps/plugin-opener";
  import { onMount, tick } from "svelte";
  import { api, type Playlist, type Track, type SyncRun } from "../api";
  import DapExportModal from "./DapExportModal.svelte";
  import LyricsModal from "./LyricsModal.svelte";

  interface Props {
    playlist: Playlist;
    onstartSync: (name: string) => void;
    onrenamed: (oldName: string, newName: string) => void;
    ondeleted: (name: string) => void;
    onupdated: (pl: Playlist) => void;
  }

  let { playlist, onstartSync, onrenamed, ondeleted, onupdated }: Props = $props();

  let tracks = $state<Track[]>([]);
  let loadingTracks = $state(true);
  let tracksError = $state<string | null>(null);

  // Modals
  let showDapModal = $state(false);
  let activeLyricsTrack = $state<Track | null>(null);
  let showDuplicatesModal = $state(false);
  let duplicatesList = $state<any[]>([]);
  let checkingDuplicates = $state(false);
  let deduplicating = $state(false);
  let deduplicateMsg = $state<string | null>(null);

  // Missing / Unowned tracks download
  let downloadingMissing = $state(false);
  let downloadMissingMsg = $state<string | null>(null);

  let unownedTracks = $derived(tracks.filter((t) => !t.local_path || t.local_path === ""));

  async function handleDownloadMissingTracks() {
    if (unownedTracks.length === 0) return;
    downloadingMissing = true;
    downloadMissingMsg = null;
    try {
      const res = await api.downloadGeminiTracks(unownedTracks as any);
      downloadMissingMsg = `Queued ${res.queued} unowned track(s) for background download!`;
      // Poll library updates to reflect newly downloaded tracks automatically
      let polls = 0;
      const pollInterval = setInterval(async () => {
        polls++;
        await loadTracks();
        if (unownedTracks.length === 0 || polls > 24) {
          clearInterval(pollInterval);
        }
      }, 5000);
      setTimeout(() => (downloadMissingMsg = null), 6000);
    } catch (e) {
      downloadMissingMsg = `Download failed: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      downloadingMissing = false;
    }
  }

  async function checkDuplicates() {
    checkingDuplicates = true;
    try {
      const res = await api.getPlaylistDuplicates(playlist.name);
      duplicatesList = res.duplicates || [];
      showDuplicatesModal = true;
      deduplicateMsg = null;
    } catch (e) {
      console.error("Failed to check duplicates:", e);
    } finally {
      checkingDuplicates = false;
    }
  }

  async function handleDeduplicate() {
    deduplicating = true;
    try {
      const res = await api.deduplicatePlaylist(playlist.name);
      deduplicateMsg = `Successfully removed ${res.removed_count} duplicate track(s).`;
      await loadTracks();
      setTimeout(() => {
        showDuplicatesModal = false;
      }, 1500);
    } catch (e) {
      deduplicateMsg = `Failed to deduplicate: ${e}`;
    } finally {
      deduplicating = false;
    }
  }

  // Rename
  let editing = $state(false);
  let draftName = $state("");
  let nameInput = $state<HTMLInputElement | null>(null);
  let renaming = $state(false);
  let renameError = $state<string | null>(null);

  // Pause/resume
  let togglingPause = $state(false);

  // Delete
  let confirmDelete = $state(false);
  let deleting = $state(false);

  async function deletePlaylist() {
    deleting = true;
    try {
      await api.deletePlaylist(playlist.name);
      ondeleted(playlist.name);
    } catch {}
    finally { deleting = false; }
  }

  // Sort
  type SortKey = "artist" | "album" | "title" | "downloaded_at";
  let sortKey = $state<SortKey>("artist");
  let sortAsc = $state(true);

  let sorted = $derived(
    [...tracks].sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    })
  );


  async function loadTracks() {
    loadingTracks = true;
    tracksError = null;
    try {
      tracks = await api.playlistTracks(playlist.name);
    } catch (e) {
      tracksError = String(e);
    } finally {
      loadingTracks = false;
    }
  }

  onMount(() => {
    loadTracks();
    loadHistory();
  });

  async function startEditing() {
    draftName = playlist.name;
    renameError = null;
    editing = true;
    await tick();
    nameInput?.focus();
    nameInput?.select();
  }

  async function commitRename() {
    const trimmed = draftName.trim();
    if (!trimmed || trimmed === playlist.name) {
      editing = false;
      return;
    }
    renaming = true;
    renameError = null;
    try {
      const updated = await api.patchPlaylist(playlist.name, { name: trimmed });
      onrenamed(playlist.name, trimmed);
      onupdated(updated);
      editing = false;
    } catch (e) {
      renameError = String(e);
    } finally {
      renaming = false;
    }
  }

  function onNameKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") commitRename();
    if (e.key === "Escape") { editing = false; draftName = playlist.name; }
  }

  // Strawberry export
  let hasStrawberry = $state(false);
  let exporting = $state(false);
  let exportingM3u = $state(false);
  let exportMsg = $state<{ kind: "ok" | "err"; text: string } | null>(null);
  let exportMsgTimer: ReturnType<typeof setTimeout> | null = null;

  onMount(async () => {
    try {
      const h = await api.getIntegrationsHealth();
      hasStrawberry = !!h.strawberry;
    } catch {}
  });

  async function exportToStrawberry() {
    exporting = true;
    exportMsg = null;
    if (exportMsgTimer) clearTimeout(exportMsgTimer);
    try {
      const r = await api.strawberryExport(playlist.name);
      exportMsg = { kind: "ok", text: `Sent ${r.inserted} tracks to Strawberry` };
    } catch (e) {
      exportMsg = { kind: "err", text: String(e instanceof Error ? e.message : e) };
    } finally {
      exporting = false;
      exportMsgTimer = setTimeout(() => (exportMsg = null), 6000);
    }
  }

  async function exportM3u(openInPlayer = false) {
    exportingM3u = true;
    exportMsg = null;
    if (exportMsgTimer) clearTimeout(exportMsgTimer);
    try {
      const path = await save({
        title: "Export playlist",
        defaultPath: `${playlist.name}.m3u8`,
        filters: [{ name: "M3U playlists", extensions: ["m3u8", "m3u"] }],
      });
      if (path) {
        await api.savePlaylistM3u(playlist.name, path);
        if (openInPlayer) {
          await openPath(path);
          exportMsg = { kind: "ok", text: "M3U playlist opened in your default player" };
        } else {
          exportMsg = { kind: "ok", text: "M3U playlist saved" };
        }
      }
    } catch (e) {
      exportMsg = { kind: "err", text: String(e instanceof Error ? e.message : e) };
    } finally {
      exportingM3u = false;
      exportMsgTimer = setTimeout(() => (exportMsg = null), 6000);
    }
  }

  async function togglePause() {
    togglingPause = true;
    try {
      const updated = await api.patchPlaylist(playlist.name, { paused: !playlist.paused });
      onupdated(updated);
    } catch {}
    finally { togglingPause = false; }
  }

  function setSort(key: SortKey) {
    if (sortKey === key) sortAsc = !sortAsc;
    else { sortKey = key; sortAsc = true; }
  }

  // ── Sync history ────────────────────────────────────────────────────────────
  let runHistory = $state<SyncRun[]>([]);

  async function loadHistory() {
    try {
      runHistory = await api.syncHistory(playlist.name, 10);
    } catch {}
  }

  function formatDuration(start: string, end: string): string {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 1000) return "<1s";
    if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
    return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
  }

  function formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  function formatSyncDate(iso: string | null): string {
    if (!iso) return "Never";
    const d = new Date(iso);
    const diffH = (Date.now() - d.getTime()) / 3_600_000;
    if (diffH < 1) return "Less than an hour ago";
    if (diffH < 24) return `${Math.floor(diffH)}h ago`;
    if (diffH < 48) return "Yesterday";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  const COLS: { key: SortKey; label: string }[] = [
    { key: "title",        label: "Title" },
    { key: "artist",       label: "Artist" },
    { key: "album",        label: "Album" },
    { key: "downloaded_at", label: "Downloaded" },
  ];

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  // First 4 distinct artwork URLs for the mosaic header
  let mosaicArts = $derived(() => {
    const seen = new Set<string>();
    const result: (string | null)[] = [];
    for (const t of tracks) {
      if (result.length >= 4) break;
      const key = t.artwork_url ?? "";
      if (!seen.has(key)) {
        seen.add(key);
        result.push(t.artwork_url ?? null);
      }
    }
    while (result.length < 4) result.push(null);
    return result;
  });
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div style="padding:18px 24px 14px;border-bottom:1px solid var(--border);flex-shrink:0;position:relative;overflow:hidden;">
    <!-- Blurred art backdrop (bold) -->
    {#if mosaicArts().some(a => a)}
      <div style="position:absolute;inset:0;display:grid;grid-template-columns:repeat(4,1fr);z-index:0;pointer-events:none;" aria-hidden="true">
        {#each mosaicArts() as art}
          {#if art}
            <div style="background:url('{thumbUrl(art, '400x400')}') center/cover;filter:blur(44px) brightness(0.7) saturate(1.0);transform:scale(1.4);"></div>
          {:else}
            <div style="background:#12100e;"></div>
          {/if}
        {/each}
      </div>
      <!-- Gradient veil for legibility -->
      <div aria-hidden="true" style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(21,19,28,0.3) 0%,rgba(21,19,28,0.65) 65%,var(--bg) 100%);z-index:0;pointer-events:none;"></div>
    {/if}
    <div style="display:flex;align-items:flex-end;gap:16px;position:relative;z-index:1;">

      <!-- 2×2 mosaic -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px;width:96px;height:96px;border-radius:11px;overflow:hidden;flex-shrink:0;box-shadow:0 6px 22px rgba(0,0,0,0.7);">
        {#each mosaicArts() as art}
          {#if art}
            <img src={thumbUrl(art, "144x144")} alt="" style="width:100%;height:100%;object-fit:cover;"
              onerror={e => { const el = e.currentTarget as HTMLImageElement; el.style.display='none'; el.parentElement!.style.background='#1e1e1e'; }} />
          {:else}
            <div style="background:#1e1e1e;"></div>
          {/if}
        {/each}
      </div>

      <!-- Playlist info -->
      <div style="flex:1;min-width:0;">
        <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:2px;">Playlist</div>

        {#if editing}
          <div style="display:flex;align-items:center;gap:8px;">
            <input
              bind:this={nameInput}
              bind:value={draftName}
              onkeydown={onNameKeydown}
              onblur={commitRename}
              disabled={renaming}
              style="background:#1a1a1a;border:1px solid var(--accent);border-radius:6px;padding:4px 10px;color:white;font-size:20px;font-weight:700;outline:none;width:100%;max-width:280px;"
            />
            {#if renaming}<span style="color:var(--text-muted);font-size:12px;">Saving…</span>{/if}
          </div>
          {#if renameError}<div style="color:#f87171;font-size:11px;margin-top:2px;">{renameError}</div>{/if}
        {:else}
          <div class="group" style="display:flex;align-items:center;gap:6px;">
            <h1 style="color:var(--text-primary);font-size:30px;font-weight:800;letter-spacing:-.02em;margin:0;line-height:1.05;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-shadow:0 2px 12px rgba(0,0,0,0.5);">{playlist.name}</h1>
            <button onclick={startEditing} class="opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100" style="color:var(--text-muted);font-size:13px;background:transparent;border:none;cursor:pointer;" title="Rename" aria-label="Rename playlist">✎</button>
          </div>
        {/if}

        <div style="display:flex;align-items:center;gap:10px;margin-top:4px;font-size:12px;color:var(--text-secondary);">
          <span>{tracks.length.toLocaleString()} tracks</span>
          <span style="color:var(--text-muted);">·</span>
          <span>Last sync: {formatSyncDate(playlist.last_synced)}</span>
          {#if playlist.paused}
            <span style="color:var(--accent);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.05em;">paused</span>
          {/if}
        </div>
      </div>

      <!-- Actions -->
      <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
        {#if confirmDelete}
          <span style="font-size:12px;color:var(--text-muted);">Remove playlist?</span>
          <button onclick={deletePlaylist} disabled={deleting}
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(127,29,29,.4);color:#f87171;border:1px solid rgba(127,29,29,.5);cursor:pointer;opacity:{deleting?'.4':'1'}">
            {deleting ? "Removing…" : "Confirm"}
          </button>
          <button onclick={() => (confirmDelete = false)}
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:#1a1a1a;color:var(--text-secondary);border:1px solid #2a2a2a;cursor:pointer;">
            Cancel
          </button>
        {:else}
          <button onclick={() => (confirmDelete = true)}
            style="padding:6px 10px;border-radius:6px;font-size:11px;background:#1a1a1a;color:#555;border:1px solid #2a2a2a;cursor:pointer;">✕</button>
          <button onclick={togglePause} disabled={togglingPause}
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;opacity:{togglingPause?'.4':'1'};
              {playlist.paused
                ? 'background:rgba(180,83,9,.3);color:#f59e0b;border:1px solid rgba(180,83,9,.4);'
                : 'background:#1a1a1a;color:var(--text-secondary);border:1px solid #2a2a2a;'}">
            {playlist.paused ? "▶ Resume" : "⏸ Pause"}
          </button>
          <button onclick={checkDuplicates} disabled={checkingDuplicates} title="Check for duplicate tracks in this playlist"
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(252,211,77,0.08);color:var(--accent);border:1px solid rgba(252,211,77,0.2);cursor:pointer;opacity:{checkingDuplicates?'.5':'1'};">
            {checkingDuplicates ? "…" : "🔍 Check Duplicates"}
          </button>
          <button onclick={() => (showDapModal = true)} title="Export and transcode playlist to DAP or portable player"
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(252,211,77,0.12);color:var(--accent);border:1px solid rgba(252,211,77,0.25);cursor:pointer;">
            📱 Export to DAP
          </button>
          <button onclick={() => exportM3u()} disabled={exportingM3u} title="Export a portable playlist file"
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:#1a1a1a;color:var(--text-secondary);border:1px solid #2a2a2a;cursor:pointer;opacity:{exportingM3u?'.5':'1'};">
            {exportingM3u ? "…" : "⇩ M3U"}
          </button>
          <button onclick={() => exportM3u(true)} disabled={exportingM3u} title="Save then open in your default player"
            style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(163,230,53,.12);color:#bef264;border:1px solid rgba(163,230,53,.25);cursor:pointer;opacity:{exportingM3u?'.5':'1'};">
            {exportingM3u ? "…" : "▶ Player"}
          </button>
          {#if hasStrawberry}
            <button onclick={exportToStrawberry} disabled={exporting} title="Replace this playlist in Strawberry"
              style="padding:6px 12px;border-radius:6px;font-size:11px;font-weight:600;background:rgba(196,181,253,0.12);color:var(--accent-2);border:1px solid rgba(196,181,253,0.25);cursor:pointer;opacity:{exporting?'.5':'1'};">
              {exporting ? "…" : "🍓 Strawberry"}
            </button>
          {/if}
          {#if unownedTracks.length > 0}
            <button onclick={handleDownloadMissingTracks} disabled={downloadingMissing} title="Download unowned / AI curated tracks in this playlist"
              style="padding:6px 14px;border-radius:6px;font-size:11px;font-weight:700;background:rgba(252,211,77,0.15);color:var(--accent);border:1px solid rgba(252,211,77,0.35);cursor:pointer;opacity:{downloadingMissing?'.5':'1'};">
              {downloadingMissing ? "Queuing…" : `⚡ Download Missing (${unownedTracks.length})`}
            </button>
          {/if}
          <button onclick={() => onstartSync(playlist.name)} disabled={playlist.paused}
            style="padding:6px 16px;border-radius:6px;font-size:11px;font-weight:700;background:var(--accent);color:black;border:none;cursor:pointer;opacity:{playlist.paused?'.4':'1'};">
            ↻ Sync
          </button>
        {/if}
      </div>
    </div>
    {#if downloadMissingMsg}
      <div style="position:relative;z-index:1;margin-top:10px;padding:6px 10px;border-radius:6px;font-size:11px;background:rgba(252,211,77,0.1);color:var(--accent);border:1px solid rgba(252,211,77,0.25);">
        {downloadMissingMsg}
      </div>
    {/if}
    {#if exportMsg}
      <div style="position:relative;z-index:1;margin-top:10px;padding:6px 10px;border-radius:6px;font-size:11px;
        {exportMsg.kind === 'ok' ? 'background:rgba(94,234,212,0.1);color:#5eead4;border:1px solid rgba(94,234,212,0.25);'
          : 'background:rgba(248,113,113,0.1);color:#f87171;border:1px solid rgba(248,113,113,0.25);'}">
        {exportMsg.text}
      </div>
    {/if}
  </div>

  {#if runHistory.length > 0}
    <div style="padding:10px 24px;border-bottom:1px solid var(--border);flex-shrink:0;">
      <div style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em;font-weight:600;margin-bottom:6px;">Sync History</div>
      <div style="display:flex;flex-direction:column;gap:4px;">
        {#each runHistory as run}
          <div style="display:flex;align-items:center;gap:8px;font-size:11px;">
            <span style="width:6px;height:6px;border-radius:50%;flex-shrink:0;background:{run.status === 'success' ? '#22c55e' : '#ef4444'};"></span>
            <span style="color:var(--text-secondary);width:100px;flex-shrink:0;">{formatSyncDate(run.started_at)}</span>
            {#if run.status === 'error'}
              <span style="color:#f87171;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{run.error_message ?? 'Error'}</span>
            {:else}
              <span style="color:var(--text-muted);">{run.new_count} new · {run.skipped_count} skipped{run.error_count > 0 ? ` · ${run.error_count} err` : ''}</span>
            {/if}
            <span style="color:#333;margin-left:auto;flex-shrink:0;">{formatDuration(run.started_at, run.ended_at)}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <div style="flex:1;overflow:auto;">
    {#if loadingTracks}
      <div style="display:flex;align-items:center;justify-content:center;height:120px;color:var(--text-muted);font-size:13px;gap:8px;">
        <span style="width:16px;height:16px;border:2px solid #333;border-top-color:var(--text-secondary);border-radius:50%;animation:spin 1s linear infinite;"></span>
        Loading tracks…
      </div>
    {:else if tracksError}
      <div style="padding:24px;color:#f87171;font-size:13px;">{tracksError}</div>
    {:else if tracks.length === 0}
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:180px;color:var(--text-muted);">
        <div style="font-size:13px;">No tracks downloaded yet</div>
        {#if !playlist.paused}
          <button onclick={() => onstartSync(playlist.name)}
            style="margin-top:10px;font-size:12px;color:var(--text-secondary);background:transparent;border:none;cursor:pointer;">
            Run a sync to populate this playlist →
          </button>
        {/if}
      </div>
    {:else}
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead style="position:sticky;top:0;background:#0e0c0a;border-bottom:1px solid var(--border);">
          <tr>
            <th style="width:36px;padding:8px 10px;text-align:left;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">#</th>
            <th style="width:36px;padding:8px 4px;"></th>
            {#each COLS as col}
              <th style="padding:8px 10px;text-align:left;">
                <button onclick={() => setSort(col.key)}
                  style="font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;background:transparent;border:none;cursor:pointer;
                    color:{sortKey === col.key ? 'var(--accent)' : 'var(--text-muted)'};">
                  {col.label}{sortKey === col.key ? (sortAsc ? " ↑" : " ↓") : ""}
                </button>
              </th>
            {/each}
            <th style="width:70px;padding:8px 10px;text-align:center;font-size:9px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Lyrics</th>
          </tr>
        </thead>
        <tbody>
          {#each sorted as track, i}
            <tr style="border-bottom:1px solid rgba(245,158,11,0.06);transition:background .12s;cursor:pointer;"
              title="Show file in file manager"
              onclick={() => { api.revealTrack(track.local_path).catch(e => console.error(e)); }}
              onmouseenter={e => { (e.currentTarget as HTMLElement).style.background='rgba(245,158,11,0.07)'; (e.currentTarget as HTMLElement).style.backdropFilter='blur(8px)'; }}
              onmouseleave={e => { (e.currentTarget as HTMLElement).style.background='transparent'; (e.currentTarget as HTMLElement).style.backdropFilter=''; }}>
              <td style="padding:6px 10px;color:var(--text-muted);font-size:11px;font-variant-numeric:tabular-nums;">{i + 1}</td>
              <td style="padding:6px 4px;">
                {#if track.artwork_url}
                  <img src={thumbUrl(track.artwork_url, "56x56")} alt=""
                    style="width:28px;height:28px;border-radius:4px;object-fit:cover;display:block;"
                    onerror={e => {
                      const img = e.currentTarget as HTMLImageElement;
                      img.onerror = () => { img.style.display='none'; (img.nextElementSibling as HTMLElement)!.style.display='block'; };
                      img.src = `/api/v1/tracks/cover?track_id=${encodeURIComponent(track.track_id)}`;
                    }} />
                  <div style="display:none;width:28px;height:28px;border-radius:4px;background:#1e1e1e;"></div>
                {:else}
                  <img src={`/api/v1/tracks/cover?track_id=${encodeURIComponent(track.track_id)}`} alt=""
                    style="width:28px;height:28px;border-radius:4px;object-fit:cover;display:block;"
                    onerror={e => { const el = e.currentTarget as HTMLImageElement; el.style.display='none'; (el.nextElementSibling as HTMLElement)!.style.display='block'; }} />
                  <div style="display:none;width:28px;height:28px;border-radius:4px;background:#1e1e1e;"></div>
                {/if}
              </td>
              <td style="padding:6px 10px;color:var(--text-primary);font-weight:500;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title={track.title}>{track.title}</td>
              <td style="padding:6px 10px;color:var(--text-secondary);max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title={track.artist}>{track.artist}</td>
              <td style="padding:6px 10px;color:var(--text-muted);max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title={track.album}>{track.album}</td>
              <td style="padding:6px 10px;color:#333;font-size:11px;white-space:nowrap;">{formatDate(track.downloaded_at)}</td>
              <td style="padding:6px 10px;text-align:center;">
                <button
                  type="button"
                  onclick={(e) => { e.stopPropagation(); activeLyricsTrack = track; }}
                  title={track.has_lyrics ? "View synchronized lyrics (.lrc)" : "View / fetch lyrics"}
                  style="padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;cursor:pointer;transition:all .15s;
                    {track.has_lyrics
                      ? 'background:rgba(252,211,77,0.15);color:var(--accent);border:1px solid rgba(252,211,77,0.3);'
                      : 'background:rgba(255,255,255,0.04);color:var(--text-muted);border:1px solid var(--border);'}"
                >
                  {#if track.has_lyrics}
                    🎤 LRC
                  {:else}
                    🎤
                  {/if}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

{#if showDapModal}
  <DapExportModal
    playlistName={playlist.name}
    trackCount={tracks.length}
    onclose={() => (showDapModal = false)}
  />
{/if}

{#if activeLyricsTrack}
  <LyricsModal
    track={activeLyricsTrack}
    onclose={() => (activeLyricsTrack = null)}
  />
{/if}

{#if showDuplicatesModal}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    style="background:rgba(0,0,0,0.8);backdrop-filter:blur(8px);"
    role="dialog"
    aria-modal="true"
  >
    <div
      class="w-full max-w-lg rounded-2xl border p-6 shadow-2xl space-y-4"
      style="background:#121016;border-color:var(--border);color:var(--text-primary);"
    >
      <div class="flex items-center justify-between">
        <h3 class="text-base font-bold text-white flex items-center gap-2">
          <span>🔍 Playlist Duplicate Check</span>
        </h3>
        <button
          onclick={() => (showDuplicatesModal = false)}
          class="text-zinc-400 hover:text-white text-sm"
        >
          ✕
        </button>
      </div>

      {#if duplicatesList.length === 0}
        <div class="py-6 text-center text-zinc-400 space-y-2">
          <div class="text-2xl">✨</div>
          <div class="font-semibold text-white">No duplicates found!</div>
          <div class="text-xs text-zinc-500">Every track in &ldquo;{playlist.name}&rdquo; is unique.</div>
        </div>
        <div class="flex justify-end pt-2">
          <button
            onclick={() => (showDuplicatesModal = false)}
            class="px-4 py-2 rounded-lg text-xs font-semibold bg-zinc-800 text-white hover:bg-zinc-700"
          >
            Close
          </button>
        </div>
      {:else}
        <div class="space-y-3">
          <p class="text-xs text-zinc-300">
            Found <span class="text-amber-400 font-bold">{duplicatesList.length}</span> duplicate track groups in this playlist:
          </p>

          <div class="max-h-56 overflow-y-auto space-y-2 pr-1">
            {#each duplicatesList as dup}
              <div class="p-3 rounded-lg bg-black/40 border border-zinc-800 flex items-center justify-between">
                <div class="min-w-0 flex-1">
                  <div class="text-xs font-semibold text-white truncate">{dup.title}</div>
                  <div class="text-[11px] text-zinc-400 truncate">{dup.artist} &middot; {dup.album}</div>
                </div>
                <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {dup.count} copies
                </span>
              </div>
            {/each}
          </div>

          {#if deduplicateMsg}
            <div class="p-2.5 rounded-lg text-xs bg-green-950/40 border border-green-500/30 text-green-400">
              {deduplicateMsg}
            </div>
          {/if}

          <div class="flex items-center justify-end gap-3 pt-3 border-t border-zinc-800">
            <button
              onclick={() => (showDuplicatesModal = false)}
              class="px-4 py-2 rounded-lg text-xs font-medium text-zinc-400 hover:text-white bg-transparent"
            >
              Keep All
            </button>
            <button
              onclick={handleDeduplicate}
              disabled={deduplicating}
              class="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-500 hover:bg-amber-400 text-black shadow-lg"
            >
              {deduplicating ? "Removing…" : "Remove Duplicates (Keep First)"}
            </button>
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}
