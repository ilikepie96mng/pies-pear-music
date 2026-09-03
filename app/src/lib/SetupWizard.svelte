<script lang="ts">
  import { api, type DiagnosticCheck } from "../api";

  interface Props {
    ondone: () => void;
  }

  let { ondone }: Props = $props();

  type Step = "welcome" | "storage" | "apple" | "integrations" | "done";
  const STEPS: Step[] = ["welcome", "storage", "apple", "integrations", "done"];
  let step = $state<Step>("welcome");
  let stepIndex = $derived(STEPS.indexOf(step));

  // --- Diagnostics state ---
  let checks = $state<DiagnosticCheck[]>([]);
  let loadingChecks = $state(false);
  let checksError = $state<string | null>(null);

  // --- Configuration state ---
  let cfg = $state<Record<string, any>>({});
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saved = $state(false);

  // --- Apple ID Connection state ---
  let appleEmail = $state("");
  let applePassword = $state("");
  let apple2faCode = $state("");
  let appleConnecting = $state(false);
  let appleNeeds2fa = $state(false);
  let appleConnected = $state(false);
  let appleError = $state<string | null>(null);

  // --- Integrations state ---
  let navidromeUrl = $state("");
  let navidromeToken = $state("");
  let jellyfinUrl = $state("");
  let jellyfinApiKey = $state("");
  let geminiApiKey = $state("");

  async function loadInitialData() {
    try {
      cfg = await api.config();
      const int = cfg.integrations || {};
      navidromeUrl = int.navidrome?.url || "";
      navidromeToken = int.navidrome?.token || "";
      jellyfinUrl = int.jellyfin?.url || "";
      jellyfinApiKey = int.jellyfin?.api_key || "";
      geminiApiKey = cfg.gemini_api_key || "";

      const wrap = await api.wrapper.status();
      appleConnected = wrap.running;
    } catch {}
  }

  async function runChecks() {
    loadingChecks = true;
    checksError = null;
    try {
      checks = await api.diagnostics();
    } catch (e) {
      checksError = String(e);
    } finally {
      loadingChecks = false;
    }
  }

  async function handleConnectApple() {
    if (!appleEmail || !applePassword) return;
    appleConnecting = true;
    appleError = null;
    try {
      const res = await api.wrapper.login(appleEmail, applePassword);
      if (res.needs_2fa) {
        appleNeeds2fa = true;
      } else {
        appleConnected = true;
      }
    } catch (e) {
      appleError = String(e);
    } finally {
      appleConnecting = false;
    }
  }

  async function handleSubmit2fa() {
    if (!apple2faCode) return;
    appleConnecting = true;
    appleError = null;
    try {
      await api.wrapper.submit2fa(apple2faCode);
      appleNeeds2fa = false;
      appleConnected = true;
    } catch (e) {
      appleError = String(e);
    } finally {
      appleConnecting = false;
    }
  }

  async function saveIntegrations() {
    saving = true;
    saveError = null;
    try {
      const updates = {
        gemini_api_key: geminiApiKey,
        integrations: {
          navidrome: {
            enabled: bool(navidromeUrl),
            url: navidromeUrl,
            token: navidromeToken,
          },
          jellyfin: {
            enabled: bool(jellyfinUrl),
            url: jellyfinUrl,
            api_key: jellyfinApiKey,
          },
        },
      };
      await api.updateConfig(updates);
      step = "done";
    } catch (e) {
      saveError = String(e);
    } finally {
      saving = false;
    }
  }

  function bool(val: any): boolean {
    return Boolean(val && String(val).trim());
  }

  // Transitions
  async function goStorage() {
    step = "storage";
    await Promise.all([runChecks(), loadInitialData()]);
  }

  function goApple() {
    step = "apple";
  }

  function goIntegrations() {
    step = "integrations";
  }
</script>

