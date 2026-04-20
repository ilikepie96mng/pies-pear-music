<script lang="ts">
  import { api, type DiagnosticCheck } from "../api";

  interface Props {
    ondone: () => void;
  }

  let { ondone }: Props = $props();

  type Step = "welcome" | "environment" | "configure" | "done";
  const STEPS: Step[] = ["welcome", "environment", "configure", "done"];
  let step = $state<Step>("welcome");
  let stepIndex = $derived(STEPS.indexOf(step));

  // --- Environment step ---
  let checks = $state<DiagnosticCheck[]>([]);
  let loadingChecks = $state(false);
  let checksError = $state<string | null>(null);

  // Labels that block proceeding if failed
  const CRITICAL = new Set(["Config file", "Music directory"]);

  let criticalFailed = $derived(checks.some(c => CRITICAL.has(c.label) && !c.ok));

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

  // Group checks for display
  const GROUPS: { title: string; labels: string[] }[] = [
    { title: "System tools",  labels: ["ffmpeg", "Git"] },
    { title: "Configuration", labels: ["Config file", "Music directory", "State directory"] },
    { title: "Automation",    labels: ["Systemd timer"] },
  ];

  function checksForGroup(labels: string[]): DiagnosticCheck[] {
    return labels.map(l => checks.find(c => c.label === l) ?? { label: l, ok: false, detail: "not checked" });
  }

  // --- Configure step ---
  let cfg = $state<Record<string, string>>({});
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saved = $state(false);

  const configFields = [
    { key: "alac_rip_dir",  label: "alac-rip directory", hint: "Path to your alac-rip clone (contains wrapper/ and apple-music-downloader/)" },
    { key: "music_dir",     label: "Music directory",    hint: "Where synced ALAC files are stored" },
    { key: "state_dir",     label: "State directory",    hint: "Where the track database and sync logs are stored" },
    { key: "github_remote", label: "GitHub remote",      hint: "Optional — push state DB to a remote repo. Leave blank to skip." },
  ];

  async function loadConfig() {
    try { cfg = await api.config(); } catch {}
  }

  async function saveConfig() {
    saving = true;
    saveError = null;
    try {
      const updates: Record<string, string> = Object.fromEntries(
        configFields.map(f => [f.key, cfg[f.key] ?? ""])
      );
      await api.updateConfig(updates);
      saved = true;
      setTimeout(() => (saved = false), 2000);
    } catch (e) {
      saveError = String(e);
    } finally {
      saving = false;
    }
  }

  // Step transitions
  function goEnvironment() {
    step = "environment";
    runChecks();
  }

  async function goConfigure() {
    step = "configure";
    await loadConfig();
  }
</script>

