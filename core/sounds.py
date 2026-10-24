"""Procedural sound engine — everything is generated with numpy, no assets needed.
WAVs are cached in ~/.python_photoshop_sounds/."""
import wave
import math
from pathlib import Path

try:
    import numpy as np
    _HAVE_NUMPY = True
except Exception:
    _HAVE_NUMPY = False

from PyQt5.QtCore import QUrl
import shutil
import subprocess

try:
    from PyQt5.QtMultimedia import QSoundEffect
    _HAVE_MULTIMEDIA = True
except Exception:
    QSoundEffect = None  # type: ignore
    _HAVE_MULTIMEDIA = False


def _find_cli_player():
    for exe, args in (
        ('paplay', []),
        ('pw-play', []),
        ('aplay', ['-q']),
        ('ffplay', ['-nodisp', '-autoexit', '-loglevel', 'quiet']),
    ):
        if shutil.which(exe):
            return exe, args
    return None, None


CACHE_DIR = Path.home() / ".python_photoshop_sounds"
CACHE_DIR.mkdir(exist_ok=True)
SAMPLE_RATE = 44100


# ---------------------------------------------------------------- synthesis
def _write_wav(path: Path, samples: "np.ndarray") -> None:
    """Write float [-1,1] mono as 16-bit PCM."""
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def _envelope(n: int, attack=0.01, release=0.2) -> "np.ndarray":
    """Simple attack/release envelope."""
    a = max(1, int(attack * SAMPLE_RATE))
    r = max(1, int(release * SAMPLE_RATE))
    env = np.ones(n, dtype=np.float32)
    if a < n:
        env[:a] = np.linspace(0, 1, a)
    if r < n:
        env[-r:] *= np.linspace(1, 0, r)
    return env


def _tone(freq: float, dur: float, kind="sine", amp=0.4,
          attack=0.01, release=0.2, detune=0.0) -> "np.ndarray":
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    if kind == "sine":
        wave_data = np.sin(2 * np.pi * freq * t)
    elif kind == "square":
        wave_data = np.sign(np.sin(2 * np.pi * freq * t))
    elif kind == "tri":
        wave_data = 2 * np.abs(2 * ((t * freq) % 1) - 1) - 1
    elif kind == "saw":
        wave_data = 2 * ((t * freq) % 1) - 1
    else:
        wave_data = np.sin(2 * np.pi * freq * t)
    if detune:
        wave_data += 0.5 * np.sin(2 * np.pi * (freq + detune) * t)
        wave_data *= 0.66
    return (wave_data * amp * _envelope(n, attack, release)).astype(np.float32)


def _noise(dur: float, amp=0.2, attack=0.005, release=0.15,
           lowpass=0.05) -> "np.ndarray":
    n = int(dur * SAMPLE_RATE)
    noise = np.random.uniform(-1, 1, n).astype(np.float32)
    # crude one-pole lowpass
    if lowpass > 0:
        filtered = np.zeros_like(noise)
        acc = 0.0
        for i in range(n):
            acc += lowpass * (noise[i] - acc)
            filtered[i] = acc
        noise = filtered
    return (noise * amp * _envelope(n, attack, release)).astype(np.float32)


def _concat(*parts) -> "np.ndarray":
    return np.concatenate(parts)


def _mix(a, b) -> "np.ndarray":
    n = min(len(a), len(b))
    return (a[:n] * 0.6 + b[:n] * 0.6).astype(np.float32)


