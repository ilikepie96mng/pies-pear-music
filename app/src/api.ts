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
  source: "lrc" | "embedded" | "am_api" | "none";
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

  async config(): Promise<Record<string, string>> {
    const r = await request("/config");
    return r.json();
  },

  async updateConfig(updates: Partial<Record<string, string>>): Promise<void> {
    const r = await request("/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!r.ok) throw new Error(await r.text());
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
