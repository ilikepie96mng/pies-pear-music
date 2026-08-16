export interface CurrentTrack {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  artwork_url?: string | null;
  format?: string;
}

class PlayerStore {
  currentTrack = $state<CurrentTrack | null>(null);
  isPlaying = $state<boolean>(false);
  currentTime = $state<number>(0);
  duration = $state<number>(0);
  volume = $state<number>(1.0);
  isMuted = $state<boolean>(false);
  audioElement: HTMLAudioElement | null = null;

  initAudio() {
    if (typeof window === "undefined" || this.audioElement) return;
    this.audioElement = new Audio();

    this.audioElement.addEventListener("timeupdate", () => {
      if (this.audioElement) {
        this.currentTime = this.audioElement.currentTime;
      }
    });

    this.audioElement.addEventListener("durationchange", () => {
      if (this.audioElement) {
        this.duration = this.audioElement.duration || 0;
      }
    });

    this.audioElement.addEventListener("ended", () => {
      this.isPlaying = false;
      this.currentTime = 0;
    });

    this.audioElement.addEventListener("play", () => {
      this.isPlaying = true;
    });

    this.audioElement.addEventListener("pause", () => {
      this.isPlaying = false;
    });

    // Media Session API bindings
    if ("mediaSession" in navigator) {
      navigator.mediaSession.setActionHandler("play", () => this.play());
      navigator.mediaSession.setActionHandler("pause", () => this.pause());
      navigator.mediaSession.setActionHandler("stop", () => this.stop());
      navigator.mediaSession.setActionHandler("seekto", (details) => {
        if (details.seekTime !== undefined) {
          this.seek(details.seekTime);
        }
      });
    }
  }

  async playTrack(track: CurrentTrack) {
    this.initAudio();
    if (!this.audioElement) return;

    this.currentTrack = track;
    this.audioElement.src = `http://127.0.0.1:8000/api/v1/stream/${encodeURIComponent(track.track_id)}`;
    this.audioElement.volume = this.isMuted ? 0 : this.volume;

    // Update Media Session
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: track.title,
        artist: track.artist,
        album: track.album,
        artwork: track.artwork_url ? [{ src: track.artwork_url.replace("{w}x{h}", "512x512") }] : [],
      });
    }

    try {
      await this.audioElement.play();
      this.isPlaying = true;
    } catch (e) {
      console.warn("Audio playback autoplay prevented or error:", e);
      this.isPlaying = false;
    }
  }

  play() {
    if (this.audioElement && this.currentTrack) {
      this.audioElement.play().catch(console.warn);
      this.isPlaying = true;
    }
  }

  pause() {
    if (this.audioElement) {
      this.audioElement.pause();
      this.isPlaying = false;
    }
  }

  togglePlay() {
    if (this.isPlaying) {
      this.pause();
    } else {
      this.play();
    }
  }

  stop() {
    if (this.audioElement) {
      this.audioElement.pause();
      this.audioElement.currentTime = 0;
      this.isPlaying = false;
      this.currentTime = 0;
    }
  }

  seek(seconds: number) {
    if (this.audioElement) {
      this.audioElement.currentTime = seconds;
      this.currentTime = seconds;
    }
  }

  setVolume(vol: number) {
    this.volume = Math.max(0, Math.min(1, vol));
    if (this.audioElement) {
      this.audioElement.volume = this.isMuted ? 0 : this.volume;
    }
  }

  toggleMute() {
    this.isMuted = !this.isMuted;
    if (this.audioElement) {
      this.audioElement.volume = this.isMuted ? 0 : this.volume;
    }
  }
}

export const player = new PlayerStore();
