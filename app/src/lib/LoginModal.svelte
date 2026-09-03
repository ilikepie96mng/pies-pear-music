<script lang="ts">
  import { api } from "../api";

  interface Props {
    onsuccess: () => void;
  }

  let { onsuccess }: Props = $props();

  let password = $state("");
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!password) return;
    loading = true;
    error = null;
    try {
      const res = await api.login(password);
      if (res.authenticated) {
        onsuccess();
      } else {
        error = "Authentication failed";
      }
    } catch (err) {
      error = err instanceof Error ? err.message : "Invalid password";
    } finally {
      loading = false;
    }
  }
</script>

<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
  <div class="w-full max-w-sm rounded-2xl bg-[#12100e] border border-[rgba(252,211,77,0.2)] p-6 shadow-2xl flex flex-col gap-5">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-xl">
        🍐
      </div>
      <div>
        <h2 class="text-white font-bold text-base leading-tight">Pies Pear Music</h2>
        <p class="text-zinc-500 text-xs">Authentication Required</p>
      </div>
    </div>

    <p class="text-zinc-400 text-xs leading-relaxed">
      This music workstation is password protected. Enter your server password to unlock your library.
    </p>

    <form onsubmit={handleSubmit} class="flex flex-col gap-3">
      <div>
        <input
          type="password"
          bind:value={password}
          placeholder="Enter server password"
          autocomplete="current-password"
          required
          class="w-full bg-[#0d0d0d] border border-[#2a2a2a] focus:border-amber-600 rounded-xl px-3.5 py-2.5 text-white text-sm outline-none transition-colors"
        />
      </div>

      {#if error}
        <div class="text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded-lg p-2.5">
          {error}
        </div>
      {/if}

      <button
        type="submit"
        disabled={loading || !password}
        class="w-full py-2.5 rounded-xl text-sm font-bold bg-amber-600 hover:bg-amber-500 text-white transition-all shadow-sm flex items-center justify-center gap-2 disabled:opacity-50"
      >
        {#if loading}
          <span class="w-4 h-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
          <span>Unlocking…</span>
        {:else}
          <span>Unlock Workstation →</span>
        {/if}
      </button>
    </form>
  </div>
</div>
