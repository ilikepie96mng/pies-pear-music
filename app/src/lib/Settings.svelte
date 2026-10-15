<script lang="ts">
  import { onMount } from "svelte";
  import { api, type SchedulerStatus } from "../api";
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
  let discordTesting = $state(false);
  let discordStatus = $state<string | null>(null);
  let telegramTesting = $state(false);
  let telegramStatus = $state<string | null>(null);
  let gotifyTesting = $state(false);
  let gotifyStatus = $state<string | null>(null);

  // Scheduler State
  let schedulerStatus = $state<SchedulerStatus | null>(null);
  let schedulerTriggering = $state(false);

  // Storage & SMB helper state
  let storageTesting = $state(false);
  let storageTestResult = $state<string | null>(null);
  let smbUriInput = $state("");
  let smbResolving = $state(false);
  let smbResolveResult = $state<string | null>(null);

  // Navidrome token generator state
  let naviPasswordInput = $state("");
  let naviGenerating = $state(false);
  let naviGenResult = $state<string | null>(null);

  // Navidrome sync state
  let naviSyncing = $state(false);
  let naviSyncStatus = $state<string | null>(null);

  // Database import/export state
  let dbImporting = $state(false);
  let dbImportResult = $state<string | null>(null);

  async function handleDatabaseUpload(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    dbImporting = true;
    dbImportResult = null;
    try {
      const res = await api.importDatabase(file);
      dbImportResult = `✓ Database restored! Loaded ${res.total_tracks} tracks and ${res.total_playlists} playlists.`;
      setTimeout(() => {
        if (typeof window !== "undefined") window.location.reload();
      }, 1200);
    } catch (err) {
      dbImportResult = `✗ Failed to import database: ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      dbImporting = false;
      input.value = "";
    }
  }

  async function testStorageAccess() {
    const target = cfg.music_dir?.toString().trim();
    if (!target) return;
    storageTesting = true;
    storageTestResult = null;
    try {
      const res = await api.testStoragePath(target);
      if (res.writable) {
        storageTestResult = `✓ Writable (~${res.latency_ms}ms latency, ${res.free_space_formatted} free)`;
      } else {
        storageTestResult = `✗ ${res.message || "Directory is not writable"}`;
      }
    } catch (e) {
      storageTestResult = `✗ Error testing storage: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      storageTesting = false;
    }
  }

  async function resolveSmbShare() {
    const uri = smbUriInput.trim();
    if (!uri) return;
    smbResolving = true;
    smbResolveResult = null;
    try {
      const res = await api.resolveSmb(uri);
      if (res.found && res.resolved_path) {
        cfg.music_dir = res.resolved_path;
        smbResolveResult = `✓ Found active SMB mount! Set Music Directory to: ${res.resolved_path}`;
      } else {
        const parts = uri.replace(/^smb:\/\//i, "").split("/");
        const baseShare = parts.length > 1 ? `smb://${parts[0]}/${parts[1]}` : uri;
        smbResolveResult = `✗ Mount not detected in GVFS/CIFS. Please connect to ${baseShare} in your file manager (Other Locations) or run:\ngio mount ${baseShare}`;
      }
    } catch (e) {
      smbResolveResult = `✗ Error: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      smbResolving = false;
    }
  }

  async function generateNaviToken() {
    if (!naviPasswordInput) return;
    naviGenerating = true;
    naviGenResult = null;
    try {
      const res = await api.generateNavidromeToken(naviPasswordInput);
      cfg.integrations.navidrome.token = res.token;
      cfg.integrations.navidrome.salt = res.salt;
      naviGenResult = "✓ Token & Salt generated and applied!";
      naviPasswordInput = "";
    } catch (e) {
      naviGenResult = `✗ Error: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      naviGenerating = false;
    }
  }

  async function syncNavidromeNow() {
    naviSyncing = true;
    naviSyncStatus = null;
    try {
      const res = await api.syncNavidromePlaylists();
      if (res.status === "ok") {
        naviSyncStatus = `✓ Synced! (Imported: ${res.imported_from_remote ?? 0}, Updated: ${res.updated_local ?? 0}, Pushed: ${res.pushed_to_remote ?? 0})`;
      } else if (res.status === "skipped") {
        naviSyncStatus = `ℹ ${res.message || "Skipped"}`;
      } else {
        naviSyncStatus = `✗ Error: ${res.message || (res.errors && res.errors.join(", ")) || "Sync failed"}`;
      }
    } catch (e) {
      naviSyncStatus = `✗ Error: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      naviSyncing = false;
    }
  }

  async function testDiscord() {
    discordTesting = true;
    discordStatus = null;
    try {
      const url = cfg.integrations?.discord?.webhook_url || "";
      const res = await api.integrations.testWebhook({ service: "discord", url });
      discordStatus = res.success ? `✓ ${res.message}` : `✗ ${res.message}`;
    } catch (e) {
      discordStatus = `✗ Error: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      discordTesting = false;
    }
  }

  async function testTelegram() {
    telegramTesting = true;
    telegramStatus = null;
    try {
      const tg = cfg.integrations?.telegram || {};
      const res = await api.integrations.testWebhook({
        service: "telegram",
        token: tg.bot_token || "",
        chat_id: tg.chat_id || "",
      });
      telegramStatus = res.success ? `✓ ${res.message}` : `✗ ${res.message}`;
    } catch (e) {
      telegramStatus = `✗ Error: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      telegramTesting = false;
    }
  }

  async function testGotify() {
    gotifyTesting = true;
    gotifyStatus = null;
    try {
      const g = cfg.integrations?.gotify || {};
      const res = await api.integrations.testWebhook({
        service: "gotify",
        url: g.server_url || "",
        token: g.token || "",
      });
      gotifyStatus = res.success ? `✓ ${res.message}` : `✗ ${res.message}`;
    } catch (e) {
      gotifyStatus = `✗ Error: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      gotifyTesting = false;
    }
  }

  async function triggerSchedulerSync() {
    schedulerTriggering = true;
    try {
      await api.scheduler.trigger();
      schedulerStatus = await api.scheduler.getStatus();
    } catch (e) {
      console.error(e);
    } finally {
      schedulerTriggering = false;
    }
  }

  onMount(async () => {
    theme = getStoredTheme();
    const wp = getStoredWallpaper();
    wallpaperImage = wp.image;
    wallpaperDim = wp.dim;
    wallpaperBlur = wp.blur;

    cfg = await api.config();
    if (!cfg.integrations) {
      cfg.integrations = {};
    }
    if (!cfg.integrations.jellyfin) cfg.integrations.jellyfin = { enabled: false, server_url: "", api_key: "", auto_refresh: true };
    if (!cfg.integrations.navidrome) cfg.integrations.navidrome = { enabled: false, server_url: "", user: "", token: "", salt: "", auto_refresh: true, bidirectional_sync: true };
    if (cfg.integrations.navidrome.bidirectional_sync === undefined) cfg.integrations.navidrome.bidirectional_sync = true;
    if (!cfg.integrations.discord) cfg.integrations.discord = { enabled: false, webhook_url: "" };
    if (!cfg.integrations.telegram) cfg.integrations.telegram = { enabled: false, bot_token: "", chat_id: "" };
    if (!cfg.integrations.gotify) cfg.integrations.gotify = { enabled: false, server_url: "", token: "" };

    if (!cfg.scheduler) {
      cfg.scheduler = { enabled: false, interval_minutes: 60 };
    }

    try {
      schedulerStatus = await api.scheduler.getStatus();
    } catch {}

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
      title: "Security & Multi-Device Access",
      fields: [
        { key: "api_token", label: "Headless Web API Token", hint: "Optional static token required for web browser access when self-hosting with Docker.", type: "password" },
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
          if ((f.key === "lastfm_api_key" || f.key === "gemini_api_key" || f.key === "api_token") && !val) continue;
          updates[f.key] = val;
        }
      }
      if (cfg.integrations) {
        updates.integrations = cfg.integrations;
      }
      if (cfg.scheduler) {
        updates.scheduler = cfg.scheduler;
      }
      if (cfg.api_token !== undefined) {
        updates.api_token = cfg.api_token;
      }
      await api.updateConfig(updates);
      if (cfg.scheduler) {
        schedulerStatus = await api.scheduler.updateConfig(cfg.scheduler.enabled, cfg.scheduler.interval_minutes);
      }
      saved = true;
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }
  function applyServerDefaults() {
    cfg.music_dir = "/music";
    cfg.state_dir = "/config";
    cfg.alac_rip_dir = "/app";
    appearanceMessage = "Applied standard Docker container paths (/music, /config, /app). Click Save to apply!";
  }
</script>

<div class="p-8 max-w-2xl h-full overflow-y-auto space-y-8">
  <div>
    <h1 class="text-white text-2xl font-bold tracking-tight">Settings</h1>
    <p class="text-zinc-500 text-sm mt-1">Configuring <span class="font-mono text-zinc-400 text-xs">{typeof window !== 'undefined' && window.location.hostname !== 'tauri.localhost' ? 'Headless Docker / Server Mode' : '~/.config/pies-alac-rip/config.yaml'}</span></p>
  </div>

  <!-- SERVER VS DESKTOP SETUP HELPER -->
  <div class="p-4 rounded-xl border border-amber-500/30 bg-amber-950/10 space-y-3">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="text-base">💡</span>
        <span class="text-xs font-bold text-amber-400">Desktop vs Server (Docker) Mode Guide</span>
      </div>
      {#if typeof window !== 'undefined' && window.location.hostname !== 'tauri.localhost'}
        <button
          onclick={applyServerDefaults}
          class="px-2.5 py-1 rounded text-[11px] font-bold bg-amber-500 text-black hover:bg-amber-400 transition-colors"
        >
          ⚡ Set Container Defaults
        </button>
      {/if}
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px] text-zinc-400 leading-relaxed">
      <div class="p-2.5 rounded-lg bg-black/40 border border-zinc-800 space-y-1">
        <div class="font-semibold text-zinc-200">🖥️ Desktop App Mode</div>
        <div>• <strong>Music Dir:</strong> Local path or SMB mount (e.g. <code class="text-zinc-300">/run/user/1000/kio-fuse.../music</code>)</div>
        <div>• <strong>State Dir:</strong> <code class="text-zinc-300">~/.local/share/pies-alac-rip</code></div>
        <div>• <strong>ALAC-RIP Dir:</strong> Local clone folder with wrapper & downloader</div>
      </div>
      <div class="p-2.5 rounded-lg bg-black/40 border border-zinc-800 space-y-1">
        <div class="font-semibold text-zinc-200">🐳 Docker / Server Mode</div>
        <div>• <strong>Music Dir:</strong> <code class="text-amber-300">/music</code> (mounts your NAS/host storage)</div>
        <div>• <strong>State Dir:</strong> <code class="text-amber-300">/config/.state</code> (mounts your config volume)</div>
        <div>• <strong>ALAC-RIP Dir:</strong> <code class="text-amber-300">/app</code> (embedded inside container)</div>
      </div>
    </div>
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
                <div class="flex items-center gap-2">
                  {#if field.key === "music_dir"}
                    <button
                      onclick={testStorageAccess}
                      disabled={storageTesting || !cfg.music_dir}
                      class="px-2 py-0.5 rounded text-[10px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
                    >
                      {storageTesting ? "Testing…" : "Test Storage & Access"}
                    </button>
                  {/if}
                  {#if REQUIRED.has(field.key) && isEmpty(field.key)}
                    <span class="text-amber-500 text-[9px] uppercase tracking-wider font-semibold">required</span>
                  {/if}
                </div>
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

              {#if field.key === "music_dir" && storageTestResult}
                <div class="mt-2 text-xs font-mono {storageTestResult.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">
                  {storageTestResult}
                </div>
              {/if}

              {#if field.key === "music_dir"}
                <!-- SMB / Network Share Auto-Resolver Card -->
                <div class="mt-3 p-3 bg-black/40 border border-zinc-800 rounded-xl space-y-2">
                  <div class="text-[11px] font-bold text-amber-400 flex items-center gap-1.5">
                    <span>🌐</span>
                    <span>SMB / NAS Network Storage Resolver</span>
                  </div>
                  <p class="text-[10px] text-zinc-400 leading-relaxed">
                    Paste your network share URI (e.g. <code class="text-amber-300">smb://msadmin@192.168.0.250/tank/media/music/</code>) to auto-detect its active Linux GVFS/CIFS mount point:
                  </p>
                  <div class="flex items-center gap-2">
                    <input
                      bind:value={smbUriInput}
                      placeholder="smb://msadmin@192.168.0.250/tank/media/music/"
                      class="flex-1 bg-[#12100e] border border-[#2a2a2a] rounded-lg px-3 py-1.5 text-xs text-white placeholder-zinc-700 outline-none focus:border-amber-500"
                    />
                    <button
                      onclick={resolveSmbShare}
                      disabled={smbResolving || !smbUriInput.trim()}
                      class="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500 text-black hover:bg-amber-400 transition-colors disabled:opacity-50 flex-shrink-0"
                    >
                      {smbResolving ? "Detecting…" : "Auto-Detect Mount"}
                    </button>
                  </div>
                  {#if smbResolveResult}
                    <div class="text-xs font-mono {smbResolveResult.startsWith('✓') ? 'text-emerald-400' : 'text-amber-400/90'}">
                      {smbResolveResult}
                    </div>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/each}

    <!-- DATABASE & LIBRARY STATE BACKUP / RESTORE -->
    <div class="space-y-3">
      <span class="text-zinc-200 text-sm font-semibold">Database & Library State Management</span>
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-xs font-bold text-white">Database Backup & 1-Click Restore</div>
            <p class="text-[11px] text-zinc-400 mt-0.5">Export or import your SQLite database (<code class="text-amber-300">downloaded.db</code>) with full playlist and sync history.</p>
          </div>
          <div class="flex items-center gap-2">
            <a
              href="/database/export"
              download="downloaded.db"
              class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-white/10 transition-colors"
            >
              📥 Export Database
            </a>
            <label class="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500 text-black hover:bg-amber-400 cursor-pointer transition-colors">
              <span>{dbImporting ? "Restoring…" : "📤 Import downloaded.db"}</span>
              <input type="file" accept=".db,application/x-sqlite3" onchange={handleDatabaseUpload} disabled={dbImporting} class="hidden" />
            </label>
          </div>
        </div>
        {#if dbImportResult}
          <div class="text-xs font-mono {dbImportResult.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">
            {dbImportResult}
          </div>
        {/if}
      </div>
    </div>

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
          <div class="flex items-center gap-2">
            {#if jfStatus}
              <span class="text-[11px] font-mono {jfStatus.startsWith('✓') ? 'text-emerald-400 font-bold' : 'text-red-400'}">{jfStatus}</span>
            {/if}
            <button
              onclick={testJellyfin}
              disabled={jfTesting}
              class="px-3 py-1 rounded-lg text-[11px] font-bold bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {#if jfTesting}
                <span class="w-2.5 h-2.5 border border-black border-t-transparent rounded-full animate-spin"></span>
                <span>Testing…</span>
              {:else}
                <span>⚡ Test Connection</span>
              {/if}
            </button>
          </div>
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
      </div>

      <!-- Navidrome -->
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="navi-enable" bind:checked={cfg.integrations.navidrome.enabled} class="accent-amber-400" />
            <label for="navi-enable" class="text-xs font-bold text-white cursor-pointer">Navidrome / Subsonic Integration</label>
          </div>
          <div class="flex items-center gap-2">
            {#if naviStatus}
              <span class="text-[11px] font-mono {naviStatus.startsWith('✓') ? 'text-emerald-400 font-bold' : 'text-red-400'}">{naviStatus}</span>
            {/if}
            <button
              onclick={testNavidrome}
              disabled={naviTesting}
              class="px-3 py-1 rounded-lg text-[11px] font-bold bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {#if naviTesting}
                <span class="w-2.5 h-2.5 border border-black border-t-transparent rounded-full animate-spin"></span>
                <span>Testing…</span>
              {:else}
                <span>⚡ Test Connection</span>
              {/if}
            </button>
          </div>
        </div>

        {#if cfg.integrations.navidrome.enabled}
          <div class="space-y-3 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <div class="grid grid-cols-2 gap-2">
              <input
                bind:value={cfg.integrations.navidrome.server_url}
                placeholder="http://192.168.0.250:4533"
                class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white"
              />
              <input
                bind:value={cfg.integrations.navidrome.user}
                placeholder="Username (e.g. msadmin)"
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

            <!-- Subsonic Password to Token Generator -->
            <div class="p-2.5 bg-black/40 border border-zinc-800 rounded-xl space-y-1.5">
              <div class="text-[10px] uppercase tracking-wider font-bold text-amber-400">Password-to-Token Auto-Generator</div>
              <div class="flex items-center gap-2">
                <input
                  type="password"
                  bind:value={naviPasswordInput}
                  placeholder="Enter Navidrome Password"
                  class="flex-1 px-3 py-1.5 rounded-lg text-xs bg-black/60 border border-zinc-800 text-white placeholder-zinc-700 outline-none focus:border-amber-500"
                />
                <button
                  onclick={generateNaviToken}
                  disabled={naviGenerating || !naviPasswordInput}
                  class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-zinc-800 hover:bg-zinc-700 text-amber-300 disabled:opacity-50 transition-colors flex-shrink-0"
                >
                  {naviGenerating ? "Generating…" : "Generate Token & Salt"}
                </button>
              </div>
              {#if naviGenResult}
                <div class="text-[11px] font-mono {naviGenResult.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">
                  {naviGenResult}
                </div>
              {/if}
            </div>

            <div class="flex items-center gap-2">
              <input type="checkbox" id="navi-auto" bind:checked={cfg.integrations.navidrome.auto_refresh} class="accent-amber-400" />
              <label for="navi-auto" class="text-[11px] text-zinc-400">Trigger startScan on sync / download completion</label>
            </div>

            <div class="flex items-center justify-between pt-1 border-t border-[rgba(255,255,255,0.06)]">
              <div class="flex items-center gap-2">
                <input type="checkbox" id="navi-bisync" bind:checked={cfg.integrations.navidrome.bidirectional_sync} class="accent-amber-400" />
                <label for="navi-bisync" class="text-[11px] text-zinc-300 font-medium cursor-pointer">
                  Bidirectional Playlist Sync (Symfonium / Feishin ⇄ Navidrome ⇄ Pear Music)
                </label>
              </div>
              <button
                type="button"
                onclick={syncNavidromeNow}
                disabled={naviSyncing || !cfg.integrations.navidrome.enabled}
                class="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-amber-300 disabled:opacity-50 transition-colors flex items-center gap-1.5"
              >
                {#if naviSyncing}
                  <span class="w-2.5 h-2.5 border border-amber-300 border-t-transparent rounded-full animate-spin"></span>
                  <span>Syncing…</span>
                {:else}
                  <span>🔄 Sync Playlists Now</span>
                {/if}
              </button>
            </div>
            {#if naviSyncStatus}
              <div class="text-[11px] font-mono {naviSyncStatus.startsWith('✓') ? 'text-emerald-400 font-bold' : naviSyncStatus.startsWith('ℹ') ? 'text-amber-300' : 'text-red-400'}">
                {naviSyncStatus}
              </div>
            {/if}
          </div>
        {/if}

        {#if naviStatus}
          <div class="text-[11px] font-mono {naviStatus.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">{naviStatus}</div>
        {/if}
      </div>
    </div>

    <!-- BACKGROUND AUTOMATION & SCHEDULER -->
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <span class="text-zinc-200 text-sm font-semibold">Background Sync Scheduler</span>
        {#if schedulerStatus}
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold {schedulerStatus.running ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-zinc-800 text-zinc-400'}">
              <span class="w-1.5 h-1.5 rounded-full {schedulerStatus.running ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-500'}"></span>
              {schedulerStatus.running ? 'Active daemon' : 'Idle'}
            </span>
          </div>
        {/if}
      </div>

      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="sched-enable" bind:checked={cfg.scheduler.enabled} class="accent-amber-400" />
            <label for="sched-enable" class="text-xs font-bold text-white cursor-pointer">Enable Automated Background Sync</label>
          </div>
          <button
            onclick={triggerSchedulerSync}
            disabled={schedulerTriggering}
            class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-amber-300 disabled:opacity-50 transition-colors"
          >
            {schedulerTriggering ? "Triggering…" : "Run Sync Now"}
          </button>
        </div>

        {#if cfg.scheduler.enabled}
          <div class="space-y-3 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <div class="space-y-1.5">
              <div class="flex items-center justify-between text-xs">
                <span class="text-zinc-300">Sync Interval:</span>
                <span class="font-bold text-amber-400">{cfg.scheduler.interval_minutes} minutes</span>
              </div>
              <input
                type="range"
                min="5"
                max="720"
                step="5"
                bind:value={cfg.scheduler.interval_minutes}
                class="w-full accent-amber-500 cursor-pointer"
              />
              <div class="flex justify-between text-[10px] text-zinc-500">
                <span>5m</span>
                <span>30m</span>
                <span>1h</span>
                <span>2h</span>
                <span>6h</span>
                <span>12h</span>
              </div>
            </div>

            {#if schedulerStatus}
              <div class="p-3 bg-black/40 border border-zinc-800/80 rounded-lg text-xs space-y-1 text-zinc-400">
                <div class="flex justify-between">
                  <span>Last Sync Status:</span>
                  <span class="font-medium {schedulerStatus.last_run_status === 'success' ? 'text-emerald-400' : schedulerStatus.last_run_status === 'error' ? 'text-red-400' : 'text-zinc-400'}">
                    {schedulerStatus.last_run_status || 'Never run'}
                  </span>
                </div>
                {#if schedulerStatus.last_run_time}
                  <div class="flex justify-between text-[11px]">
                    <span>Last Run Time:</span>
                    <span class="text-zinc-300">{new Date(schedulerStatus.last_run_time).toLocaleString()}</span>
                  </div>
                {/if}
                {#if schedulerStatus.last_run_message}
                  <div class="text-[11px] text-zinc-400 truncate">
                    <span>Note: {schedulerStatus.last_run_message}</span>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </div>

    <!-- NOTIFICATIONS & WEBHOOKS (Discord / Telegram / Gotify) -->
    <div class="space-y-4">
      <span class="text-zinc-200 text-sm font-semibold">Completion Webhooks & Push Notifications</span>

      <!-- Discord -->
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="discord-enable" bind:checked={cfg.integrations.discord.enabled} class="accent-amber-400" />
            <label for="discord-enable" class="text-xs font-bold text-white cursor-pointer">Discord Webhook (Rich Embeds)</label>
          </div>
          <button
            onclick={testDiscord}
            disabled={discordTesting || !cfg.integrations.discord.webhook_url}
            class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200 disabled:opacity-50"
          >
            {discordTesting ? "Sending…" : "Test Webhook"}
          </button>
        </div>

        {#if cfg.integrations.discord.enabled}
          <div class="space-y-2 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <input
              bind:value={cfg.integrations.discord.webhook_url}
              placeholder="https://discord.com/api/webhooks/..."
              class="w-full px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white placeholder-zinc-700 outline-none focus:border-amber-500 font-mono"
            />
            <p class="text-[10px] text-zinc-500">Sends rich cards with new track count, artwork, and completion timestamp on sync.</p>
          </div>
        {/if}

        {#if discordStatus}
          <div class="text-[11px] font-mono {discordStatus.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">{discordStatus}</div>
        {/if}
      </div>

      <!-- Telegram -->
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="tg-enable" bind:checked={cfg.integrations.telegram.enabled} class="accent-amber-400" />
            <label for="tg-enable" class="text-xs font-bold text-white cursor-pointer">Telegram Bot Notifications</label>
          </div>
          <button
            onclick={testTelegram}
            disabled={telegramTesting || !cfg.integrations.telegram.bot_token || !cfg.integrations.telegram.chat_id}
            class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200 disabled:opacity-50"
          >
            {telegramTesting ? "Sending…" : "Test Bot"}
          </button>
        </div>

        {#if cfg.integrations.telegram.enabled}
          <div class="grid grid-cols-2 gap-2 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <input
              type="password"
              bind:value={cfg.integrations.telegram.bot_token}
              placeholder="Bot Token (e.g. 123456:ABC-DEF1234)"
              class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white placeholder-zinc-700 outline-none focus:border-amber-500 font-mono"
            />
            <input
              bind:value={cfg.integrations.telegram.chat_id}
              placeholder="Chat ID (e.g. -100123456789 or @channel)"
              class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white placeholder-zinc-700 outline-none focus:border-amber-500 font-mono"
            />
          </div>
        {/if}

        {#if telegramStatus}
          <div class="text-[11px] font-mono {telegramStatus.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">{telegramStatus}</div>
        {/if}
      </div>

      <!-- Gotify -->
      <div class="p-4 rounded-xl border space-y-3" style="background:var(--surface);border-color:var(--border);">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <input type="checkbox" id="gotify-enable" bind:checked={cfg.integrations.gotify.enabled} class="accent-amber-400" />
            <label for="gotify-enable" class="text-xs font-bold text-white cursor-pointer">Gotify Push Server</label>
          </div>
          <button
            onclick={testGotify}
            disabled={gotifyTesting || !cfg.integrations.gotify.server_url || !cfg.integrations.gotify.token}
            class="px-2.5 py-1 rounded text-[11px] font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200 disabled:opacity-50"
          >
            {gotifyTesting ? "Sending…" : "Test Gotify"}
          </button>
        </div>

        {#if cfg.integrations.gotify.enabled}
          <div class="grid grid-cols-2 gap-2 pt-2 border-t border-[rgba(255,255,255,0.06)]">
            <input
              bind:value={cfg.integrations.gotify.server_url}
              placeholder="https://gotify.yourdomain.com"
              class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white placeholder-zinc-700 outline-none focus:border-amber-500 font-mono"
            />
            <input
              type="password"
              bind:value={cfg.integrations.gotify.token}
              placeholder="Application AppToken"
              class="px-3 py-1.5 rounded-lg text-xs bg-black/40 border border-zinc-800 text-white placeholder-zinc-700 outline-none focus:border-amber-500 font-mono"
            />
          </div>
        {/if}

        {#if gotifyStatus}
          <div class="text-[11px] font-mono {gotifyStatus.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}">{gotifyStatus}</div>
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
