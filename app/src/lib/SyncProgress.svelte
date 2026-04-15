<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type SyncEvent } from "../api";

  interface Props {
    playlistName: string;
    ondone: () => void;
  }
  let { playlistName, ondone }: Props = $props();

  let status = $state<"running" | "done" | "error">("running");
  let newSoFar = $state(0);
  let result = $state<{ new: number; skipped: number; errors: number } | null>(null);
  let errorMessage = $state<string | null>(null);
  let source: EventSource | null = null;

  onMount(async () => {
    const url = await api.syncUrl(playlistName);
    source = new EventSource(url);

    source.onmessage = (e) => {
      const data: SyncEvent = JSON.parse(e.data);
      status = data.status;
      if (data.status === "running") {
        newSoFar = data.new_so_far ?? 0;
      } else if (data.status === "done") {
        result = { new: data.new ?? 0, skipped: data.skipped ?? 0, errors: data.errors ?? 0 };
        source?.close();
      } else if (data.status === "error") {
        errorMessage = data.message ?? "Unknown error";
        source?.close();
      }
    };

    source.onerror = () => {
      if (status === "running") {
        status = "error";
        errorMessage = "Lost connection to sync server.";
      }
      source?.close();
    };
  });

  onDestroy(() => source?.close());
</script>

<div class="p-8 flex flex-col items-center justify-center min-h-full">
  <div class="w-full max-w-md">
    <h2 class="text-white text-xl font-bold mb-2">{playlistName}</h2>

    {#if status === "running"}
      <p class="text-zinc-400 text-sm mb-4">
        Downloading and syncing… <span class="text-white font-bold">{newSoFar}</span> new tracks so far
      </p>
      <div class="h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
        <div class="h-full bg-[#1db954] rounded-full w-full animate-pulse"></div>
      </div>

    {:else if status === "done" && result}
      <div class="bg-[#1a1a1a] rounded-xl p-6 border border-[#222] mt-4">
        <div class="text-[#1db954] font-bold text-base mb-4">✓ Sync complete</div>
        <div class="flex gap-8 text-sm">
          <div><div class="text-white font-bold text-2xl">{result.new}</div><div class="text-zinc-500 mt-0.5">new</div></div>
          <div><div class="text-white font-bold text-2xl">{result.skipped}</div><div class="text-zinc-500 mt-0.5">skipped</div></div>
          <div>
            <div class="font-bold text-2xl {result.errors > 0 ? 'text-red-400' : 'text-white'}">{result.errors}</div>
            <div class="text-zinc-500 mt-0.5">errors</div>
          </div>
        </div>
      </div>
      <button onclick={ondone}
        class="mt-4 w-full bg-[#1db954] text-black font-bold py-2 rounded-lg hover:bg-[#1ed760] transition-colors">
        Back to library
      </button>

    {:else if status === "error"}
      <div class="bg-red-950 border border-red-800 rounded-xl p-4 mt-4">
        <div class="text-red-400 font-bold mb-2">Sync failed</div>
        <pre class="text-red-300 text-xs overflow-auto max-h-48 whitespace-pre-wrap">{errorMessage}</pre>
      </div>
      <button onclick={ondone} class="mt-4 text-zinc-500 hover:text-white text-sm transition-colors">← Back</button>
    {/if}
  </div>
</div>
