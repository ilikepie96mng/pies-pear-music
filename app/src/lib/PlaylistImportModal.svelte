<script lang="ts">
  import { api, type ImportMatchResult } from "../api";

  interface Props {
    onclose: () => void;
    onstartRip?: (matchedTracks: ImportMatchResult[]) => void;
  }

  let { onclose, onstartRip }: Props = $props();

  let mode = $state<"url" | "file">("url");
  let inputUrl = $state("");
  let fileContent = $state("");
  let fileType = $state<"csv" | "m3u">("csv");
  let fileName = $state("");

  let parsing = $state(false);
  let error = $state<string | null>(null);
  let parsedResults = $state<ImportMatchResult[] | null>(null);

  async function handleFileUpload(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    fileName = file.name;
    fileType = file.name.endsWith(".m3u") || file.name.endsWith(".m3u8") ? "m3u" : "csv";
    fileContent = await file.text();
  }

  async function parseImport() {
    parsing = true;
    error = null;
    try {
      if (mode === "url") {
        if (!inputUrl.trim()) throw new Error("Please enter a playlist URL");
        const res = await api.parsePlaylistImport("url", inputUrl.trim());
        parsedResults = res.matches;
      } else {
        if (!fileContent.trim()) throw new Error("Please select a file to import");
        const res = await api.parsePlaylistImport(fileType, fileContent.trim());
        parsedResults = res.matches;
      }
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      parsing = false;
    }
  }

  let matchedCount = $derived(parsedResults?.filter(r => r.matched).length ?? 0);
  let matchPercentage = $derived(
    parsedResults && parsedResults.length > 0
      ? Math.round((matchedCount / parsedResults.length) * 100)
      : 0
  );
</script>

<div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
  <div class="w-full max-w-3xl max-h-[85vh] rounded-2xl border flex flex-col overflow-hidden shadow-2xl" style="background:#14121a;border-color:var(--border);">
    <!-- Header -->
    <div class="p-5 border-b flex items-center justify-between" style="border-color:var(--border);background:rgba(255,255,255,0.02);">
      <div>
        <h2 class="text-base font-bold text-white flex items-center gap-2">
          <span>Universal Playlist Matcher</span>
          <span class="text-[10px] px-2 py-0.5 rounded font-mono bg-amber-400/20 text-amber-300">Match & Rip</span>
        </h2>
        <p class="text-xs text-zinc-400 mt-0.5">Import Spotify, Tidal, Qobuz, CSV, or M3U8 and resolve to Lossless Apple ALAC</p>
      </div>
      <button onclick={onclose} class="text-zinc-500 hover:text-white text-lg">✕</button>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-6 space-y-6">
      {#if !parsedResults}
        <!-- Step 1: Ingest input -->
        <div class="flex gap-2 p-1 rounded-xl bg-black/30 border max-w-sm" style="border-color:var(--border);">
          <button
            onclick={() => (mode = "url")}
            class="flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors {mode === 'url' ? 'bg-amber-400 text-black' : 'text-zinc-400 hover:text-white'}"
          >
            Share Link (Spotify / AM)
          </button>
          <button
            onclick={() => (mode = "file")}
            class="flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors {mode === 'file' ? 'bg-amber-400 text-black' : 'text-zinc-400 hover:text-white'}"
          >
            File Upload (CSV / M3U)
          </button>
        </div>

        {#if mode === "url"}
          <div class="space-y-2">
            <label for="pl-import-url" class="text-xs text-zinc-300 font-medium">Playlist Share URL</label>
            <input
              id="pl-import-url"
              bind:value={inputUrl}
              placeholder="https://open.spotify.com/playlist/... or https://music.apple.com/..."
              class="w-full px-4 py-2.5 rounded-xl text-xs bg-black/40 border outline-none text-white focus:border-amber-400"
              style="border-color:var(--border);"
            />
          </div>
        {:else}
          <div class="space-y-2">
            <span class="text-xs text-zinc-300 font-medium">Choose Playlist File</span>
            <label class="border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer hover:border-amber-400 transition-colors" style="border-color:var(--border);">
              <span class="text-2xl mb-2">📁</span>
              <span class="text-xs font-semibold text-white">{fileName || "Click to upload CSV or M3U file"}</span>
              <span class="text-[10px] text-zinc-500 mt-1">Supports Soundiiz, TuneMyMusic, and standard M3U8</span>
              <input type="file" accept=".csv,.m3u,.m3u8" onchange={handleFileUpload} class="hidden" />
            </label>
          </div>
        {/if}

        {#if error}
          <div class="p-3 rounded-xl bg-red-950/40 border border-red-900 text-red-300 text-xs">
            {error}
          </div>
        {/if}

        <button
          onclick={parseImport}
          disabled={parsing}
          class="w-full py-3 rounded-xl font-bold text-xs bg-amber-400 hover:bg-amber-300 text-black transition-colors disabled:opacity-50"
        >
          {parsing ? "Resolving and Matching Tracks…" : "Analyze & Match with Apple Music"}
        </button>
      {:else}
        <!-- Step 2: Confirmation & Ripping list -->
        <div class="p-4 rounded-xl flex items-center justify-between border" style="background:var(--surface);border-color:var(--border);">
          <div>
            <div class="text-sm font-bold text-white">Matched {matchedCount} of {parsedResults.length} tracks</div>
            <div class="text-xs text-zinc-400 mt-0.5">{matchPercentage}% resolved to Apple Music Lossless catalog</div>
          </div>
          <div class="w-16 h-16 rounded-full border-4 border-amber-400 flex items-center justify-center font-bold text-sm text-white">
            {matchPercentage}%
          </div>
        </div>

        <div class="border rounded-xl overflow-hidden divide-y max-h-80 overflow-y-auto" style="border-color:var(--border);">
          {#each parsedResults as item}
            <div class="p-3 flex items-center justify-between text-xs hover:bg-white/[0.02]">
              <div class="min-w-0 pr-4">
                <div class="font-semibold text-white truncate">{item.original_title}</div>
                <div class="text-zinc-400 text-[11px] truncate">{item.original_artist}</div>
              </div>
              <div class="flex items-center gap-2 flex-shrink-0">
                {#if item.matched && item.am_track}
                  <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                    Lossless ALAC Match
                  </span>
                {:else}
                  <span class="px-2 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-400">
                    Unmatched
                  </span>
                {/if}
              </div>
            </div>
          {/each}
        </div>

        <div class="flex gap-3">
          <button
            onclick={() => (parsedResults = null)}
            class="px-4 py-2.5 rounded-xl border text-xs font-semibold text-zinc-300 hover:text-white"
            style="border-color:var(--border);"
          >
            ← Back
          </button>
          <button
            onclick={() => { onstartRip?.(parsedResults || []); onclose(); }}
            class="flex-1 py-2.5 rounded-xl font-bold text-xs bg-amber-400 hover:bg-amber-300 text-black transition-colors"
          >
            Queue Matched Tracks for ALAC Rip ({matchedCount})
          </button>
        </div>
      {/if}
    </div>
  </div>
</div>