# ---------------------------------------------------------------- sound bank
def _build_sounds():
    """Return {name: np.ndarray}. Fails gracefully to empty when numpy missing."""
    sounds = {}
    if not _HAVE_NUMPY:
        return sounds

    # startup chime — rising arpeggio with a soft tail
    sounds["startup"] = _concat(
        _tone(523.25, 0.18, amp=0.35, release=0.05),   # C5
        _tone(659.25, 0.18, amp=0.35, release=0.05),   # E5
        _tone(783.99, 0.35, amp=0.40, release=0.30),   # G5
    )

    # seamless looping "scratch" for continuous drawing
    loop_len = 1.0
    n = int(loop_len * SAMPLE_RATE)
    noise = np.random.uniform(-1, 1, n).astype(np.float32)
    # lowpass a bit
    acc = 0.0
    filt = np.zeros_like(noise)
    for i in range(n):
        acc += 0.12 * (noise[i] - acc)
        filt[i] = acc
    # fade ends to make loop seamless
    fade = int(0.08 * SAMPLE_RATE)
    filt[:fade] *= np.linspace(0, 1, fade)
    filt[-fade:] *= np.linspace(1, 0, fade)
    sounds["brush_loop"] = (filt * 0.20).astype(np.float32)

    # brush stroke — soft, short noise with a low tone
    sounds["brush"] = _mix(
        _noise(0.08, amp=0.10, lowpass=0.15),
        _tone(220, 0.08, amp=0.05, release=0.05)
    )

    # eraser — similar but higher hiss
    sounds["eraser"] = _noise(0.10, amp=0.12, lowpass=0.4)

    # pencil — clicky tick
    sounds["pencil"] = _tone(1200, 0.04, kind="square", amp=0.08, release=0.03)

    # blur tool — soft whoosh (filtered noise)
    sounds["blur"] = _noise(0.15, amp=0.08, lowpass=0.08)

    # 3D brush — metallic pluck
    sounds["3d_brush"] = _mix(
        _tone(660, 0.06, kind="tri", amp=0.12, release=0.04),
        _tone(990, 0.06, kind="sine", amp=0.06, release=0.04)
    )

    # bucket fill — glug
    sounds["bucket"] = _mix(
        _tone(160, 0.22, kind="tri", amp=0.25, release=0.18),
        _noise(0.22, amp=0.06, lowpass=0.05)
    )

    # lasso — zipper-ish sweep
    sounds["lasso"] = _tone(880, 0.12, kind="tri", amp=0.10, release=0.08)

    # text commit — typewriter ding
    sounds["text"] = _mix(
        _tone(880, 0.10, kind="sine", amp=0.15, release=0.06),
        _tone(1320, 0.10, kind="sine", amp=0.10, release=0.06)
    )

    # image import — soft rising chime
    sounds["image"] = _concat(
        _tone(440, 0.12, amp=0.20, release=0.05),
        _tone(587.33, 0.20, amp=0.25, release=0.15),
    )

    # shape created — soft "boop"
    sounds["shape"] = _tone(392, 0.12, kind="tri", amp=0.20, release=0.10)

    # layer added — quick pop
    sounds["layer_new"] = _tone(660, 0.06, kind="square", amp=0.12, release=0.05)

    # layer deleted — descending
    sounds["layer_del"] = _concat(
        _tone(660, 0.07, kind="square", amp=0.10, release=0.03),
        _tone(440, 0.10, kind="square", amp=0.10, release=0.06),
    )

    # undo — descending blip
    sounds["undo"] = _concat(
        _tone(660, 0.05, amp=0.10, release=0.03),
        _tone(440, 0.07, amp=0.08, release=0.05),
    )

    # redo — ascending blip
    sounds["redo"] = _concat(
        _tone(440, 0.05, amp=0.08, release=0.03),
        _tone(660, 0.07, amp=0.10, release=0.05),
    )

    # export done — fanfare
    sounds["export"] = _concat(
        _tone(523.25, 0.10, amp=0.18, release=0.04),   # C5
        _tone(659.25, 0.10, amp=0.20, release=0.04),   # E5
        _tone(783.99, 0.20, amp=0.22, release=0.15),   # G5
    )

    # error — buzz
    sounds["error"] = _mix(
        _tone(120, 0.15, kind="saw", amp=0.20, release=0.10),
        _tone(90, 0.15, kind="saw", amp=0.15, release=0.10)
    )

    # tab switch — tick
    sounds["tab"] = _tone(1000, 0.03, kind="square", amp=0.06, release=0.02)

    return sounds


# ---------------------------------------------------------------- cache + playback
from PyQt5.QtCore import QObject as _QObject


