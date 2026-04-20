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
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="px-8 pt-8 pb-5 border-b border-[#1a1a1a] flex-shrink-0">
    <div class="flex items-start justify-between gap-4">
      <!-- Name + rename -->
      <div class="flex-1 min-w-0">
        {#if editing}
          <div class="flex items-center gap-2">
            <input
              bind:this={nameInput}
              bind:value={draftName}
              onkeydown={onNameKeydown}
              onblur={commitRename}
              disabled={renaming}
              class="bg-[#1a1a1a] border border-amber-700 rounded-lg px-3 py-1.5 text-white text-xl font-bold outline-none w-full max-w-sm"
            />
            {#if renaming}
              <span class="text-zinc-500 text-sm">Saving…</span>
            {/if}
          </div>
          {#if renameError}
            <div class="text-red-400 text-xs mt-1">{renameError}</div>
          {/if}
        {:else}
          <div class="flex items-center gap-2 group">
            <h1 class="text-white text-2xl font-bold tracking-tight truncate">{playlist.name}</h1>
            <button
              onclick={startEditing}
              class="opacity-0 group-hover:opacity-100 transition-opacity text-zinc-600 hover:text-zinc-400 text-sm"
              title="Rename">✎</button>
          </div>
        {/if}

        <div class="flex items-center gap-4 mt-1.5 text-xs text-zinc-500">
          <span>{tracks.length.toLocaleString()} tracks</span>
          <span>·</span>
          <span>Last sync: {formatSyncDate(playlist.last_synced)}</span>
          {#if playlist.paused}
            <span class="text-amber-500 font-semibold uppercase tracking-wider">paused</span>
          {/if}
        </div>
        <div class="text-zinc-700 text-[10px] font-mono mt-1 truncate max-w-md" title={playlist.url}>{playlist.url}</div>

      </div>

      <!-- Actions -->
      <div class="flex items-center gap-2 flex-shrink-0">
        {#if confirmDelete}
          <span class="text-xs text-zinc-500 mr-1">Remove playlist?</span>
          <button
            onclick={deletePlaylist}
            disabled={deleting}
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors disabled:opacity-40
              bg-red-950/50 text-red-400 border border-red-900/50 hover:bg-red-950/80">
            {deleting ? "Removing…" : "Confirm"}
          </button>
          <button
            onclick={() => (confirmDelete = false)}
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors
              bg-[#1a1a1a] text-zinc-500 border border-[#2a2a2a] hover:text-white">
            Cancel
          </button>
        {:else}
          <button
            onclick={() => (confirmDelete = true)}
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors
              bg-[#1a1a1a] text-zinc-600 border border-[#2a2a2a] hover:text-red-400">
            ✕
          </button>
          <button
            onclick={togglePause}
            disabled={togglingPause}
            class="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors disabled:opacity-40
              {playlist.paused
                ? 'bg-amber-900/40 text-amber-400 border border-amber-800/50 hover:bg-amber-900/60'
                : 'bg-[#1a1a1a] text-zinc-400 border border-[#2a2a2a] hover:text-white'}">
            {playlist.paused ? "▶ Resume" : "⏸ Pause"}
          </button>
          <button
            onclick={() => onstartSync(playlist.name)}
            disabled={playlist.paused}
            class="px-4 py-1.5 rounded-lg text-xs font-bold transition-colors
              bg-[#1db954] text-black hover:bg-[#1ed760] disabled:opacity-40">
            ↻ Sync
          </button>
        {/if}
      </div>
    </div>
  </div>

  <!-- Sync run history -->
  {#if runHistory.length > 0}
    <div class="px-8 py-3 border-b border-[#1a1a1a] flex-shrink-0">
      <div class="text-zinc-600 text-[10px] uppercase tracking-widest font-semibold mb-2">Sync History</div>
      <div class="flex flex-col gap-1">
        {#each runHistory as run}
          <div class="flex items-center gap-2 text-xs">
            <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 {run.status === 'success' ? 'bg-green-500' : 'bg-red-500'}"></span>
            <span class="text-zinc-500 w-28 flex-shrink-0">{formatSyncDate(run.started_at)}</span>
            {#if run.status === 'error'}
              <span class="text-red-400 truncate">{run.error_message ?? 'Error'}</span>
            {:else}
              <span class="text-zinc-600">{run.new_count} new · {run.skipped_count} skipped{run.error_count > 0 ? ` · ${run.error_count} err` : ''}</span>
            {/if}
            <span class="text-zinc-700 ml-auto flex-shrink-0">{formatDuration(run.started_at, run.ended_at)}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Track table -->
  <div class="flex-1 overflow-auto">
    {#if loadingTracks}
      <div class="flex items-center justify-center h-32 text-zinc-600 text-sm gap-2">
        <span class="w-4 h-4 border border-zinc-700 border-t-zinc-400 rounded-full animate-spin"></span>
        Loading tracks…
      </div>
    {:else if tracksError}
      <div class="px-8 py-6 text-red-400 text-sm">{tracksError}</div>
    {:else if tracks.length === 0}
      <div class="flex flex-col items-center justify-center h-48 text-zinc-600">
        <div class="text-sm">No tracks downloaded yet</div>
        {#if !playlist.paused}
          <button onclick={() => onstartSync(playlist.name)}
            class="mt-3 text-xs text-zinc-500 hover:text-white transition-colors">
            Run a sync to populate this playlist →
          </button>
        {/if}
      </div>
    {:else}
      <table class="w-full text-sm border-collapse">
        <thead class="sticky top-0 bg-[#0f0f0f] border-b border-[#1e1e1e]">
          <tr>
            <th class="w-10 px-4 py-2.5 text-left text-[10px] text-zinc-600 font-semibold uppercase tracking-widest">#</th>
            {#each COLS as col}
              <th class="px-3 py-2.5 text-left">
                <button
                  onclick={() => setSort(col.key)}
                  class="text-[10px] font-semibold uppercase tracking-widest transition-colors
                    {sortKey === col.key ? 'text-amber-500' : 'text-zinc-600 hover:text-zinc-400'}">
                  {col.label}{sortKey === col.key ? (sortAsc ? " ↑" : " ↓") : ""}
                </button>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody class="divide-y divide-[#141414]">
          {#each sorted as track, i}
            <tr class="hover:bg-[#111] transition-colors group">
              <td class="px-4 py-2.5 text-zinc-700 text-xs tabular-nums">{i + 1}</td>
              <td class="px-3 py-2.5 text-white font-medium max-w-[200px] truncate" title={track.title}>{track.title}</td>
              <td class="px-3 py-2.5 text-zinc-400 max-w-[160px] truncate" title={track.artist}>{track.artist}</td>
              <td class="px-3 py-2.5 text-zinc-500 max-w-[160px] truncate" title={track.album}>{track.album}</td>
              <td class="px-3 py-2.5 text-zinc-600 text-xs whitespace-nowrap">{formatDate(track.downloaded_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>
