"""Build the Mend commercial: AI voice-over (Piper, offline), scenes timed to the voice, motion graphics, final MP4.

  python media/commercial/make_commercial.py              # voice + video  -> media/commercial/out/mend-commercial.mp4
  python media/commercial/make_commercial.py --no-voice   # silent preview with default scene lengths
  options: --voice en_US-ryan-high  --no-captions  --stills

Needs: pip install piper-tts; Node with Playwright; ffmpeg. The first run downloads the voice from huggingface.co.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
VOICES = HERE / ".voices"
LEAD, TAIL = 0.35, 0.65   # silence before each line, and breathing room after it


def run(cmd: list[str], **kw) -> None:
    print("$", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "", flush=True)
    subprocess.run(cmd, check=True, **kw)


def synthesize(voice: str, scenes: list[dict], length_scale: float) -> list[Path]:
    VOICES.mkdir(exist_ok=True)
    model = VOICES / f"{voice}.onnx"
    if not model.exists():
        run([sys.executable, "-m", "piper.download_voices", voice, "--download-dir", str(VOICES)])
    files = []
    for i, s in enumerate(scenes):
        f = OUT / f"line-{i}-{s['id']}.wav"
        run([sys.executable, "-m", "piper", "-m", str(model), "-f", str(f), "--length-scale", str(length_scale)],
            input=s["line"].encode())
        files.append(f)
    return files


def wav_seconds(f: Path) -> float:
    with wave.open(str(f)) as w:
        return w.getnframes() / w.getframerate()


def mix(lines: list[Path], timings: list[dict], out: Path) -> None:
    """One mono track: each line placed at its scene start + LEAD, silence elsewhere."""
    with wave.open(str(lines[0])) as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
    total = int(timings[-1]["end"] * rate) * width * ch
    buf = bytearray(total)
    for f, t in zip(lines, timings):
        with wave.open(str(f)) as w:
            data = w.readframes(w.getnframes())
        at = int((t["start"] + LEAD) * rate) * width * ch
        buf[at:at + len(data)] = data[: max(0, total - at)]
    raw = out.with_suffix(".raw.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(width); w.setframerate(rate); w.writeframes(bytes(buf))
    # broadcast-style loudness, a touch of warmth, 48 kHz stereo for video
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af",
         "highpass=f=70,equalizer=f=180:t=q:w=1:g=2,acompressor=threshold=-18dB:ratio=3,loudnorm=I=-16:TP=-1.5:LRA=7",
         "-ar", "48000", "-ac", "2", str(out)])
    raw.unlink()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--voice")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--stills", action="store_true")
    a = ap.parse_args()

    spec = json.loads((HERE / "script.json").read_text())
    scenes = spec["scenes"]
    OUT.mkdir(exist_ok=True)
    lines = [] if a.no_voice else synthesize(a.voice or spec["voice"], scenes, spec.get("length_scale", 1.0))

    timings, t = [], 0.0
    for i, s in enumerate(scenes):
        need = LEAD + wav_seconds(lines[i]) + TAIL if lines else 0
        d = round(max(s["min"], need), 2)
        timings.append({"id": s["id"], "start": round(t, 2), "end": round(t + d, 2), "line": s["line"]})
        t += d
    (OUT / "timings.json").write_text(json.dumps(timings, indent=1))
    print("scenes:", ", ".join(f"{x['id']} {x['end'] - x['start']:.1f}s" for x in timings), f"| total {t:.1f}s")

    audio = None
    if lines:
        audio = OUT / "voice.wav"
        mix(lines, timings, audio)

    video = OUT / ("mend-commercial.mp4" if lines else "mend-commercial-preview.mp4")
    npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "NODE_PATH": os.pathsep.join(filter(None, [os.environ.get("NODE_PATH"), npm_root]))}
    cmd = ["node", str(HERE / "render.js"), str(OUT / "timings.json"), str(video)] + ([str(audio)] if audio else [])
    cmd += (["--no-captions"] if a.no_captions else []) + (["--stills"] if a.stills else [])
    run(cmd, env=env)
    print("done:", video)


if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required")
    main()
