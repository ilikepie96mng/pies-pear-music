import { invoke } from "@tauri-apps/api/core";

interface ApiConnection {
  port: number;
  capability: string;
}

let _connection: ApiConnection | null = null;

async function getConnection(): Promise<ApiConnection> {
  if (_connection !== null) return _connection;
  _connection = await invoke<ApiConnection>("get_api_connection");
  return _connection;
}

async function base(): Promise<string> {
  return `http://127.0.0.1:${(await getConnection()).port}`;
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const connection = await getConnection();
  return fetch(`${await base()}${path}`, {
    ...init,
    headers: {
      "X-Pies-Api-Token": connection.capability,
      ...init.headers,
    },
  });
}

export async function streamEvents(
  path: string,
  onEvent: (event: SyncEvent) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const response = await request(path, { signal });
  if (!response.ok || !response.body) throw new Error(`Stream request failed (${response.status})`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const messages = pending.split("\n\n");
      pending = messages.pop() ?? "";
      for (const message of messages) {
        const data = message
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");
        if (data) await onEvent(JSON.parse(data) as SyncEvent);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export interface Playlist {
  name: string;
  url: string;
  last_synced: string | null;
  paused: boolean;
  thumbnail_url: string | null;
}

export interface Track {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  downloaded_at: string;
  artwork_url: string | null;
  has_lyrics?: boolean;
}

export interface DapExportResult {
  status: string;
  playlist_name: string;
  format: string;
  bitrate: string;
  target_dir: string;
  export_dir: string;
  exported_count: number;
  skipped_count: number;
  error_count: number;
  playlist_file: string;
  files: string[];
}

export interface GraveyardTrack {
  playlist_name: string;
  track_id: string;
  delisted_at: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  artwork_url: string | null;
}

export interface LyricLine {
  time_ms?: number;
  timestamp?: string;
  text: string;
}

export interface TrackLyrics {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  lyrics: string;
  synced: boolean;
  source: "lrc" | "embedded" | "am_api" | "lrclib" | "none";
  lines: LyricLine[];
}

export interface SyncEvent {
  status: "queued" | "running" | "done" | "error";
  position?: number;
  phase?: string;
  message?: string;
  new?: number;
  skipped?: number;
  errors?: number;
  log_path?: string;
}

export interface DuplicateTrackInfo {
  title: string;
  artist: string;
  album: string;
  count: number;
  track_ids: string[];
  tracks: Track[];
}

export interface DeduplicateResult {
  status: string;
  playlist_name: string;
  duplicates_found: number;
  removed_count: number;
  removed_track_ids: string[];
}

export interface IntegrationsHealth {
  gemini: boolean;
  lastfm: boolean;
  jellyfin: boolean;
  navidrome: boolean;
  strawberry: boolean;
}

export interface QueueJob {
  id: string;
  type: "playlist" | "one-off";
  playlist_name: string | null;
  url: string | null;
}

export interface QueueStatus {
  active: QueueJob | null;
  pending: QueueJob[];
}

export interface DiagnosticCheck {
  label: string;
  ok: boolean;
  detail?: string;
}

export interface Stats {
  playlist_count: number;
  total_tracks: number;
  last_sync: string | null;
  playlists: { name: string; track_count: number; last_synced: string | null }[];
}

export interface SyncRun {
  id: number;
  playlist_name: string;
  started_at: string;
  ended_at: string;
  status: "success" | "error";
  new_count: number;
  skipped_count: number;
  error_count: number;
  log_path: string;
  error_message: string | null;
}

export interface RecentTrack {
  title: string;
  artist: string;
  album: string;
  local_path: string;
  artwork_url: string | null;
  downloaded_at: string;
}

export interface Recommendation {
  artist: string;
  similar_to: string;
  reason: string;
  match: number;
  lastfm_url: string;
}

export interface RecommendedTrack {
  name: string;
  url: string;
  artist: string;
}

export interface RecommendedAlbum {
  name: string;
  url: string;
  artist: string;
  image_url: string | null;
}

export interface HomeData {
  recent_tracks: RecentTrack[];
  recommendations: Recommendation[];
  recommended_tracks: RecommendedTrack[];
  recommended_albums: RecommendedAlbum[];
  recommendations_available: boolean;
  recommendation_source: "live" | "cached" | "unavailable";
  recommendations_updated_at: string | null;
  last_sync: { run_id: number; playlist_name: string; started_at: string; synced_at: string; new_tracks: number } | null;
}

export interface LibraryTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  downloaded_at: string;
  artwork_url: string | null;
  playlists: string[];
  has_lyrics: boolean;
  format: string;
  file_size: number;
  exists_on_disk: boolean;
}

export interface LibraryStats {
  total_tracks: number;
  total_albums: number;
  total_artists: number;
  total_playlists: number;
  delisted_count: number;
  total_bytes: number;
}

export interface AuditMissingTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  playlists?: string[];
}

export interface AuditOrphanFile {
  path: string;
  name: string;
  size: number;
  relative_path: string;
}

export interface LibraryAuditReport {
  missing_files: AuditMissingTrack[];
  orphaned_files: AuditOrphanFile[];
  missing_lyrics: AuditMissingTrack[];
  missing_art: AuditMissingTrack[];
  summary: {
    total_db_tracks: number;
    missing_files_count: number;
    orphaned_files_count: number;
    missing_lyrics_count: number;
    missing_art_count: number;
  };
}

export interface IntegrityErrorTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  error: string;
}

