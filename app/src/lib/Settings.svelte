<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";
  import {
    applyTheme, getStoredTheme, parseAppearance, serializeAppearance, textContrast, themes, type ThemeId,
  } from "./themes";

  let cfg = $state<Record<string, string>>({});
  let saving = $state(false);
  let saved = $state(false);
  let error = $state<string | null>(null);
  let loaded = $state(false);
  let theme = $state<ThemeId>("amber-night");
  let appearanceMessage = $state<string | null>(null);
  let contrast = $derived(textContrast(theme));

  onMount(async () => {
    theme = getStoredTheme();
    cfg = await api.config();
    loaded = true;
  });

  function selectTheme(id: ThemeId) {
    theme = id;
    applyTheme(id);
    appearanceMessage = null;
  }

  function resetTheme() {
    selectTheme("amber-night");
    appearanceMessage = "Reset to Amber Night.";
  }

  function exportTheme() {
    const blob = new Blob([serializeAppearance(theme)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "pies-pear-music-appearance.json";
    link.click();
    URL.revokeObjectURL(url);
    appearanceMessage = "Preset exported.";
  }

  async function importTheme(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    try {
      selectTheme(parseAppearance(await file.text()));
      appearanceMessage = "Preset imported.";
    } catch (e) {
      appearanceMessage = e instanceof Error ? e.message : "Could not import theme file.";
    }
  }

  const SECTIONS: {
    title: string;
    hint?: string;
    fields: { key: string; label: string; hint: string; type?: string; mono?: boolean }[];
  }[] = [
    {
      title: "Paths",
      fields: [
        { key: "music_dir",   label: "Music directory",   hint: "Where synced ALAC files are stored. Must exist or be creatable." },
        { key: "state_dir",   label: "State directory",   hint: "Where the track database (downloaded.db) and sync logs are stored." },
      ],
    },
    {
      title: "Tools",
      fields: [
        { key: "alac_rip_dir", label: "alac-rip directory", hint: "Absolute path to your alac-rip clone (contains wrapper/ and apple-music-downloader/)." },
      ],
    },
    {
      title: "Integrations",
      fields: [
        { key: "lastfm_api_key", label: "Last.fm API Key", hint: "Get a free key at last.fm/api — used for artist recommendations on the Home screen.", type: "password" },
      ],
    },
  ];

  function isEmpty(key: string): boolean {
    return !cfg[key]?.trim();
  }

  const REQUIRED = new Set(["music_dir", "state_dir"]);

  let hasIssues = $derived([...REQUIRED].some(k => isEmpty(k)));

  async function save() {
    saving = true;
    error = null;
    try {
      const updates: Record<string, string> = {};
      for (const section of SECTIONS) {
        for (const f of section.fields) {
          const val = cfg[f.key] ?? "";
          // Don't send empty API keys — GET /config omits them so blank means "unchanged"
          if (f.key === "lastfm_api_key" && !val) continue;
          updates[f.key] = val;
        }
      }
      await api.updateConfig(updates);
      saved = true;
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }
</script>

<div class="p-8 max-w-xl h-full overflow-y-auto">
  <div class="mb-7">
    <h1 class="text-white text-2xl font-bold tracking-tight">Settings</h1>
    <p class="text-zinc-500 text-sm mt-1">Saved to <span class="font-mono text-zinc-400 text-xs">~/.config/pies-alac-rip/config.yaml</span></p>
  </div>

  {#if !loaded}
    <div class="flex flex-col gap-4">
      {#each [1,2,3] as _}
        <div class="h-14 rounded-xl bg-[#12100e] animate-pulse border border-[rgba(255,255,255,0.06)]"></div>
      {/each}
    </div>
  {:else}
    <div class="flex flex-col gap-7">
      <div>
        <div class="flex items-baseline gap-2 mb-3">
          <span class="text-zinc-300 text-sm font-semibold">Appearance</span>
          <span class="text-zinc-600 text-xs">Stored locally; it does not alter sync configuration.</span>
        </div>
        <div class="grid grid-cols-2 gap-2">
          {#each themes as preset}
            <button
              type="button"
              onclick={() => selectTheme(preset.id)}
              aria-pressed={theme === preset.id}
              class="rounded-xl border p-3 text-left transition-colors {theme === preset.id ? 'border-amber-500 bg-amber-950/30' : 'border-[rgba(255,255,255,0.10)] bg-[#12100e] hover:border-zinc-600'}">
              <div class="flex gap-1.5 mb-2" aria-hidden="true">
                {#each [preset.colors['--bg'], preset.colors['--surface'], preset.colors['--accent'], preset.colors['--accent-2']] as color}
                  <span class="h-4 w-4 rounded-full border border-white/20" style:background={color}></span>
                {/each}
              </div>
              <div class="text-sm font-medium text-white">{preset.name}</div>
              <div class="mt-0.5 text-[10px] text-zinc-500">{preset.description}</div>
            </button>
          {/each}
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" onclick={resetTheme} class="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs" style="color:var(--text-secondary);background:var(--surface);">Reset</button>
          <button type="button" onclick={exportTheme} class="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs" style="color:var(--text-secondary);background:var(--surface);">Export preset</button>
          <label class="cursor-pointer rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs" style="color:var(--text-secondary);background:var(--surface);">
            Import preset
            <input class="sr-only" type="file" accept="application/json,.json" onchange={importTheme} />
          </label>
          {#if appearanceMessage}
            <span class="text-xs" style="color:var(--text-muted);">{appearanceMessage}</span>
          {/if}
        </div>
        <p class="mt-2 text-xs" style="color:var(--text-muted);">
          Primary text contrast: {contrast.toFixed(1)}:1
          {#if contrast < 4.5}
            <span style="color:#f87171;"> — below the 4.5:1 target.</span>
          {:else}
            <span style="color:var(--accent);"> — meets the 4.5:1 target.</span>
          {/if}
        </p>
      </div>

      {#each SECTIONS as section}
        <div>
          <div class="flex items-baseline gap-2 mb-3">
            <span class="text-zinc-300 text-sm font-semibold">{section.title}</span>
            {#if section.hint}
              <span class="text-zinc-600 text-xs">{section.hint}</span>
            {/if}
          </div>

          <div class="flex flex-col gap-3 border border-[rgba(255,255,255,0.06)] rounded-xl overflow-hidden">
            {#each section.fields as field, fi}
              <div class="px-4 {fi > 0 ? 'pt-3 border-t border-[#181818]' : 'pt-4'} pb-3">
                <div class="flex items-center justify-between mb-1.5">
                  <label class="text-zinc-400 text-[10px] uppercase tracking-widest font-semibold" for={field.key}>
                    {field.label}
                  </label>
                  {#if REQUIRED.has(field.key) && isEmpty(field.key)}
                    <span class="text-amber-500 text-[9px] uppercase tracking-wider font-semibold">required</span>
                  {/if}
                </div>
                  <input
                    id={field.key}
                    bind:value={cfg[field.key]}
                    type={field.type ?? "text"}
                    class="w-full bg-[#0d0d0d] border rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors
                      {field.mono ? 'font-mono text-xs' : ''}
                      {isEmpty(field.key) && REQUIRED.has(field.key)
                        ? 'border-amber-800/60 focus:border-amber-600'
                        : 'border-[#2a2a2a] focus:border-amber-700'}"
                  />
                <p class="text-zinc-600 text-[10px] mt-1.5 leading-relaxed">{field.hint}</p>
              </div>
            {/each}
          </div>
        </div>
      {/each}

      {#if error}
        <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 text-red-400 text-sm">{error}</div>
      {/if}

      {#if hasIssues}
        <div class="bg-amber-950/30 border border-amber-900/40 rounded-xl px-4 py-3 text-amber-400 text-sm flex items-center gap-2">
          <span>⚠</span>
          <span>Some required fields are empty. The app may not function until they're filled in.</span>
        </div>
      {/if}

      <button
        onclick={save}
        disabled={saving}
        class="w-full py-2.5 rounded-xl font-bold text-sm transition-colors disabled:opacity-50
          {saved
            ? 'bg-amber-900/50 text-amber-400 border border-amber-800/50'
            : 'bg-amber-700 hover:bg-amber-600 text-white'}">
        {saving ? "Saving…" : saved ? "✓ Saved" : "Save changes"}
      </button>
    </div>
  {/if}
</div>
