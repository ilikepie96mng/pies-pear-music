<script lang="ts">
  import { onMount } from "svelte";
  import { api, type GeminiPlaylistResult } from "../api";
  import { player } from "./player.svelte";

  let prompt = $state("");
  let trackCount = $state(20);
  let availableModels = $state<string[]>([]);
  let selectedModel = $state("gemini-2.5-flash");
  let customModel = $state("");
  let curating = $state(false);
  let loadingModels = $state(false);
  let error = $state<string | null>(null);
  let result = $state<GeminiPlaylistResult | null>(null);

  onMount(async () => {
    loadingModels = true;
    try {
      const models = await api.getGeminiModels();
      if (models && models.length > 0) {
        availableModels = models;
        // Default to the first (cheapest / most cost-effective) model
        if (!selectedModel || !models.includes(selectedModel)) {
          selectedModel = models[0];
        }
      }
    } catch {
      // Fallback to defaults
      availableModels = [
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-flash",
        "gemini-2.5-pro",
      ];
    } finally {
      loadingModels = false;
    }
  });

  async function handleCurate() {
    if (!prompt.trim()) return;
    curating = true;
    error = null;
    const modelToUse = selectedModel === "custom" ? customModel.trim() : selectedModel;
    try {
      result = await api.curateGemini(prompt.trim(), trackCount, modelToUse || undefined);
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
        placeholder="e.g., A moody late-night indie rock & post-punk mix with heavy basslines and driving drums..."
        class="w-full p-4 rounded-xl text-xs bg-black/50 border outline-none text-white focus:border-amber-400 resize-none placeholder:text-zinc-500"
        style="border-color:var(--border);"
      ></textarea>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-4 pt-3 border-t" style="border-color:var(--border);">
      <div class="flex flex-wrap items-center gap-4">
        <div class="flex items-center gap-2">
          <label for="gemini-model-select" class="text-xs text-zinc-300 font-semibold">Model:</label>
          <select
            id="gemini-model-select"
            bind:value={selectedModel}
            style="background:#111116;color:#ffffff;border:1px solid rgba(255,255,255,0.2);"
            class="px-3 py-1.5 rounded-lg text-xs font-medium outline-none focus:border-amber-400 cursor-pointer"
          >
            {#if availableModels.length > 0}
              {#each availableModels as m}
                <option value={m} style="background:#111116;color:#ffffff;">
                  {m} {#if m.includes('flash') || m.includes('lite')}(Cheapest & Fast){:else if m.includes('pro')}(Deep Analysis){/if}
                </option>
              {/each}
            {:else}
              <option value="gemini-2.5-flash" style="background:#111116;color:#ffffff;">gemini-2.5-flash</option>
              <option value="gemini-2.0-flash-lite" style="background:#111116;color:#ffffff;">gemini-2.0-flash-lite (Lowest Cost)</option>
              <option value="gemini-2.0-flash" style="background:#111116;color:#ffffff;">gemini-2.0-flash</option>
              <option value="gemini-1.5-flash" style="background:#111116;color:#ffffff;">gemini-1.5-flash</option>
            {/if}
            <option value="custom" style="background:#111116;color:#ffffff;">Custom Model Name…</option>
          </select>
        </div>

        {#if selectedModel === "custom"}
          <input
            type="text"
            bind:value={customModel}
            placeholder="e.g. gemini-2.0-flash-lite"
            style="background:#111116;color:#ffffff;border:1px solid rgba(255,255,255,0.2);"
            class="px-3 py-1.5 rounded-lg text-xs outline-none focus:border-amber-400 w-44"
          />
        {/if}

        <div class="flex items-center gap-2">
          <label for="gemini-track-count-range" class="text-xs text-zinc-300 font-semibold">Target tracks:</label>
          <input
            id="gemini-track-count-range"
            type="range"
            min="5"
            max="30"
            bind:value={trackCount}
            class="w-24 h-1.5 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-amber-400"
          />
          <span class="text-xs font-bold text-amber-300 min-w-[20px]">{trackCount}</span>
        </div>
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