export interface LibraryIntegrityReport {
  checked_count: number;
  corrupted: IntegrityErrorTrack[];
  status: "ok" | "errors_found";
}

export interface LibraryRepairResult {
  status?: string;
  action?: string;
  pruned_count?: number;
  repaired_count?: number;
  playlists?: string[];
  adopted_count?: number;
  adopted?: { track_id: string; title: string; artist: string; album: string; local_path: string }[];
}

export interface DownloadRequestItem {
  id: string;
  url: string;
  format: string;
  requester: string;
  status: string;
  notes: string;
  created_at: string;
}

export interface ImportMatchResult {
  original_title: string;
  original_artist: string;
  original_album: string;
  original_isrc: string;
  matched: boolean;
  match_score: number;
  am_track?: {
    id: string;
    title: string;
    artist: string;
    album: string;
    url?: string;
  } | null;
}

export interface GeminiPlaylistResult {
  playlist_title: string;
  description: string;
  vibe_tags: string[];
  tracks: {
    title: string;
    artist: string;
    album: string;
    rationale: string;
    matched?: boolean;
    am_track?: {
      id: string;
      title: string;
      artist: string;
      album: string;
    } | null;
  }[];
}

export const api = {
  async playlists(): Promise<Playlist[]> {
    const r = await request("/playlists");
    return r.json();
  },

  async addPlaylist(name: string, url: string): Promise<Playlist> {
    const r = await request("/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, url }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deletePlaylist(name: string): Promise<void> {
    await request(`/playlists/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
  },

  async patchPlaylist(name: string, patch: { name?: string; paused?: boolean }): Promise<Playlist> {
    const r = await request(`/playlists/${encodeURIComponent(name)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async library(): Promise<Record<string, Track[]>> {
    const r = await request("/library");
    return r.json();
  },

  async allLibraryTracks(): Promise<LibraryTrack[]> {
    const r = await request("/library/tracks");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async libraryStats(): Promise<LibraryStats> {
    const r = await request("/library/stats");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async auditLibrary(): Promise<LibraryAuditReport> {
    const r = await request("/library/audit");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async verifyIntegrity(limit?: number): Promise<LibraryIntegrityReport> {
    const r = await request("/library/verify-integrity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async repairLibrary(action: string, payload?: { track_ids?: string[]; file_paths?: string[] }): Promise<LibraryRepairResult> {
    const r = await request("/library/repair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...payload }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Repair failed (${r.status})`);
    }
    return r.json();
  },

  async trackArtUrl(localPath: string): Promise<string> {
    const response = await request(`/track-art?path=${encodeURIComponent(localPath)}`);
    if (!response.ok) return "";
    return URL.createObjectURL(await response.blob());
  },

  async stats(): Promise<Stats> {
    const r = await request("/stats");
    return r.json();
  },

  async diagnostics(): Promise<DiagnosticCheck[]> {
    const r = await request("/diagnostics");
    return r.json();
  },

  async queue(): Promise<QueueStatus> {
    const r = await request("/sync/queue");
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async config(): Promise<Record<string, any>> {
    const r = await request("/config");
    return r.json();
  },

  async updateConfig(updates: Partial<Record<string, any>>): Promise<void> {
    const r = await request("/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async testJellyfin(serverUrl: string, apiKey: string): Promise<{ success: boolean; message: string }> {
    const r = await request("/integrations/jellyfin/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_url: serverUrl, api_key: apiKey }),
    });
    return r.json();
  },

  async testNavidrome(serverUrl: string, user: string, token: string, salt: string): Promise<{ success: boolean; message: string }> {
    const r = await request("/integrations/navidrome/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_url: serverUrl, user, token, salt }),
    });
    return r.json();
  },

  async downloadRequests(status?: string): Promise<DownloadRequestItem[]> {
    const url = status ? `/api/v1/requests?status=${encodeURIComponent(status)}` : "/api/v1/requests";
    const r = await request(url);
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async createDownloadRequest(url: string, format: string = "ALAC", requester: string = "local", notes: string = ""): Promise<DownloadRequestItem> {
    const r = await request("/api/v1/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format, requester, notes }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async parsePlaylistImport(sourceType: "url" | "csv" | "m3u", content: string): Promise<{ source_type: string; track_count: number; matches: ImportMatchResult[] }> {
    const r = await request("/playlist/parse-import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_type: sourceType, content }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async curateGemini(prompt: string, trackCount: number = 20, model?: string): Promise<GeminiPlaylistResult> {
    const r = await request("/gemini/curate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, track_count: trackCount, model: model || undefined }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Gemini curation failed");
    }
    return r.json();
  },

  async getGeminiModels(): Promise<string[]> {
    const r = await request("/gemini/models");
    if (!r.ok) return [];
    const data = await r.json().catch(() => ({ models: [] }));
    return data.models || [];
  },

  async saveGeminiPlaylist(name: string, tracks: unknown[], prompt: string = ""): Promise<Playlist> {
    const r = await request("/gemini/save-playlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, tracks, prompt }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to save playlist");
    }
    return r.json();
  },

  async home(): Promise<HomeData> {
    const r = await request("/home");
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async libraryProfile(): Promise<Record<string, unknown>> {
    const r = await request("/library-profile");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async excludeRecommendationArtist(artist: string): Promise<void> {
    const r = await request("/recommendations/exclusions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist }),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async recommendationExclusions(): Promise<string[]> {
    const r = await request("/recommendations/exclusions");
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json() as { artists: string[] };
    return data.artists;
  },

  async includeRecommendationArtist(artist: string): Promise<void> {
    const r = await request(`/recommendations/exclusions/${encodeURIComponent(artist)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
  },

  async clearRecommendationExclusions(): Promise<void> {
    const r = await request("/recommendations/exclusions", { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
  },

  async recommendationPreferences(): Promise<{ genres: string[] }> {
    const r = await request("/recommendations/preferences");
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateRecommendationPreferences(genres: string[]): Promise<{ genres: string[] }> {
    const r = await request("/recommendations/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ genres }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async syncRunTracks(runId: number): Promise<{ run_id: number; playlist_name: string; tracks: RecentTrack[] }> {
    const r = await request(`/sync-runs/${runId}/tracks`);
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },

  async strawberryExport(playlistName: string): Promise<{ removed: number; inserted: number; playlist_id: number; backup: string }> {
    const r = await request("/strawberry/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playlist_name: playlistName }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `${r.status}`);
    }
    return r.json();
  },

  async playlistM3u(playlistName: string): Promise<string> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/m3u`);
    if (!r.ok) throw new Error(await r.text());
    return r.text();
  },

  async savePlaylistM3u(playlistName: string, path: string): Promise<void> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/m3u/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async revealTrack(localPath: string): Promise<void> {
    const r = await request("/reveal-track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ local_path: localPath }),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async syncHistory(playlistName?: string, limit = 30): Promise<SyncRun[]> {
    const url = playlistName
      ? `/sync-history/${encodeURIComponent(playlistName)}?limit=${limit}`
      : `/sync-history?limit=${limit}`;
    const r = await request(url);
    return r.json();
  },

  async exportDap(
    playlistName: string,
    targetDir: string,
    format: string = "opus",
    bitrate?: string,
  ): Promise<DapExportResult> {
    const r = await request("/export/dap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist_name: playlistName,
        target_dir: targetDir,
        format,
        ...(bitrate ? { bitrate } : {}),
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Export failed (${r.status})`);
    }
    return r.json();
  },

  async getStreamingGraveyard(playlistName?: string): Promise<{ tracks: GraveyardTrack[]; count: number }> {
    const url = playlistName
      ? `/streaming-graveyard?playlist_name=${encodeURIComponent(playlistName)}`
      : "/streaming-graveyard";
    const r = await request(url);
    if (!r.ok) throw new Error(`Failed to load streaming graveyard (${r.status})`);
    return r.json();
  },

  async getTrackLyrics(trackId: string): Promise<TrackLyrics> {
    const r = await request(`/tracks/${encodeURIComponent(trackId)}/lyrics`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to load lyrics (${r.status})`);
    }
    return r.json();
  },

  async getStreamUrl(trackId: string): Promise<string> {
    const conn = await getConnection();
    return `http://127.0.0.1:${conn.port}/api/v1/stream/${encodeURIComponent(trackId)}?token=${encodeURIComponent(conn.capability)}`;
  },

  async getPlaylistDuplicates(playlistName: string): Promise<{ playlist_name: string; duplicates: DuplicateTrackInfo[]; count: number }> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/duplicates`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deduplicatePlaylist(playlistName: string): Promise<DeduplicateResult> {
    const r = await request(`/playlists/${encodeURIComponent(playlistName)}/deduplicate`, {
      method: "POST",
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async getIntegrationsHealth(): Promise<IntegrationsHealth> {
    const r = await request("/system/integrations-health");
    if (!r.ok) {
      return { gemini: false, lastfm: false, jellyfin: false, navidrome: false, strawberry: false };
    }
    return r.json();
  },

  wrapper: {
    async login(email: string, password: string): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      return r.json();
    },

    async stop(): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/stop", { method: "POST" });
      return r.json();
    },

    async submit2fa(code: string): Promise<{ status: string; msg: string }> {
      const r = await request("/wrapper/2fa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      return r.json();
    },

    async status(): Promise<{ running: boolean; needs_2fa: boolean; "2fa_type": string; logs: string[] }> {
      const r = await request("/wrapper/status");
      return r.json();
    },
  },
};
