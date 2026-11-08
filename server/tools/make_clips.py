#!/usr/bin/env python3
"""Generate the announcement clips in server/voice_clips.csv with Piper.

Writes sounds/field/<clip>.wav for the field speaker: 16-bit mono, silence
trimmed from both ends, every clip normalized to the same peak level, plus a
short lead-in so a PA that wakes on signal doesn't swallow the first word.

    python server/tools/make_clips.py --voice ~/.local/share/piper-voices/en_US-ryan-high.onnx
                                      [--out server/sounds/field] [--only clip1,clip2]

Needs: pip install piper-tts (in the airsoft conda env on the dev laptop).
Then copy the folder to the server:
    scp -r server/sounds/field airsoft@airsoft-pi.local:~/airsoft-dashboard/sounds/
"""
import argparse
import csv
import io
import os
import wave

import numpy as np
from piper import PiperVoice, SynthesisConfig

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--voice", required=True, help="Piper .onnx voice model")
ap.add_argument("--csv", default=os.path.join(HERE, "..", "voice_clips.csv"))
ap.add_argument("--out", default=os.path.join(HERE, "..", "sounds", "field"))
ap.add_argument("--only", default="", help="comma-separated clip names (default: all)")
ap.add_argument("--speed", type=float, default=1.0, help="<1 slower, >1 faster")
args = ap.parse_args()

LEAD_IN_S = 0.15        # silence before the first word
TAIL_S = 0.10           # silence after the last word
PEAK = 0.89             # about -1 dBFS: loud and consistent, no clipping
SILENCE = 0.02          # samples quieter than this (of full scale) count as silence

voice = PiperVoice.load(os.path.expanduser(args.voice))
cfg = SynthesisConfig(length_scale=1.0 / args.speed)
only = {c.strip() for c in args.only.split(",") if c.strip()}
os.makedirs(args.out, exist_ok=True)

with open(args.csv, newline="") as f:
    rows = list(csv.DictReader(f))
for row in rows:
    clip, text = row["clip"], row["text"]
    if only and clip not in only:
        continue
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(text, w, syn_config=cfg)
    buf.seek(0)
    with wave.open(buf, "rb") as w:
        rate = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    loud = np.nonzero(np.abs(audio) > SILENCE)[0]
    if len(loud):
        audio = audio[loud[0]:loud[-1] + 1]
    if np.abs(audio).max() > 0:
        audio = audio * (PEAK / np.abs(audio).max())
    audio = np.concatenate([np.zeros(int(LEAD_IN_S * rate)), audio, np.zeros(int(TAIL_S * rate))])
    path = os.path.join(args.out, f"{clip}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    print(f"{clip:28s} {len(audio) / rate:4.1f} s  {text}")
