<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";
  import {
    applyTheme, getStoredTheme, parseAppearance, serializeAppearance, textContrast, themes, type ThemeId,
    applyWallpaper, getStoredWallpaper,
  } from "./themes";

  let cfg = $state<Record<string, any>>({});
  let saving = $state(false);
  let saved = $state(false);
  let error = $state<string | null>(null);
  let loaded = $state(false);
  let theme = $state<ThemeId>("amber-night");
  let appearanceMessage = $state<string | null>(null);
  let contrast = $derived(textContrast(theme));

  // Custom Wallpaper Engine
  let wallpaperImage = $state("");
  let wallpaperDim = $state(40);
  let wallpaperBlur = $state(8);

  // Integration test feedback
  let jfTesting = $state(false);
  let jfStatus = $state<string | null>(null);
  let naviTesting = $state(false);
  let naviStatus = $state<string | null>(null);

  onMount(async () => {
    theme = getStoredTheme();
    const wp = getStoredWallpaper();
    wallpaperImage = wp.image;
    wallpaperDim = wp.dim;
    wallpaperBlur = wp.blur;

    cfg = await api.config();
    if (!cfg.integrations) {
      cfg.integrations = {
        jellyfin: { enabled: false, server_url: "", api_key: "", auto_refresh: true },
        navidrome: { enabled: false, server_url: "", user: "", token: "", salt: "", auto_refresh: true },
      };
    }
    loaded = true;
  });

  function selectTheme(id: ThemeId) {
    theme = id;
    applyTheme(id);
    appearanceMessage = null;
  }

  function resetTheme() {
    selectTheme("amber-night");
    wallpaperImage = "";
    wallpaperDim = 40;
    wallpaperBlur = 8;
    applyWallpaper("", 40, 8);
    appearanceMessage = "Reset to Amber Night default appearance.";
  }

  function handleWallpaperUpload(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      wallpaperImage = event.target?.result as string;
      applyWallpaper(wallpaperImage, wallpaperDim, wallpaperBlur);
    };
    reader.readAsDataURL(file);
  }

  function updateWallpaperSettings() {
    applyWallpaper(wallpaperImage, wallpaperDim, wallpaperBlur);
  }

  function clearWallpaper() {
    wallpaperImage = "";
    applyWallpaper("", wallpaperDim, wallpaperBlur);
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
      const res = parseAppearance(await file.text());
      selectTheme(res.theme);
      if (res.wallpaper !== undefined) wallpaperImage = res.wallpaper;
      if (res.dim !== undefined) wallpaperDim = res.dim;
      if (res.blur !== undefined) wallpaperBlur = res.blur;
      applyWallpaper(wallpaperImage, wallpaperDim, wallpaperBlur);
      appearanceMessage = "Preset imported.";
    } catch (e) {
      appearanceMessage = e instanceof Error ? e.message : "Could not import theme file.";
    }
  }

  async function testJellyfin() {
    jfTesting = true;
    jfStatus = null;
    try {
      const jf = cfg.integrations?.jellyfin || {};
      const res = await api.testJellyfin(jf.server_url || "", jf.api_key || "");
      jfStatus = res.success ? `✓ ${res.message}` : `✗ ${res.message}`;
    } catch (e) {
      jfStatus = `✗ Error: ${e}`;
    } finally {
      jfTesting = false;
    }
  }

  async function testNavidrome() {
    naviTesting = true;
    naviStatus = null;
    try {
      const nav = cfg.integrations?.navidrome || {};
      const res = await api.testNavidrome(nav.server_url || "", nav.user || "", nav.token || "", nav.salt || "");
      naviStatus = res.success ? `✓ ${res.message}` : `✗ ${res.message}`;
    } catch (e) {
      naviStatus = `✗ Error: ${e}`;
    } finally {
      naviTesting = false;
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
      title: "AI & External Intelligence",
      fields: [
        { key: "gemini_api_key", label: "Google Gemini API Key", hint: "Used for Gemini AI Curator intelligent playlist generation (stored mode 0600).", type: "password" },
        { key: "lastfm_api_key", label: "Last.fm API Key", hint: "Used for artist recommendations and music intelligence.", type: "password" },
        { key: "lastfm_shared_secret", label: "Last.fm Shared Secret", hint: "Optional shared secret for authenticated Last.fm sessions (stored mode 0600).", type: "password" },
        { key: "lastfm_username", label: "Last.fm Username", hint: "Your Last.fm user profile name for customized taste profiles.", type: "text" },
      ],
    },
  ];

  function isEmpty(key: string): boolean {
    return !cfg[key]?.toString().trim();
  }

  const REQUIRED = new Set(["music_dir", "state_dir"]);
  let hasIssues = $derived([...REQUIRED].some(k => isEmpty(k)));

  async function save() {
    saving = true;
    error = null;
    try {
      const updates: Record<string, any> = {};
      for (const section of SECTIONS) {
        for (const f of section.fields) {
          const val = cfg[f.key] ?? "";
          if ((f.key === "lastfm_api_key" || f.key === "gemini_api_key") && !val) continue;
          updates[f.key] = val;
        }
      }
      if (cfg.integrations) {
        updates.integrations = cfg.integrations;
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

<div class="p-8 max-w-2xl h-full overflow-y-auto space-y-8">
  <div>
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
    <!-- APPEARANCE & THEME ENGINE -->
    <div class="space-y-4">
      <div class="flex items-baseline gap-2">
        <span class="text-zinc-200 text-sm font-semibold">Appearance & WCAG AAA Themes</span>
        <span class="text-zinc-500 text-xs">Custom wallpapers, contrast boosts, glassmorphism.</span>
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
            <div class="mt-0.5 text-[10px] text-zinc-400">{preset.description}</div>
          </button>
        {/each}
      </div>

      <!-- Custom Wallpaper Engine Controls -->
      <div class="p-4 rounded-xl border space-y-4" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold text-white">Custom Wallpaper Engine</span>
          {#if wallpaperImage}
            <button onclick={clearWallpaper} class="text-[11px] text-red-400 hover:underline">Remove Wallpaper</button>
          {/if}
        </div>

        <div class="flex items-center gap-4">
          <label class="px-3 py-1.5 rounded-lg border text-xs font-medium cursor-pointer hover:border-amber-400" style="background:var(--surface);border-color:var(--border);color:var(--text-secondary);">
            <span>📁 Upload Background Image</span>
            <input type="file" accept="image/*" onchange={handleWallpaperUpload} class="hidden" />
          </label>
        </div>

        {#if wallpaperImage}
          <div class="grid grid-cols-2 gap-4 pt-2">
            <div class="space-y-1.5">
              <div class="flex justify-between text-xs text-zinc-400">
                <label for="wallpaper-dim-slider">Background Dimming</label>
                <span>{wallpaperDim}%</span>
              </div>
              <input
                id="wallpaper-dim-slider"
                type="range"
                min="0"
                max="80"
                bind:value={wallpaperDim}
                oninput={updateWallpaperSettings}
                class="w-full h-1 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-amber-400"
              />
            </div>

            <div class="space-y-1.5">
              <div class="flex justify-between text-xs text-zinc-400">
                <label for="wallpaper-blur-slider">Backdrop Blur</label>
                <span>{wallpaperBlur}px</span>
              </div>
              <input
                id="wallpaper-blur-slider"
                type="range"
                min="0"
                max="20"
                bind:value={wallpaperBlur}
                oninput={updateWallpaperSettings}
                class="w-full h-1 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-amber-400"
              />
            </div>
          </div>
        {/if}
      </div>

      <div class="flex flex-wrap items-center gap-2">
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
      <p class="text-xs" style="color:var(--text-muted);">
        Primary text contrast: {contrast.toFixed(1)}:1 (WCAG AAA standard: 7.0+:1)
      </p>
    </div>

    <!-- CORE CONFIG SECTIONS -->
    {#each SECTIONS as section}
      <div class="space-y-3">
        <span class="text-zinc-200 text-sm font-semibold">{section.title}</span>
        <div class="flex flex-col gap-3 border rounded-xl overflow-hidden" style="border-color:var(--border);background:var(--surface);">
          {#each section.fields as field, fi}
            {@const isConfigured = Boolean(cfg[`${field.key}_configured`] || (cfg[field.key] && cfg[field.key] !== ""))}
            <div class="px-4 {fi > 0 ? 'pt-3 border-t border-[rgba(255,255,255,0.06)]' : 'pt-4'} pb-3">
              <div class="flex items-center justify-between mb-1.5">
                <label class="text-zinc-400 text-[10px] uppercase tracking-widest font-semibold flex items-center gap-2" for={field.key}>
                  <span>{field.label}</span>
                  {#if field.type === "password" && isConfigured}
                    <span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-green-950/60 text-green-400 border border-green-500/30 normal-case tracking-normal">
                      ✓ Stored Securely
                    </span>
                  {/if}
                </label>
                {#if REQUIRED.has(field.key) && isEmpty(field.key)}
                  <span class="text-amber-500 text-[9px] uppercase tracking-wider font-semibold">required</span>
                {/if}
              </div>
              <input
                id={field.key}
                bind:value={cfg[field.key]}
                type={field.type ?? "text"}
                placeholder={field.type === "password" && isConfigured ? "••••••••••••••••••••••••••••••••" : ""}
                class="w-full bg-[#0d0d0d] border rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors
                  {field.mono ? 'font-mono text-xs' : ''}
                  {isEmpty(field.key) && REQUIRED.has(field.key)
                    ? 'border-amber-800/60 focus:border-amber-600'
                    : 'border-[#2a2a2a] focus:border-amber-700'}"
              />
              <p class="text-zinc-500 text-[10px] mt-1.5 leading-relaxed">{field.hint}</p>
            </div>
          {/each}
        </div>
      </div>
    {/each}

    <!-- HOME MEDIA ECOSYSTEM INTEGRATIONS (Jellyfin / Navidrome) -->
    <div class="space-y-4">
      <span class="text-zinc-200 text-sm font-semibold">Home Media Servers (Auto-Scan Webhooks)</span>

      <!-- Jellyfin -->
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="jf-enable" bind:checked={cfg.integrations.jellyfin.enabled} class="accent-amber-400" />
            <label for="jf-enable" class="text-xs font-bold text-white cursor-pointer">Jellyfin Server Integration</label>
          </div>
          <button
            onclick={testJellyfin}
            disabled={jfTesting || !cfg.integrations.jellyfin.server_url}
            class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
          >
            {jfTesting ? "Testing…" : "Test Connection"}
          </button>
        </div>

        {#if cfg.integrations.jellyfin.enabled}
          <div class="space-y-2 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <div class="grid grid-cols-2 gap-2">
              <input
                bind:value={cfg.integrations.jellyfin.server_url}
                placeholder="http://192.168.1.100:8096"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
              <input
                type="password"
                bind:value={cfg.integrations.jellyfin.api_key}
                placeholder="Jellyfin API Key"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
            </div>
            <div class="flex items-center gap-2">
              <input type="checkbox" id="jf-auto" bind:checked={cfg.integrations.jellyfin.auto_refresh} class="accent-amber-400" />
              <label for="jf-auto" class="text-[11px] text-zinc-400">Trigger /Library/Refresh on sync completion</label>
            </div>
          </div>
        {/if}

        {#if jfStatus}
          <div class="text-[11px] font-mono {jfStatus.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">{jfStatus}</div>
        {/if}
      </div>

      <!-- Navidrome -->
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="navi-enable" bind:checked={cfg.integrations.navidrome.enabled} class="accent-amber-400" />
            <label for="navi-enable" class="text-xs font-bold text-white cursor-pointer">Navidrome / Subsonic Integration</label>
          </div>
          <button
            onclick={testNavidrome}
            disabled={naviTesting || !cfg.integrations.navidrome.server_url}
            class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
          >
            {naviTesting ? "Testing…" : "Test Connection"}
          </button>
        </div>

        {#if cfg.integrations.navidrome.enabled}
          <div class="space-y-2 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <div class="grid grid-cols-2 gap-2">
              <input
                bind:value={cfg.integrations.navidrome.server_url}
                placeholder="http://192.168.1.100:4533"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
              <input
                bind:value={cfg.integrations.navidrome.user}
                placeholder="Username"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
              <input
                type="password"
                bind:value={cfg.integrations.navidrome.token}
                placeholder="Subsonic Auth Token"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
              <input
                bind:value={cfg.integrations.navidrome.salt}
                placeholder="Auth Salt"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
            </div>
            <div class="flex items-center gap-2">
              <input type="checkbox" id="navi-auto" bind:checked={cfg.integrations.navidrome.auto_refresh} class="accent-amber-400" />
              <label for="navi-auto" class="text-[11px] text-zinc-400">Trigger startScan on sync completion</label>
            </div>
          </div>
        {/if}

        {#if naviStatus}
          <div class="text-[11px] font-mono {naviStatus.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">{naviStatus}</div>
        {/if}
      </div>
    </div>

    {#if error}
      <div class="bg-red-950/40 border border-red-900/50 rounded-xl px-4 py-3 text-red-400 text-sm">{error}</div>
    {/if}

    <button
      onclick={save}
      disabled={saving}
      class="w-full py-3 rounded-xl font-bold text-sm transition-colors disabled:opacity-50
        {saved
          ? 'bg-amber-900/50 text-amber-400 border border-amber-800/50'
          : 'bg-amber-700 hover:bg-amber-600 text-white'}">
      {saving ? "Saving…" : saved ? "✓ Saved" : "Save changes"}
    </button>
  {/if}
</div>