<div class="flex h-full items-center justify-center bg-[#0f0f0f] p-8">
  <div class="w-full max-w-xl">

    <!-- Step indicator -->
    <div class="flex items-center gap-2 mb-8 justify-center">
      {#each STEPS as s, i}
        <div class="flex items-center gap-2">
          <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-colors
            {step === s ? 'bg-amber-600 text-white' : stepIndex > i ? 'bg-[#333] text-[#888]' : 'bg-[#1a1a1a] text-[#555]'}">
            {stepIndex > i ? "✓" : i + 1}
          </div>
          {#if i < STEPS.length - 1}
            <div class="w-8 h-px {stepIndex > i ? 'bg-[#444]' : 'bg-[#222]'}"></div>
          {/if}
        </div>
      {/each}
    </div>

    <!-- Step: Welcome -->
    {#if step === "welcome"}
      <div class="flex flex-col gap-6">
        <div>
          <div class="text-amber-500 text-xs font-semibold uppercase tracking-widest mb-2">Setup</div>
          <h1 class="text-white text-3xl font-bold tracking-tight leading-tight">Welcome to pies-alac-rip</h1>
          <p class="text-zinc-500 text-sm mt-3 leading-relaxed">
            A Linux-native music library sync tool. This wizard will verify your environment
            and configure your paths before your first sync.
          </p>
        </div>

        <div class="border border-[#222] rounded-xl p-4 flex flex-col gap-2 bg-[#111]">
          <div class="text-zinc-400 text-xs font-semibold uppercase tracking-widest mb-1">What we'll check</div>
          {#each ["System tools (ffmpeg, Git)", "Configuration (directories, config file)", "Automation (systemd timer)"] as item}
            <div class="flex items-center gap-2 text-sm text-zinc-400">
              <span class="text-amber-600 text-xs">◆</span> {item}
            </div>
          {/each}
        </div>

        <button onclick={goEnvironment}
          class="w-full bg-amber-700 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition-colors text-sm">
          Check environment →
        </button>
      </div>

    <!-- Step: Environment -->
    {:else if step === "environment"}
      <div class="flex flex-col gap-5">
        <div>
          <div class="text-amber-500 text-xs font-semibold uppercase tracking-widest mb-2">Environment</div>
          <h2 class="text-white text-2xl font-bold tracking-tight">Dependency check</h2>
        </div>

        {#if loadingChecks}
          <div class="flex items-center gap-3 text-zinc-500 text-sm py-8 justify-center">
            <div class="w-4 h-4 border-2 border-zinc-600 border-t-amber-500 rounded-full animate-spin"></div>
            Checking…
          </div>
        {:else if checksError}
          <div class="bg-red-950 border border-red-800 rounded-xl p-4 text-red-400 text-sm">{checksError}</div>
        {:else if checks.length}
          <div class="flex flex-col gap-3">
            {#each GROUPS as group}
              <div class="border border-[#1e1e1e] rounded-xl overflow-hidden">
                <div class="px-4 py-2 bg-[#111] border-b border-[#1e1e1e]">
                  <span class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold">{group.title}</span>
                </div>
                <div class="divide-y divide-[#1a1a1a]">
                  {#each checksForGroup(group.labels) as check}
                    <div class="flex items-center gap-3 px-4 py-2.5">
                      <span class="text-base {check.ok ? 'text-green-500' : CRITICAL.has(check.label) ? 'text-red-500' : 'text-amber-500'}">
                        {check.ok ? "✓" : "✗"}
                      </span>
                      <span class="text-sm text-white flex-1">{check.label}</span>
                      {#if check.detail && !check.ok}
                        <span class="text-zinc-600 text-xs truncate max-w-[160px]" title={check.detail}>{check.detail}</span>
                      {:else if check.detail && check.ok}
                        <span class="text-zinc-700 text-xs truncate max-w-[160px]" title={check.detail}>{check.detail}</span>
                      {/if}
                    </div>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        {/if}

        <div class="flex gap-2">
          <button onclick={runChecks} disabled={loadingChecks}
            class="px-4 py-2 rounded-lg text-sm text-zinc-400 hover:text-white bg-[#1a1a1a] hover:bg-[#222] transition-colors disabled:opacity-50">
            Recheck
          </button>
          <button onclick={goConfigure}
            class="flex-1 py-2 rounded-lg text-sm font-bold transition-colors
              {criticalFailed
                ? 'bg-[#1a1a1a] text-zinc-500 cursor-default'
                : 'bg-amber-700 hover:bg-amber-600 text-white'}">
            {criticalFailed ? "Resolve critical issues to continue" : "Configure credentials →"}
          </button>
        </div>

        {#if !criticalFailed && checks.some(c => !c.ok)}
          <p class="text-zinc-600 text-xs text-center">Some non-critical checks failed — you can still continue.</p>
        {/if}
      </div>

    <!-- Step: Configure -->
    {:else if step === "configure"}
      <div class="flex flex-col gap-5">
        <div>
          <div class="text-amber-500 text-xs font-semibold uppercase tracking-widest mb-2">Configuration</div>
          <h2 class="text-white text-2xl font-bold tracking-tight">Paths & settings</h2>
          <p class="text-zinc-500 text-sm mt-1">These are saved to <code class="text-zinc-400">~/.config/pies-alac-rip/config.yaml</code>.</p>
        </div>

        <div class="flex flex-col gap-3">
          {#each configFields as field}
            <label class="flex flex-col gap-1">
              <span class="text-zinc-400 text-[10px] uppercase tracking-widest font-semibold">{field.label}</span>
              <input bind:value={cfg[field.key]} type="text"
                class="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-amber-700 transition-colors" />
              <span class="text-zinc-600 text-[10px]">{field.hint}</span>
            </label>
          {/each}
        </div>

        {#if saveError}
          <div class="bg-red-950 border border-red-800 rounded-xl p-3 text-red-400 text-sm">{saveError}</div>
        {/if}

        <div class="flex gap-2">
          <button onclick={saveConfig} disabled={saving}
            class="flex-1 bg-amber-700 hover:bg-amber-600 text-white font-bold py-2.5 rounded-xl transition-colors text-sm disabled:opacity-50">
            {saving ? "Saving…" : saved ? "✓ Saved" : "Save configuration"}
          </button>
          <button onclick={() => (step = "done")}
            class="px-4 py-2.5 rounded-xl text-sm text-zinc-400 hover:text-white bg-[#1a1a1a] hover:bg-[#222] transition-colors">
            Skip →
          </button>
        </div>

        {#if saved}
          <button onclick={() => (step = "done")}
            class="w-full text-center text-amber-500 text-sm hover:text-amber-400 transition-colors">
            Continue to finish →
          </button>
        {/if}
      </div>

    <!-- Step: Done -->
    {:else if step === "done"}
      <div class="flex flex-col gap-6 text-center">
        <div>
          <div class="text-5xl mb-4">◆</div>
          <div class="text-amber-500 text-xs font-semibold uppercase tracking-widest mb-2">Complete</div>
          <h2 class="text-white text-2xl font-bold tracking-tight">You're all set</h2>
          <p class="text-zinc-500 text-sm mt-3">
            Add a playlist from the sidebar, then hit <strong class="text-white">Sync All</strong> to start your first download.
          </p>
        </div>

        <div class="border border-[#1e1e1e] rounded-xl p-4 bg-[#111] text-left flex flex-col gap-2">
          <div class="text-zinc-500 text-[10px] uppercase tracking-widest font-semibold mb-1">Quick start</div>
          {#each [
            "Add a playlist via the sidebar (name + URL)",
            "Place downloaded .m4a files in the staging directory",
            "Click Sync — live progress will appear",
          ] as tip, i}
            <div class="flex items-start gap-3 text-sm text-zinc-400">
              <span class="text-amber-600 font-bold mt-0.5">{i + 1}</span>
              <span>{tip}</span>
            </div>
          {/each}
        </div>

        <button onclick={ondone}
          class="w-full bg-amber-700 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition-colors text-sm">
          Open the app →
        </button>
      </div>
    {/if}

  </div>
</div>
