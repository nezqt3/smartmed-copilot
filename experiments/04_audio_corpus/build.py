"""Build six synthetic Mandarin dialogue WAVs with macOS voices and ffmpeg."""

import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLE_RATE = 16_000
PAUSE_FRAMES = int(0.8 * SAMPLE_RATE)
VOICES = {"doctor": "Eddy (Chinese (China mainland))", "patient": "Tingting"}


def main():
    if platform.system() != "Darwin" or not shutil.which("say") or not shutil.which("ffmpeg"):
        raise SystemExit("Generation requires macOS say and ffmpeg; committed WAVs are portable.")
    scripts = json.loads((ROOT / "scripts.json").read_text(encoding="utf-8"))
    clips = ROOT / "clips"
    clips.mkdir(exist_ok=True)
    manifest = []
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        for case in scripts:
            target = clips / f"{case['id']}.wav"
            with wave.open(str(target), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(SAMPLE_RATE)
                for index, turn in enumerate(case["turns"]):
                    aiff = temp / f"{case['id']}_{index}.aiff"
                    wav = temp / f"{case['id']}_{index}.wav"
                    subprocess.run(
                        ["say", "-v", VOICES[turn["speaker"]], "-r", "120",
                         "-o", str(aiff), turn["text"]],
                        check=True,
                    )
                    subprocess.run(
                        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff),
                         "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
                         str(wav)],
                        check=True,
                    )
                    with wave.open(str(wav), "rb") as segment:
                        if segment.getnchannels() != 1 or segment.getsampwidth() != 2:
                            raise ValueError("Unexpected segment format")
                        output.writeframes(segment.readframes(segment.getnframes()))
                    if index < len(case["turns"]) - 1:
                        output.writeframes(b"\0\0" * PAUSE_FRAMES)
                    aiff.unlink()
                    wav.unlink()
            with wave.open(str(target), "rb") as clip:
                duration = round(clip.getnframes() / clip.getframerate(), 3)
            manifest.append({
                **case,
                "source_type": "synthetic_macos_tts_not_clinically_reviewed",
                "audio_path": f"clips/{target.name}",
                "duration_s": duration,
                "sample_rate": SAMPLE_RATE,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "voices": VOICES,
                "generator": "macOS say + ffmpeg PCM16",
                "macos_version": platform.mac_ver()[0],
                "transcript_status": "source_script_not_independent_manual_transcription",
            })
            print(f"{case['id']}: {duration}s")
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
