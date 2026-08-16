<script lang="ts">
  import { api, type GeminiPlaylistResult } from "../api";
  import { player } from "./player.svelte";

  let prompt = $state("");
  let trackCount = $state(20);
  let curating = $state(false);
  let error = $state<string | null>(null);
  let result = $state<GeminiPlaylistResult | null>(null);

  async function handleCurate() {
    if (!prompt.trim()) return;
    curating = true;
    error = null;
    try {
      result = await api.curateGemini(prompt.trim(), trackCount);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      curating = false;
    }
  }

  function playPreview(title: string, artist: string) {
    player.playTrack({
      track_id: "preview-" + Math.random(),
      title,
      artist,
      album: "Gemini Curated",
      local_path: "",
    });
  }
</script>

<div class="p-8 max-w-4xl mx-auto h-full overflow-y-auto space-y-6">
  <!-- Header -->
  <div>
    <div class="flex items-center gap-2">
      <h1 class="text-2xl font-bold text-white tracking-tight">Gemini AI Music Intelligence</h1>
      <span class="text-[10px] px-2 py-0.5 rounded font-mono font-bold bg-amber-400/20 text-amber-300 border border-amber-400/30">
        AI Curator
      </span>
    </div>
    <p class="text-xs text-zinc-400 mt-1">
      Describe your vibe, setting, or aesthetic in natural language. Gemini constructs intelligent thematic tracklists resolved against the Apple Lossless catalog.
    </p>
  </div>

  <!-- Prompt Box -->
  <div class="p-6 rounded-2xl border space-y-4 shadow-xl" style="background:var(--surface);border-color:var(--border);">
    <div class="space-y-2">
      <label for="gemini-curator-prompt" class="text-xs font-semibold text-zinc-300">Natural Language Prompt</label>
      <textarea
        id="gemini-curator-prompt"
        bind:value={prompt}
        rows="3"
        placeholder="e.g., A moody 80s late-night cyberpunk rain mix with ethereal synths, heavy bass, and driving electronic percussion..."
        class="w-full p-4 rounded-xl text-xs bg-black/40 border outline-none text-white focus:border-amber-400 resize-none"
        style="border-color:var(--border);"
      ></textarea>
    </div>

    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <label for="gemini-track-count-range" class="text-xs text-zinc-400">Target tracks:</label>
        <input
          id="gemini-track-count-range"
          type="range"
          min="5"
          max="30"
          bind:value={trackCount}
          class="w-28 h-1 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-amber-400"
        />
        <span class="text-xs font-bold text-white min-w-[24px]">{trackCount}</span>
      </div>

      <button
        onclick={handleCurate}
        disabled={curating || !prompt.trim()}
        class="px-6 py-2.5 rounded-xl font-bold text-xs bg-amber-400 hover:bg-amber-300 text-black transition-colors disabled:opacity-50 shadow-lg"
      >
        {curating ? "Generating Mix with Gemini…" : "✨ Generate Lossless Playlist"}
      </button>
    </div>

    {#if error}
      <div class="p-4 rounded-xl bg-red-950/40 border border-red-900 text-red-300 text-xs">
        {error}
      </div>
    {/if}
  </div>

  <!-- Results View -->
  {#if result}
    <div class="p-6 rounded-2xl border space-y-6" style="background:var(--surface);border-color:var(--border);">
      <div class="flex flex-col gap-2">
        <h2 class="text-lg font-bold text-white">{result.playlist_title}</h2>
        <p class="text-xs text-zinc-300 leading-relaxed">{result.description}</p>
        <div class="flex flex-wrap gap-1.5 mt-1">
          {#each (result.vibe_tags || []) as tag}
            <span class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-amber-400/10 text-amber-300 border border-amber-400/20">
              #{tag}
            </span>
          {/each}
        </div>
      </div>

      <!-- Tracks list -->
      <div class="border rounded-xl overflow-hidden divide-y" style="border-color:var(--border);">
        {#each (result.tracks || []) as track, idx}
          <div class="p-3.5 flex items-center justify-between text-xs hover:bg-white/[0.03] transition-colors">
            <div class="flex items-center gap-3 min-w-0 pr-4">
              <span class="text-zinc-500 font-mono text-[10px] w-4 text-right">{idx + 1}</span>
              <div class="min-w-0">
                <div class="font-semibold text-white truncate">{track.title}</div>
                <div class="text-zinc-400 text-[11px] truncate">{track.artist} <span class="text-zinc-600">—</span> {track.album}</div>
                {#if track.rationale}
                  <div class="text-amber-200/60 text-[10px] italic mt-0.5 truncate">{track.rationale}</div>
                {/if}
              </div>
            </div>

            <div class="flex items-center gap-2 flex-shrink-0">
              {#if track.matched}
                <span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                  Lossless Match
                </span>
              {/if}
              <button
                onclick={() => playPreview(track.title, track.artist)}
                class="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold"
              >
                ▶ Play
              </button>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
