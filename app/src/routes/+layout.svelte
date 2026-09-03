<script lang="ts">
  import { onMount } from 'svelte';
  import '../app.css';
  import { applyTheme, getStoredTheme, applyWallpaper, getStoredWallpaper } from '$lib/themes';
  let { children } = $props();

  onMount(() => {
    applyTheme(getStoredTheme());
    const wp = getStoredWallpaper();
    applyWallpaper(wp.image, wp.dim, wp.blur);
  });
</script>

<div class="wallpaper-layer" aria-hidden="true"></div>
<div class="wallpaper-overlay" aria-hidden="true"></div>
<div class="app-root h-screen w-screen overflow-hidden">
  {@render children()}
</div>
