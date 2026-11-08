"""Field-speaker audio: plays announcement clips from the server's own sound
card (the headphone jack into the field PA), one at a time from a queue.

Clips are WAV files in sounds/field/<clip>.wav (16-bit PCM; generated from
server/voice_clips.csv by tools/make_clips.py). WAV, not MP3, so the server
needs no decoder.

Playback backends, first available wins:
  aplay   the standard ALSA command-line player (package alsa-utils)
  alsa    libasound called directly through ctypes, for servers that have
          the ALSA library but not alsa-utils (no install needed)
  none    no usable sound output; clips are logged and skipped
Force one with the AIRSOFT_AUDIO_BACKEND environment variable.
"""
import ctypes
import ctypes.util
import os
import queue
import shutil
import subprocess
import threading
import time
import wave

from . import config, hub, settings

CLIPS_DIR = os.path.join(config.SOUNDS_DIR, "field")
MAX_QUEUE = 6                 # announcements, not music: drop extras rather than lag


class _AlsaCtypes:
    """Just enough of libasound to play a 16-bit PCM WAV file."""
    SND_PCM_STREAM_PLAYBACK = 0
    SND_PCM_FORMAT_S16_LE = 2
    SND_PCM_ACCESS_RW_INTERLEAVED = 3

    def __init__(self):
        name = ctypes.util.find_library("asound")
        if not name:
            raise OSError("libasound not found")
        self.lib = ctypes.CDLL(name)
        self.lib.snd_pcm_writei.restype = ctypes.c_long
        self.lib.snd_strerror.restype = ctypes.c_char_p

    def _check(self, rc, what):
        if rc < 0:
            raise OSError(f"{what}: {self.lib.snd_strerror(rc).decode()}")

    def play(self, path):
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                raise OSError(f"{os.path.basename(path)}: only 16-bit WAV is supported")
            channels, rate = w.getnchannels(), w.getframerate()
            frames = w.readframes(w.getnframes())
        pcm = ctypes.c_void_p()
        self._check(self.lib.snd_pcm_open(ctypes.byref(pcm), b"default",
                                          self.SND_PCM_STREAM_PLAYBACK, 0), "open")
        try:
            self._check(self.lib.snd_pcm_set_params(
                pcm, self.SND_PCM_FORMAT_S16_LE, self.SND_PCM_ACCESS_RW_INTERLEAVED,
                channels, rate, 1, 500000), "set_params")
            frame_bytes = 2 * channels
            buf = ctypes.create_string_buffer(frames)
            total = len(frames) // frame_bytes
            done = 0
            while done < total:
                ptr = ctypes.byref(buf, done * frame_bytes)
                n = self.lib.snd_pcm_writei(pcm, ptr, total - done)
                if n < 0:
                    self._check(self.lib.snd_pcm_recover(pcm, int(n), 1), "write")
                    continue
                done += n
            self.lib.snd_pcm_drain(pcm)
        finally:
            self.lib.snd_pcm_close(pcm)


def _pick_backend():
    want = os.environ.get("AIRSOFT_AUDIO_BACKEND", "").strip().lower()
    if want in ("", "aplay") and shutil.which("aplay"):
        return "aplay", None
    if want in ("", "alsa"):
        try:
            return "alsa", _AlsaCtypes()
        except OSError as e:
            print(f"[audio] ALSA library unavailable: {e}")
    return "none", None


_backend, _alsa = _pick_backend()
_q = queue.Queue()
_lock = threading.Lock()
_state = {"enabled": settings.load().get("audio", {}).get("enabled", True),
          "playing": None, "last": None, "last_error": None}


def clip_path(clip):
    return os.path.join(CLIPS_DIR, f"{clip}.wav")


def have(clip):
    return os.path.isfile(clip_path(clip))


def status():
    with _lock:
        return {"kind": "audio", "backend": _backend, "enabled": _state["enabled"],
                "playing": _state["playing"], "queued": _q.qsize(),
                "last": _state["last"], "last_error": _state["last_error"]}


def _announce_status():
    hub.broadcast(status())


def set_enabled(on):
    with _lock:
        _state["enabled"] = bool(on)
    settings.save("audio", {"enabled": bool(on)})
    _announce_status()


def play(clip, force=False):
    """Queue a clip. force=True plays even with the speaker switched off (the
    referee's Test / play-now buttons). Returns False if it was skipped."""
    with _lock:
        enabled = _state["enabled"]
    if not (enabled or force):
        return False
    if not have(clip):
        with _lock:
            _state["last_error"] = f"missing clip: {clip}.wav"
        print(f"[audio] missing clip {clip_path(clip)}")
        _announce_status()
        return False
    if _q.qsize() >= MAX_QUEUE:
        print(f"[audio] queue full, dropping {clip}")
        return False
    _q.put(clip)
    _announce_status()
    return True


def _play_file(path):
    if _backend == "aplay":
        r = subprocess.run(["aplay", "-q", path], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise OSError((r.stderr or "aplay failed").strip().splitlines()[-1])
    elif _backend == "alsa":
        _alsa.play(path)
    else:
        raise OSError("no sound output available on this server")


def _worker():
    while True:
        clip = _q.get()
        with _lock:
            _state["playing"] = clip
        _announce_status()
        err = None
        try:
            _play_file(clip_path(clip))
            print(f"[audio] played {clip}")
        except Exception as e:  # noqa: BLE001 — never let audio kill the thread
            err = f"{clip}: {e}"
            print(f"[audio] {err}")
            time.sleep(0.5)
        with _lock:
            _state["playing"] = None
            _state["last"] = clip
            if err:
                _state["last_error"] = err
        _announce_status()


def start():
    print(f"[audio] backend: {_backend}; clips in {CLIPS_DIR}; "
          f"speaker {'on' if _state['enabled'] else 'off'}")
    threading.Thread(target=_worker, daemon=True).start()
