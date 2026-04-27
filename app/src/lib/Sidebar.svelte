<script lang="ts">
  import { api, type Playlist } from "../api";
  import QueueIndicator from "./QueueIndicator.svelte";
  import { onMount } from "svelte";

  interface Props {
    playlists: Playlist[];
    selectedName: string | null;
    onselectPlaylist: (name: string) => void;
    onstartSync: (name: string) => void;
    onopenSettings: () => void;
    onopenSetup: () => void;
    onopenDiagnostics: () => void;
    onopenDashboard: () => void;
    onopenDownload: () => void;
    onplaylistAdded: (pl: Playlist) => void;
  }

  let {
    playlists, selectedName,
    onselectPlaylist, onstartSync,
    onopenSettings, onopenSetup, onopenDiagnostics, onopenDashboard, onopenDownload,
    onplaylistAdded,
  }: Props = $props();

  let showAddForm = $state(false);
  let newName = $state("");
  let newUrl = $state("");
  let adding = $state(false);
  let addError = $state<string | null>(null);

  let wrapperRunning = $state<boolean | null>(null);

  async function pollWrapperStatus() {
    try {
      const s = await api.wrapper.status();
      wrapperRunning = s.running;
    } catch {
      wrapperRunning = false;
    }
  }

  onMount(() => {
    pollWrapperStatus();
    const interval = setInterval(pollWrapperStatus, 10_000);
    return () => clearInterval(interval);
  });

  function thumbUrl(url: string | null | undefined, size: string): string {
    if (!url) return "";
    return url.replace("{w}x{h}", size);
  }

  async function addPlaylist() {
    if (!newName.trim() || !newUrl.trim()) return;
    adding = true;
    addError = null;
    try {
      const pl = await api.addPlaylist(newName.trim(), newUrl.trim());
      onplaylistAdded(pl);
      newName = "";
      newUrl = "";
      showAddForm = false;
      onselectPlaylist(pl.name);
    } catch (e) {
      addError = String(e);
    } finally {
      adding = false;
    }
  }


</script>

