<script lang="ts">
  import { onMount, tick } from "svelte";
  import { api, type Playlist, type Track, type SyncRun } from "../api";

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

  // Rename
  let editing = $state(false);
  let draftName = $state(playlist.name);
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
      const library = await api.library();
      tracks = library[playlist.name] ?? [];
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
  <div style="padding:20px 24px 16px;border-bottom:1px solid var(--border);flex-shrink:0;">
    <div style="display:flex;align-items:flex-end;gap:16px;">

      <!-- 2×2 mosaic -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px;width:72px;height:72px;border-radius:10px;overflow:hidden;flex-shrink:0;box-shadow:0 4px 16px rgba(0,0,0,0.4);">
        {#each mosaicArts() as art}
          {#if art}
            <img src={thumbUrl(art, "72x72bb")} alt="" style="width:100%;height:100%;object-fit:cover;"
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
          <div style="display:flex;align-items:center;gap:6px;"
            onmouseenter={e => { const btn = (e.currentTarget as HTMLElement).querySelector<HTMLElement>('[data-rename-btn]'); if (btn) btn.style.opacity='1'; }}
            onmouseleave={e => { const btn = (e.currentTarget as HTMLElement).querySelector<HTMLElement>('[data-rename-btn]'); if (btn) btn.style.opacity='0'; }}>
            <h1 style="color:var(--text-primary);font-size:22px;font-weight:700;letter-spacing:-.02em;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{playlist.name}</h1>
            <button onclick={startEditing} data-rename-btn style="opacity:0;color:var(--text-muted);font-size:13px;background:transparent;border:none;cursor:pointer;" title="Rename">✎</button>
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
          <button onclick={() => onstartSync(playlist.name)} disabled={playlist.paused}
            style="padding:6px 16px;border-radius:6px;font-size:11px;font-weight:700;background:var(--accent);color:black;border:none;cursor:pointer;opacity:{playlist.paused?'.4':'1'};">
            ↻ Sync
          </button>
        {/if}
      </div>
    </div>
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
          </tr>
        </thead>
        <tbody>
          {#each sorted as track, i}
            <tr style="border-bottom:1px solid rgba(255,255,255,0.03);"
              onmouseenter={e => { (e.currentTarget as HTMLElement).style.background='rgba(245,158,11,0.04)'; }}
              onmouseleave={e => { (e.currentTarget as HTMLElement).style.background='transparent'; }}>
              <td style="padding:6px 10px;color:var(--text-muted);font-size:11px;font-variant-numeric:tabular-nums;">{i + 1}</td>
              <td style="padding:6px 4px;">
                {#if track.artwork_url}
                  <img src={thumbUrl(track.artwork_url, "56x56bb")} alt=""
                    style="width:28px;height:28px;border-radius:4px;object-fit:cover;display:block;"
                    onerror={e => { const el = e.currentTarget as HTMLImageElement; el.style.display='none'; (el.nextElementSibling as HTMLElement)!.style.display='block'; }} />
                  <div style="display:none;width:28px;height:28px;border-radius:4px;background:#1e1e1e;"></div>
                {:else}
                  <div style="width:28px;height:28px;border-radius:4px;background:#1e1e1e;"></div>
                {/if}
              </td>
              <td style="padding:6px 10px;color:var(--text-primary);font-weight:500;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title={track.title}>{track.title}</td>
              <td style="padding:6px 10px;color:var(--text-secondary);max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title={track.artist}>{track.artist}</td>
              <td style="padding:6px 10px;color:var(--text-muted);max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title={track.album}>{track.album}</td>
              <td style="padding:6px 10px;color:#333;font-size:11px;white-space:nowrap;">{formatDate(track.downloaded_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>
