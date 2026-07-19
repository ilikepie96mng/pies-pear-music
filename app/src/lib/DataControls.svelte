<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  let hiddenArtists = $state<string[]>([]);
  let genres = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let message = $state<string | null>(null);

  onMount(async () => {
    try {
      const [artists, preferences] = await Promise.all([
        api.recommendationExclusions(),
        api.recommendationPreferences(),
      ]);
      hiddenArtists = artists;
      genres = preferences.genres.join(", ");
    } catch {
      message = "Could not load recommendation controls.";
    } finally {
      loading = false;
    }
  });

  async function exportProfile() {
    try {
      const profile = await api.libraryProfile();
      const url = URL.createObjectURL(new Blob([JSON.stringify(profile, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "pies-pear-music-library-profile.json";
      link.click();
      URL.revokeObjectURL(url);
      message = "Profile exported. It contains no file paths or credentials.";
    } catch {
      message = "Could not export the library profile.";
    }
  }

  async function saveGenres() {
    saving = true;
    message = null;
    try {
      const values = genres.split(",").map((value) => value.trim()).filter(Boolean);
      const saved = await api.updateRecommendationPreferences(values);
      genres = saved.genres.join(", ");
      message = "Genre preferences saved. Refresh Home to apply them.";
    } catch {
      message = "Could not save genre preferences. Use up to 10 short genre names.";
    } finally {
      saving = false;
    }
  }

  async function restoreArtist(artist: string) {
    await api.includeRecommendationArtist(artist);
    hiddenArtists = hiddenArtists.filter((value) => value !== artist);
  }

  async function clearHiddenArtists() {
    await api.clearRecommendationExclusions();
    hiddenArtists = [];
    message = "Hidden-artist list cleared.";
  }
</script>

<div class="h-full overflow-y-auto p-6 md:p-9" style="background:var(--bg);color:var(--text-primary);">
  <div class="max-w-3xl">
    <div class="mb-8">
      <div class="text-xs uppercase tracking-[0.2em]" style="color:var(--accent);">Library controls</div>
      <h1 class="mt-2 text-2xl font-semibold">Data & recommendations</h1>
      <p class="mt-2 text-sm" style="color:var(--text-muted);">Manage the local signals that shape recommendations and export a privacy-safe library summary.</p>
    </div>

    {#if message}
      <div class="mb-5 rounded-lg border px-3 py-2 text-sm" style="border-color:var(--border);background:var(--surface);color:var(--text-secondary);">{message}</div>
    {/if}

    <section class="mb-5 rounded-xl border p-5" style="border-color:var(--border);background:var(--surface);">
      <h2 class="font-medium">Export listening profile</h2>
      <p class="mt-1 text-sm" style="color:var(--text-muted);">Exports artist, album, and aggregate track counts only—never file paths, Apple Music URLs, tokens, or credentials.</p>
      <button onclick={exportProfile} class="mt-4 rounded-lg px-3 py-2 text-sm font-medium" style="background:var(--accent);color:var(--bg);">Export JSON profile</button>
    </section>

    <section class="mb-5 rounded-xl border p-5" style="border-color:var(--border);background:var(--surface);">
      <h2 class="font-medium">Genre preferences</h2>
      <p class="mt-1 text-sm" style="color:var(--text-muted);">Optional Last.fm genre tags, such as <em>ambient, jazz, indie rock</em>. These add lower-priority suggestions alongside artists similar to your library.</p>
      <label class="mt-4 block text-xs uppercase tracking-wider" style="color:var(--text-muted);" for="genres">Preferred genres</label>
      <input id="genres" bind:value={genres} placeholder="ambient, jazz, indie rock" class="mt-2 w-full rounded-lg border px-3 py-2 text-sm outline-none" style="border-color:var(--border);background:var(--bg);color:var(--text-primary);" />
      <button onclick={saveGenres} disabled={saving} class="mt-3 rounded-lg border px-3 py-2 text-sm disabled:opacity-50" style="border-color:var(--border);color:var(--text-secondary);">{saving ? "Saving…" : "Save preferences"}</button>
    </section>

    <section class="rounded-xl border p-5" style="border-color:var(--border);background:var(--surface);">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h2 class="font-medium">Hidden artists</h2>
          <p class="mt-1 text-sm" style="color:var(--text-muted);">Hidden artists stay out of recommendation results until restored.</p>
        </div>
        {#if hiddenArtists.length > 0}
          <button onclick={clearHiddenArtists} class="rounded-lg border px-3 py-2 text-sm" style="border-color:var(--border);color:var(--text-secondary);">Clear list</button>
        {/if}
      </div>
      {#if loading}
        <p class="mt-4 text-sm" style="color:var(--text-muted);">Loading controls…</p>
      {:else if hiddenArtists.length === 0}
        <p class="mt-4 text-sm" style="color:var(--text-muted);">No artists are hidden.</p>
      {:else}
        <div class="mt-4 flex flex-wrap gap-2">
          {#each hiddenArtists as artist}
            <button onclick={() => restoreArtist(artist)} class="rounded-full border px-3 py-1.5 text-sm" style="border-color:var(--border);color:var(--text-secondary);" title="Restore {artist}">{artist} <span style="color:var(--accent);">×</span></button>
          {/each}
        </div>
      {/if}
    </section>
  </div>
</div>