<aside style="width:180px;min-width:180px;background:var(--bg);display:flex;flex-direction:column;border-right:1px solid var(--border);">
  <!-- Logo -->
  <div style="padding:16px;border-bottom:1px solid var(--border);">
    <div style="color:var(--accent);font-weight:700;font-size:15px;letter-spacing:.02em;">pies</div>
  </div>

  <!-- Nav -->
  <nav style="padding:8px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:2px;">
    {#each [
      { label: "▦ Dashboard", action: onopenDashboard },
      { label: "⊕ Diagnostics", action: onopenDiagnostics },
      { label: "⚙ Settings", action: onopenSettings },
      { label: "◆ Setup", action: onopenSetup },
      { label: "↓ Download", action: onopenDownload },
    ] as item}
      <button
        onclick={item.action}
        style="width:100%;text-align:left;padding:6px 10px;border-radius:6px;font-size:13px;color:var(--text-secondary);background:transparent;border:none;cursor:pointer;transition:color .15s,background .15s;"
        onmouseenter={e => { (e.currentTarget as HTMLElement).style.color='var(--text-primary)'; (e.currentTarget as HTMLElement).style.background='var(--surface)'; }}
        onmouseleave={e => { (e.currentTarget as HTMLElement).style.color='var(--text-secondary)'; (e.currentTarget as HTMLElement).style.background='transparent'; }}
      >{item.label}</button>
    {/each}
  </nav>

  <!-- Playlists label -->
  <div style="padding:10px 12px 4px;font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em;">Playlists</div>

  <!-- Playlist list -->
  <div style="flex:1;overflow-y:auto;padding:0 8px;display:flex;flex-direction:column;gap:2px;">
    {#each playlists as pl}
      <button
        onclick={() => onselectPlaylist(pl.name)}
        type="button"
        style="width:100%;text-align:left;padding:4px 6px;border-radius:6px;font-size:13px;display:flex;align-items:center;gap:6px;border:none;cursor:pointer;transition:color .15s,background .15s;
          {selectedName === pl.name
            ? 'background:var(--accent-dim);color:var(--accent);border-left:2px solid var(--accent);padding-left:4px;'
            : 'background:transparent;color:var(--text-secondary);'}"
        onmouseenter={e => { if (selectedName !== pl.name) { (e.currentTarget as HTMLElement).style.color='var(--text-primary)'; (e.currentTarget as HTMLElement).style.background='var(--surface)'; } }}
        onmouseleave={e => { if (selectedName !== pl.name) { (e.currentTarget as HTMLElement).style.color='var(--text-secondary)'; (e.currentTarget as HTMLElement).style.background='transparent'; } }}
      >
        {#if pl.thumbnail_url}
          <img
            src={thumbUrl(pl.thumbnail_url, "36x36bb")}
            alt=""
            style="width:18px;height:18px;border-radius:3px;flex-shrink:0;object-fit:cover;"
            onerror={e => { (e.currentTarget as HTMLImageElement).style.display='none'; }}
          />
        {:else}
          <div style="width:18px;height:18px;border-radius:3px;flex-shrink:0;background:#1e1e1e;"></div>
        {/if}
        {#if pl.paused}
          <span style="color:#b45309;font-size:9px;flex-shrink:0;">⏸</span>
        {/if}
        <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{pl.name}</span>
      </button>
    {/each}

    {#if showAddForm}
      <div style="padding:4px;display:flex;flex-direction:column;gap:4px;">
        <input bind:value={newName} placeholder="Name"
          style="background:#1a1a1a;border:1px solid #333;border-radius:4px;padding:4px 8px;font-size:11px;color:white;width:100%;outline:none;box-sizing:border-box;" />
        <input bind:value={newUrl} placeholder="Playlist URL"
          style="background:#1a1a1a;border:1px solid #333;border-radius:4px;padding:4px 8px;font-size:11px;color:white;width:100%;outline:none;box-sizing:border-box;" />
        {#if addError}
          <div style="color:#f87171;font-size:10px;background:rgba(127,29,29,.5);border:1px solid rgba(127,29,29,.6);border-radius:4px;padding:4px 8px;word-break:break-all;">{addError}</div>
        {/if}
        <div style="display:flex;gap:4px;">
          <button onclick={addPlaylist} disabled={adding}
            style="flex:1;background:var(--accent);color:black;font-size:11px;font-weight:700;border:none;border-radius:4px;padding:4px;cursor:pointer;opacity:{adding?'.5':'1'}">
            {adding ? "…" : "Add"}
          </button>
          <button onclick={() => { showAddForm = false; addError = null; }}
            style="flex:1;background:#1a1a1a;color:var(--text-secondary);font-size:11px;border:none;border-radius:4px;padding:4px;cursor:pointer;">Cancel</button>
        </div>
      </div>
    {:else}
      <button onclick={() => (showAddForm = true)}
        style="width:100%;text-align:left;padding:6px 10px;font-size:13px;color:var(--text-muted);background:transparent;border:none;cursor:pointer;transition:color .15s;"
        onmouseenter={e => { (e.currentTarget as HTMLElement).style.color='var(--text-primary)'; }}
        onmouseleave={e => { (e.currentTarget as HTMLElement).style.color='var(--text-muted)'; }}
        >+ Add playlist</button>
    {/if}
  </div>

  <QueueIndicator />

  <!-- Connection status -->
  <div style="padding:8px 12px;border-top:1px solid var(--border);display:flex;align-items:center;gap:8px;">
    {#if wrapperRunning === null}
      <span style="width:8px;height:8px;border-radius:50%;background:#444;flex-shrink:0;"></span>
      <span style="font-size:10px;color:var(--text-muted);">Checking…</span>
    {:else if wrapperRunning}
      <span style="width:8px;height:8px;border-radius:50%;background:#22c55e;flex-shrink:0;"></span>
      <span style="font-size:10px;color:var(--text-secondary);">Apple Music</span>
    {:else}
      <span style="width:8px;height:8px;border-radius:50%;background:#444;flex-shrink:0;"></span>
      <span style="font-size:10px;color:var(--text-muted);">Not signed in</span>
    {/if}
  </div>

  <!-- Sync All -->
  <div style="padding:8px;border-top:1px solid var(--border);">
    <button
      onclick={() => { const first = playlists.find(p => !p.paused); if (first) onstartSync(first.name); }}
      disabled={playlists.every(p => p.paused)}
      style="width:100%;background:var(--accent);color:black;font-size:13px;font-weight:700;border:none;border-radius:8px;padding:8px;cursor:pointer;transition:background .15s;opacity:{playlists.every(p=>p.paused)?'.5':'1'};"
      onmouseenter={e => { (e.currentTarget as HTMLElement).style.background='var(--accent-hover)'; }}
      onmouseleave={e => { (e.currentTarget as HTMLElement).style.background='var(--accent)'; }}
    >↻ Sync All</button>
  </div>
</aside>
