# Mend commercial

A 30-second promo with an AI voice-over, motion graphics timed to the voice, and captions.

```bash
pip install piper-tts                                   # offline neural text-to-speech
python media/commercial/make_commercial.py              # -> media/commercial/out/mend-commercial.mp4
python media/commercial/make_commercial.py --no-voice   # silent preview, default scene lengths
```

- `script.json`: the voice-over, one line per scene, the voice (`en_US-ryan-high`) and its speed.
- `make_commercial.py`: synthesizes each line with Piper, sets each scene's length to fit its line,
  mixes the voice track (loudness-normalized), and calls the renderer.
- `render.js`: the motion graphics (Playwright frames piped to ffmpeg, 1920x1080, 30 fps).

Needs Node with Playwright, ffmpeg, and network access to `huggingface.co` the first time (Piper downloads
the voice there into `.voices/`). Every number on screen comes from the recorded runs in `runs/`.