class SoundEngine(_QObject):
    def __init__(self):
        super().__init__()
        self._persistent_timers = {}   # name -> QTimer, kept alive
        self.enabled = True
        self._paths: dict[str, Path] = {}
        self._effects: dict[str, QSoundEffect] = {}
        self._cli_player, self._cli_args = _find_cli_player()
        self._procs = []   # keep refs so play() calls aren't reaped instantly
        self._master_volume = 0.6
        self._loop_effects: dict[str, QSoundEffect] = {}
        self._cli_loop_active: dict[str, dict] = {}   # name -> {volume, timer}
        self._load()

    def _load(self):
        if not _HAVE_NUMPY:
            print("[sounds] numpy missing — sounds disabled")
            return
        sounds = _build_sounds()
        for name, samples in sounds.items():
            path = CACHE_DIR / f"{name}.wav"
            if not path.is_file():
                try:
                    _write_wav(path, samples)
                except Exception as e:
                    print(f"[sounds] failed to write {name}: {e}")
                    continue
            self._paths[name] = path

        if not _HAVE_MULTIMEDIA:
            if self._cli_player:
                print(f"[sounds] QtMultimedia missing — using CLI player '{self._cli_player}' "
                      f"(pseudo-loop via QTimer)")
            else:
                print('[sounds] no audio backend available — playback disabled')
            return  # _paths is already populated; loop uses CLI path
        for name, path in self._paths.items():
            eff = QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(str(path)))
            eff.setVolume(0.55 * self._master_volume)
            self._effects[name] = eff

        # loop sounds
        for loop_name in ('brush_loop',):
            p = self._paths.get(loop_name)
            if p is None:
                continue
            eff = QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(str(p)))
            eff.setLoopCount(QSoundEffect.Infinite)
            eff.setVolume(0.0)
            self._loop_effects[loop_name] = eff

    def play(self, name: str):
        if not self.enabled:
            return

        # 1) QtMultimedia path
        eff = self._effects.get(name)
        if eff is not None:
            try:
                eff.play()
                return
            except Exception:
                pass

        # 2) CLI fallback
        path = self._paths.get(name)
        if path is None or not self._cli_player:
            return
        try:
            cmd = [self._cli_player, *self._cli_args, str(path)]
            proc = subprocess.Popen(cmd,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            self._procs = [p for p in self._procs if p.poll() is None]
            self._procs.append(proc)
            if len(self._procs) > 8:
                self._procs.pop(0)
        except Exception:
            pass

    def set_enabled(self, value: bool):
        self.enabled = value

    def set_master_volume(self, value: float):
        self._master_volume = max(0.0, min(1.0, value))
        for eff in self._effects.values():
            try:
                eff.setVolume(0.55 * self._master_volume)
            except Exception:
                pass

    def start_loop(self, name: str, volume: float = 0.5):
        if not self.enabled:
            return

        # ---- Qt path ----
        eff = self._loop_effects.get(name)
        if eff is not None:
            try:
                eff.setVolume(max(0.0, min(1.0, volume)) * self._master_volume)
                if eff.status() != QSoundEffect.Loading:
                    eff.play()
                return
            except Exception:
                pass

        # ---- CLI pseudo-loop via QTimer ----
        if name in self._cli_loop_active:
            self.set_loop_volume(name, volume)
            return
        if not self._cli_player:
            return
        path = self._paths.get(name)
        if path is None:
            return

        # Require a running QApplication — otherwise QTimer is inert.
        try:
            from PyQt5.QtWidgets import QApplication
            if QApplication.instance() is None:
                # no event loop → just play the one-shot sound, no loop
                path0 = self._paths.get(name)
                if path0 is not None and self._cli_player:
                    try:
                        subprocess.Popen(
                            [self._cli_player, *self._cli_args, str(path0)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                return
        except Exception:
            pass

        from PyQt5.QtCore import QTimer
        state = {"volume": max(0.0, min(1.0, volume))}

        def _fire():
            vol = state["volume"] * self._master_volume
            if vol <= 0.001:
                return
            try:
                cmd = list(self._cli_args)
                if self._cli_player == "paplay":
                    cmd = [f"--volume={int(vol * 65536)}"] + cmd
                elif self._cli_player == "pw-play":
                    cmd = [f"--volume={vol:.3f}"] + cmd
                proc = subprocess.Popen(
                    [self._cli_player, *cmd, str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._procs.append(proc)
                if len(self._procs) > 8:
                    self._procs.pop(0)
            except Exception as e:
                print(f"[sounds] paplay failed: {e}")

        # parent to `self` so the timer survives GC
        timer = QTimer(self)
        timer.setInterval(900)
        timer.timeout.connect(_fire)

        # store BOTH references — belt and suspenders
        state["timer"] = timer
        self._persistent_timers[name] = timer
        self._cli_loop_active[name] = state
        timer.start()
        _fire()

    def set_loop_volume(self, name: str, volume: float):
        volume = max(0.0, min(1.0, volume))
        eff = self._loop_effects.get(name)
        if eff is not None:
            try:
                eff.setVolume(volume * self._master_volume)
                return
            except Exception:
                pass
        state = self._cli_loop_active.get(name)
        if state is not None:
            state["volume"] = volume

    def stop_loop(self, name: str):
        eff = self._loop_effects.get(name)
        if eff is not None:
            try:
                eff.stop()
            except Exception:
                pass
        state = self._cli_loop_active.pop(name, None)
        if state is not None:
            t = state.get("timer")
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
            state.pop("timer", None)
        self._persistent_timers.pop(name, None)


# ---------------------------------------------------------------- singleton
_engine: SoundEngine | None = None


def get_engine() -> SoundEngine:
    global _engine
    if _engine is None:
        _engine = SoundEngine()
    return _engine


def play(name: str) -> None:
    get_engine().play(name)


def set_master_volume(v: float) -> None:
    get_engine().set_master_volume(v)


def start_loop(name: str, volume: float = 0.5) -> None:
    get_engine().start_loop(name, volume)


def set_loop_volume(name: str, volume: float) -> None:
    get_engine().set_loop_volume(name, volume)


def stop_loop(name: str) -> None:
    get_engine().stop_loop(name)


def debug_list() -> None:
    """Print what the engine knows + what's cached on disk."""
    eng = get_engine()
    print("[sounds] cache dir:", CACHE_DIR)
    for name, path in eng._paths.items():
        exists = "✓" if path.is_file() else "✗"
        size = path.stat().st_size if path.is_file() else 0
        loop = " (loop)" if name in eng._loop_effects else ""
        print(f"  {exists} {name:12s} {size:>7d} bytes{loop}")