<div class="flex h-full items-center justify-center bg-[#0e0c0a] p-6 overflow-y-auto select-none">
  <div class="w-full max-w-xl py-6 flex flex-col gap-6">

    <!-- Step indicator -->
    <div class="flex items-center gap-2 justify-center">
      {#each STEPS as s, i}
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all
            {step === s ? 'bg-amber-600 text-white ring-2 ring-amber-500/40 shadow-lg' : stepIndex > i ? 'bg-emerald-900/80 text-emerald-300 border border-emerald-700/50' : 'bg-[#181818] text-zinc-600 border border-white/5'}">
            {stepIndex > i ? "✓" : i + 1}
          </div>
          {#if i < STEPS.length - 1}
            <div class="w-6 sm:w-10 h-0.5 {stepIndex > i ? 'bg-emerald-700/60' : 'bg-white/5'}"></div>
          {/if}
        </div>
      {/each}
    </div>

    <!-- Step 1: Welcome -->
    {#if step === "welcome"}
      <div class="flex flex-col gap-6 p-6 rounded-2xl bg-[#12100e] border border-white/5 shadow-2xl">
        <div class="flex items-center gap-3.5">
          <span class="text-3xl">🍐</span>
          <div>
            <div class="text-amber-500 text-[10px] font-bold uppercase tracking-widest">Onboarding Guide</div>
            <h1 class="text-white text-2xl font-bold tracking-tight">Welcome to Pies Pear Music</h1>
          </div>
        </div>

        <p class="text-zinc-400 text-xs leading-relaxed">
          Pies Pear Music is a high-fidelity local music workstation. This quick 2-minute wizard verifies your storage folders, connects your Apple ID for bit-perfect ALAC decryption, and sets up media server integration.
        </p>

        <div class="flex flex-col gap-2.5 p-4 rounded-xl bg-black/40 border border-white/5 text-xs">
          <div class="text-zinc-300 font-semibold text-[11px] uppercase tracking-wider mb-0.5">What we will configure:</div>
          <div class="flex items-center gap-2.5 text-zinc-400">
            <span class="text-amber-500">📁</span>
            <span><strong>Storage Mounts:</strong> Music output (<code class="text-amber-300">/music</code>) & State database (<code class="text-amber-300">/config</code>).</span>
          </div>
          <div class="flex items-center gap-2.5 text-zinc-400">
            <span class="text-amber-500">🔐</span>
            <span><strong>Apple Music DRM:</strong> FairPlay decryption daemon for lossless ALAC/FLAC streams.</span>
          </div>
          <div class="flex items-center gap-2.5 text-zinc-400">
            <span class="text-amber-500">📡</span>
            <span><strong>Media Server Webhooks:</strong> Auto-refresh Navidrome / Jellyfin when new songs arrive.</span>
          </div>
        </div>

        <button onclick={goStorage}
          class="w-full bg-amber-600 hover:bg-amber-500 text-white font-bold py-3 rounded-xl transition-all shadow-md text-xs flex items-center justify-center gap-2">
          <span>Let's get started →</span>
        </button>
      </div>

    <!-- Step 2: Storage & Volume Verification -->
    {:else if step === "storage"}
      <div class="flex flex-col gap-5 p-6 rounded-2xl bg-[#12100e] border border-white/5 shadow-2xl">
        <div>
          <div class="text-amber-500 text-[10px] font-bold uppercase tracking-widest mb-1">Step 1 of 4</div>
          <h2 class="text-white text-xl font-bold tracking-tight">Storage & Directory Verification</h2>
          <p class="text-zinc-400 text-xs mt-1 leading-relaxed">
            Pies Pear Music requires three directory locations to organize and preserve your collection:
          </p>
        </div>

        <div class="flex flex-col gap-3 text-xs">
          <div class="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-1">
            <div class="flex items-center justify-between">
              <span class="font-bold text-white flex items-center gap-1.5">
                <span>🎵</span> Music Library Folder
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-300 border border-amber-500/20">/music</span>
            </div>
            <p class="text-zinc-400 text-[11px] leading-relaxed mt-1">
              <strong>Why it's needed:</strong> Where all bit-perfect ALAC/FLAC songs, cover artwork, and <code class="text-zinc-300">playlists/*.m3u8</code> files are permanently stored and organized.
            </p>
          </div>

          <div class="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-1">
            <div class="flex items-center justify-between">
              <span class="font-bold text-white flex items-center gap-1.5">
                <span>🗄️</span> State & Config Folder
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-300 border border-amber-500/20">/config</span>
            </div>
            <p class="text-zinc-400 text-[11px] leading-relaxed mt-1">
              <strong>Why it's needed:</strong> Stores your SQLite track state database (<code class="text-zinc-300">downloaded.db</code>), sync history, and <code class="text-zinc-300">config.yaml</code>.
            </p>
          </div>

          <div class="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-1">
            <div class="flex items-center justify-between">
              <span class="font-bold text-white flex items-center gap-1.5">
                <span>⚡</span> Staging Buffer
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-300 border border-amber-500/20">/staging</span>
            </div>
            <p class="text-zinc-400 text-[11px] leading-relaxed mt-1">
              <strong>Why it's needed:</strong> Fast temporary workspace where audio streams are downloaded, converted to FLAC, and tagged with lyrics before atomic commit to your library.
            </p>
          </div>
        </div>

        {#if loadingChecks}
          <div class="flex items-center gap-2 text-zinc-500 text-xs py-2 justify-center font-mono">
            <span class="w-3.5 h-3.5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></span>
            Verifying filesystem permissions…
          </div>
        {:else if checks.length > 0}
          <div class="p-3 rounded-xl bg-black/20 border border-white/5 flex flex-col gap-1.5 text-xs font-mono">
            {#each checks as c}
              <div class="flex items-center justify-between">
                <span class="text-zinc-400">{c.label}</span>
                <span class={c.ok ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                  {c.ok ? "✓ Ready" : c.detail || "Warning"}
                </span>
              </div>
            {/each}
          </div>
        {/if}

        <div class="flex items-center justify-between gap-3 pt-2">
          <button onclick={() => step = "welcome"} class="px-4 py-2 text-xs text-zinc-400 hover:text-white transition-colors">
            ← Back
          </button>
          <button onclick={goApple} class="px-6 py-2.5 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all shadow-sm">
            Continue to Apple Music DRM →
          </button>
        </div>
      </div>

    <!-- Step 3: Apple Music DRM Setup -->
    {:else if step === "apple"}
      <div class="flex flex-col gap-5 p-6 rounded-2xl bg-[#12100e] border border-white/5 shadow-2xl">
        <div>
          <div class="text-amber-500 text-[10px] font-bold uppercase tracking-widest mb-1">Step 2 of 4</div>
          <h2 class="text-white text-xl font-bold tracking-tight">Apple Music FairPlay DRM Setup</h2>
          <p class="text-zinc-400 text-xs mt-1 leading-relaxed">
            <strong>Why it's needed:</strong> Apple Music audio tracks are encrypted with FairPlay DRM. A background decryption daemon authenticates with Apple's key server using your Apple ID to unlock bit-perfect lossless streams.
          </p>
        </div>

        {#if appleConnected}
          <div class="p-4 rounded-xl bg-emerald-950/30 border border-emerald-800/40 flex items-center gap-3">
            <span class="text-2xl">✅</span>
            <div>
              <div class="text-xs font-bold text-emerald-300">Decryption Wrapper Active & Connected</div>
              <div class="text-[11px] text-zinc-400 mt-0.5">Your server is ready to download lossless ALAC/FLAC music.</div>
            </div>
          </div>
        {:else if appleNeeds2fa}
          <div class="flex flex-col gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/20">
            <div class="text-xs font-bold text-amber-300">Two-Factor Authentication Required</div>
            <p class="text-zinc-400 text-[11px]">Apple has sent a verification code to your trusted Apple devices. Enter it below:</p>
            <div class="flex gap-2">
              <input type="text" bind:value={apple2faCode} placeholder="Enter 6-digit 2FA code"
                class="flex-1 bg-black/60 border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-3 py-2 text-white text-xs outline-none font-mono" />
              <button onclick={handleSubmit2fa} disabled={appleConnecting || !apple2faCode}
                class="px-4 py-2 rounded-lg text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all disabled:opacity-50">
                Submit 2FA
              </button>
            </div>
          </div>
        {:else}
          <div class="flex flex-col gap-3 p-4 rounded-xl bg-black/40 border border-white/5">
            <div class="text-[11px] font-semibold text-zinc-300">Enter Apple ID Credentials:</div>
            <div class="flex flex-col gap-2">
              <input type="email" bind:value={appleEmail} placeholder="Apple ID Email (e.g. user@icloud.com)"
                class="w-full bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-3 py-2 text-white text-xs outline-none transition-colors" />
              <input type="password" bind:value={applePassword} placeholder="Password"
                class="w-full bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-3 py-2 text-white text-xs outline-none transition-colors" />
              <button onclick={handleConnectApple} disabled={appleConnecting || !appleEmail || !applePassword}
                class="w-full py-2.5 rounded-lg text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all disabled:opacity-50 shadow-sm flex items-center justify-center gap-1.5">
                {#if appleConnecting}
                  <span class="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                  <span>Authenticating…</span>
                {:else}
                  <span>Connect Apple Music Daemon</span>
                {/if}
              </button>
            </div>
            {#if appleError}
              <div class="text-[11px] text-red-400 mt-1">{appleError}</div>
            {/if}
          </div>
        {/if}

        <div class="flex items-center justify-between gap-3 pt-2">
          <button onclick={() => step = "storage"} class="px-4 py-2 text-xs text-zinc-400 hover:text-white transition-colors">
            ← Back
          </button>
          <button onclick={goIntegrations} class="px-6 py-2.5 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all shadow-sm">
            Continue to Integrations →
          </button>
        </div>
      </div>

    <!-- Step 4: Optional Integrations -->
    {:else if step === "integrations"}
      <div class="flex flex-col gap-5 p-6 rounded-2xl bg-[#12100e] border border-white/5 shadow-2xl">
        <div>
          <div class="text-amber-500 text-[10px] font-bold uppercase tracking-widest mb-1">Step 3 of 4</div>
          <h2 class="text-white text-xl font-bold tracking-tight">Media Server & AI Integrations</h2>
          <p class="text-zinc-400 text-xs mt-1 leading-relaxed">
            Optional connections to enhance your music workstation. You can update these anytime in Settings.
          </p>
        </div>

        <div class="flex flex-col gap-3.5 text-xs">
          <!-- Navidrome -->
          <div class="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-2">
            <span class="font-bold text-white flex items-center gap-1.5">
              <span>📻</span> Navidrome / Subsonic Auto-Refresh
            </span>
            <p class="text-zinc-400 text-[11px]">Sends an instant webhook (<code class="text-zinc-300">/rest/startScan.view</code>) whenever new music is saved.</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-1">
              <input type="text" bind:value={navidromeUrl} placeholder="http://192.168.0.x:4533"
                class="bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-2.5 py-1.5 text-white text-xs outline-none" />
              <input type="text" bind:value={navidromeToken} placeholder="API Token / Password"
                class="bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-2.5 py-1.5 text-white text-xs outline-none" />
            </div>
          </div>

          <!-- Jellyfin -->
          <div class="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-2">
            <span class="font-bold text-white flex items-center gap-1.5">
              <span>🍿</span> Jellyfin Auto-Refresh
            </span>
            <p class="text-zinc-400 text-[11px]">Triggers Jellyfin library scans (<code class="text-zinc-300">/Library/Refresh</code>) automatically.</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-1">
              <input type="text" bind:value={jellyfinUrl} placeholder="http://192.168.0.x:8096"
                class="bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-2.5 py-1.5 text-white text-xs outline-none" />
              <input type="text" bind:value={jellyfinApiKey} placeholder="Jellyfin API Key"
                class="bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-2.5 py-1.5 text-white text-xs outline-none" />
            </div>
          </div>

          <!-- Gemini AI -->
          <div class="p-3.5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-2">
            <span class="font-bold text-white flex items-center gap-1.5">
              <span>✨</span> Gemini AI Music Intelligence
            </span>
            <p class="text-zinc-400 text-[11px]">Powers natural language smart playlist generation and taste profiling.</p>
            <input type="password" bind:value={geminiApiKey} placeholder="AIzaSy..."
              class="w-full bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-lg px-2.5 py-1.5 text-white text-xs outline-none mt-1" />
          </div>
        </div>

        {#if saveError}
          <div class="text-xs text-red-400">{saveError}</div>
        {/if}

        <div class="flex items-center justify-between gap-3 pt-2">
          <button onclick={() => step = "apple"} class="px-4 py-2 text-xs text-zinc-400 hover:text-white transition-colors">
            ← Back
          </button>
          <button onclick={saveIntegrations} disabled={saving}
            class="px-6 py-2.5 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all shadow-sm disabled:opacity-50">
            {saving ? "Saving…" : "Save & Complete Setup ✓"}
          </button>
        </div>
      </div>

    <!-- Step 5: Done -->
    {:else if step === "done"}
      <div class="flex flex-col items-center text-center gap-5 p-8 rounded-2xl bg-[#12100e] border border-white/5 shadow-2xl">
        <div class="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-3xl">
          🎉
        </div>
        <div>
          <h2 class="text-white text-2xl font-bold tracking-tight">Your Workstation is Ready!</h2>
          <p class="text-zinc-400 text-xs mt-2 max-w-md leading-relaxed">
            Pies Pear Music is configured and operational. You can now sync playlists, explore your lossless library, or generate smart AI mixes.
          </p>
        </div>

        <button onclick={ondone}
          class="w-full max-w-sm py-3 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all shadow-lg">
          Open Workstation Dashboard →
        </button>
      </div>
    {/if}

  </div>
</div>
