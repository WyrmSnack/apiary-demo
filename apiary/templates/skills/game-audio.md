---
name: game-audio
description: Make game sound effects and simple music loops with SoX (synthesis and effects) and convert, trim and normalise audio with FFmpeg, then check rate, length and loudness with the audio gate. Use when a task needs sounds, music or audio conversion for a game.
---

# Game audio with SoX and FFmpeg

Both run only through `run_connector` (`connector: sox` or `connector: ffmpeg`). Work in WAV, check it, then encode
to Ogg Vorbis for the game (Godot plays `.ogg` and `.wav`).

**Create the output folder first** (for example `mkdir -p game/sfx/src`): neither program makes folders. Measured
with SoX 14.4.2: a missing folder fails with `FAIL formats: can't open output file`, which the run record shows as
`NOT OK`.

## Sound effects from nothing (SoX)

`-n` means "no input"; `synth <seconds> <wave> <start>-<end Hz>` sweeps; effects follow.

| Sound | `args` |
|---|---|
| Jump | `-n -r 44100 -c 1 -b 16 sfx/jump.wav synth 0.25 square 300-900 fade 0 0.25 0.12 vol 0.5` |
| Coin | `-n -r 44100 -c 1 -b 16 sfx/coin.wav synth 0.08 square 988 : synth 0.3 square 1319 fade 0 0.3 0.25 vol 0.4` |
| Hit | `-n -r 44100 -c 1 -b 16 sfx/hit.wav synth 0.15 brownnoise fade 0 0.15 0.14 lowpass 1500 vol 0.8` |
| Laser | `-n -r 44100 -c 1 -b 16 sfx/laser.wav synth 0.3 sawtooth 1500-200 fade 0 0.3 0.2 vol 0.4` |
| Explosion | `-n -r 44100 -c 1 -b 16 sfx/boom.wav synth 1.2 brownnoise fade 0 1.2 1.1 lowpass 600 reverb 40 vol 0.9` |

**Always `-b 16` before the output file.** Measured with SoX 14.4.2: without it a synthesised WAV is 32-bit
`WAVE_FORMAT_EXTENSIBLE`, which Godot 4.7.2 refuses to import ("Format not supported for WAVE file (not PCM)").
The audio gate fails such a file.

Waves: `sine`, `square`, `triangle`, `sawtooth`, `whitenoise`, `pinknoise`, `brownnoise`. A short note sequence
(`synth 0.2 square 523 : synth 0.2 square 659 : ...`) makes a jingle; `repeat <n>` loops it. Keep effects under
about one second and leave headroom (`vol` 0.4 to 0.8): clipping sounds bad.

## Convert and tidy (FFmpeg)

Always `-nostdin -y -loglevel error`.

- WAV to Ogg Vorbis: `-nostdin -y -loglevel error -i sfx/jump.wav -c:a libvorbis -q:a 5 sfx/jump.ogg`
- Normalise loudness: `... -i in.wav -af loudnorm=I=-16:TP=-1.5 out.wav`
- Trim silence at the start: `... -i in.wav -af silenceremove=start_periods=1:start_threshold=-50dB out.wav`
- Resample to mono 44.1 kHz: `... -i in.wav -ac 1 -ar 44100 out.wav`

## The gate

    python -m apiary.gates.assets audio sfx/jump.wav --rate 44100 --channels 1 --min-seconds 0.1 --max-seconds 1 --not-silent
    python -m apiary.gates.assets audio sfx/jump.ogg --rate 44100 --max-seconds 1

`--not-silent` reads WAV samples (a typo in an effect chain can give silence with exit 0); for Ogg it checks the
headers and length only, so check the WAV before encoding.

Licensing: sounds you synthesise are the colony's own. Never pull samples from the web without a licence that allows
it, and record the source and licence in the task's notes.
