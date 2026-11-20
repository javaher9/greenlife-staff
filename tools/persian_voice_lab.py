"""Offline GreenLife voice preview. Run --help for available modes.

Use a local Piper ONNX model with its adjacent .onnx.json file. Audio input
also requires a local faster-whisper model, NumPy, and FFmpeg. Live desktop
simulation uses a PulseAudio input and ffplay with headphones to isolate
playback from the microphone. All results are printed as JSON previews.
"""

import argparse
import json
import re
import subprocess
import tempfile
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OPENING = "سلام، وقتتون بخیر. من دستیار صوتی گِرین‌لایف هستم. برای معرفی یه پیشنهاد همکاری با جواهرفروشی‌تون تماس گرفتم. الان فرصت دارین؟"
REPEAT = "صدا واضح نبود. ممکنه یه بار دیگه بفرمایین؟"
PARTNERSHIP = "تماس برای بررسی امکان همکاری گرین‌لایف با جواهرفروشی شماست. اگه مایل باشین، همکارم می‌تونه دربارهٔ جزئیات باهاتون صحبت کنه."
TEHRAN = ZoneInfo("Asia/Tehran")
DAYS = ("دوشنبه", "سه شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")
HOURS = "یک دو سه چهار پنج شش هفت هشت نه ده یازده دوازده".split()


def normalize(value):
    value = value.translate(str.maketrans("يك‌۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "یک 01234567890123456789"))
    value = re.sub(r"[\u064b-\u065f]", "", value)
    return " ".join(re.sub(r"[^\w\s:]", " ", value).split())


class Dialogue:
    def __init__(self, now=None):
        self.now = now or (lambda: datetime.now(TEHRAN))
        self.day = None
        self.period = None
        self.pending = None
        self.follow_up = None
        self.scheduling = False
        self.outcome = ""
        self.notes = ""
        self.done = False

    def preview(self):
        return {
            "outcome": self.outcome,
            "followup_at": self.follow_up.isoformat() if self.follow_up else None,
            "followup_consent": "yes" if self.follow_up else (
                "no" if self.outcome == "do_not_contact" else "unknown"
            ),
            "do_not_contact": self.outcome == "do_not_contact",
            "notes": self.notes,
        }

    def respond(self, transcript):
        if self.done:
            raise RuntimeError("Call has ended.")
        value = normalize(transcript)
        if re.search(r"تماس نگیر|زنگ نزن|دیگ[هه] تماس ن|دیگه زنگ ن", value):
            self.outcome, self.notes, self.done = "do_not_contact", "", True
            self.pending = self.follow_up = None
            return "حتماً، درخواستتون برای تماس نگرفتن ثبت می‌شه. روزتون بخیر."
        if not value:
            return REPEAT
        if re.search(r"چه همکاری|چه پیشنهاد|موضوع چیه|چه جوری همکاری", value):
            self.outcome = "answered"
            return PARTNERSHIP
        if re.search(r"یه نفر|یک نفر|آدم واقعی|اپراتور|وصل کن|با.*(همکار|کارشناس)", value):
            self.outcome, self.notes = "answered", "مخاطب درخواست گفت‌وگو با کارشناس انسانی را مطرح کرد."
            self.pending = self.follow_up = None
            self.done = True
            return "حتماً. درخواست صحبت با همکارم رو یادداشت می‌کنم. روزتون بخیر."
        if self.pending and re.fullmatch(r"(بله|آره|باشه|درسته|تایید می کنم|همین خوبه)( (ممنون|مرسی|درسته))?", value):
            self.follow_up, self.pending = self.pending, None
            self.outcome, self.done = "follow_up", True
            return "ممنون، زمان تماس رو یادداشت کردم. روزتون بخیر."
        now = self.now()
        day = re.search(r"\b(?:پس فردا|فردا|امروز|" + "|".join(DAYS) + r")\b", value)
        if day:
            self.period = None
            name = day[0]
            offset = {"امروز": 0, "فردا": 1, "پس فردا": 2}.get(name)
            if offset is None:
                offset = (DAYS.index(name) - now.weekday()) % 7 or 7
            self.day = now.date() + timedelta(days=offset)
        if day or re.search(r"زنگ بزن|تماس بگیر|بعدا|وقت ندارم|پیگیری", value):
            self.scheduling = True
        if not self.scheduling:
            return REPEAT
        period = re.search(r"صبح|بعد از ظهر|بعدازظهر|عصر|شب|ظهر", value)
        if period:
            self.period = period[0]
        hour = re.search(r"(?:\bساعت |^)([0-9]{1,2})(?::([0-9]{2}))?(?![\w:])", value)
        spoken = re.search(r"(?:^|ساعت )(" + "|".join(HOURS) + r")( و نیم)?\b", value)
        if not (hour or spoken):
            if self.pending and re.match(r"نه\b", value):
                self.pending = None
            elif self.pending and not day:
                return "لطفاً بفرمایین زمان پیشنهادی رو تأیید می‌کنین یا ساعت دیگه‌ای مناسب‌تره؟"
            self.pending = None
            return ("چه روز و چه ساعتی براتون مناسبه؟" if self.day is None
                    else "برای همون روز چه ساعت دقیقی براتون مناسبه؟")
        if not self.day:
            return "چه روزی برای تماس مناسبه؟ لطفاً روز و ساعت رو با هم بفرمایین."
        h, m = ((int(hour[1]), int(hour[2] or 0)) if hour else
                (HOURS.index(spoken[1]) + 1, 30 if spoken[2] else 0))
        self.pending = None
        if 1 <= h < 12 and self.period in {"عصر", "بعد از ظهر", "بعدازظهر", "شب"}:
            h += 12
        elif 1 <= h <= 12 and not self.period:
            return "منظورتون صبحه یا بعدازظهر؟ لطفاً ساعت رو کامل بفرمایین."
        if h > 23 or m > 59:
            return "لطفاً ساعت دقیق تماس رو دوباره بفرمایین."
        candidate = datetime(self.day.year, self.day.month, self.day.day, h, m, tzinfo=TEHRAN)
        if candidate <= now:
            return "این زمان گذشته. چه روز و ساعت دیگه‌ای براتون مناسبه؟"
        self.pending = candidate
        offset = (candidate.date() - now.date()).days
        day_name = {0: "امروز", 1: "فردا", 2: "پس‌فردا"}.get(offset, DAYS[candidate.weekday()])
        clock = HOURS[(h % 12) - 1] if h % 12 else "دوازده"
        minute = "" if m == 0 else (" و نیم" if m == 30 else f" و {m} دقیقه")
        period = "بامداد" if h == 0 else "صبح" if h < 12 else "ظهر" if h == 12 else "بعدازظهر" if h < 19 else "شب"
        return f"پس {day_name}، ساعت {clock}{minute} {period} تماس بگیریم. درسته؟"


class Voice:
    def __init__(self, path, pace=1.03):
        from piper import PiperVoice, SynthesisConfig

        self.voice = PiperVoice.load(str(path))
        self.config = SynthesisConfig(length_scale=pace, noise_scale=0.55)

    def render(self, text, path):
        with wave.open(str(path), "wb") as output:
            self.voice.synthesize_wav(text, output, syn_config=self.config)


class Recognizer:
    def __init__(self, path):
        from faster_whisper import WhisperModel

        if not path.is_dir():
            raise ValueError("Pass the directory of an installed faster-whisper model.")
        self.model = WhisperModel(str(path), device="cpu", compute_type="int8",
                                  cpu_threads=4, local_files_only=True)

    def transcribe(self, samples):
        segments, _ = self.model.transcribe(
            samples, language="fa", beam_size=3, condition_on_previous_text=False,
            log_prob_threshold=-1.0, no_speech_threshold=0.6,
        )
        return " ".join(x.text.strip() for x in segments if x.avg_logprob >= -1.0)


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class VoiceGate:
    """Energy gate for isolated input, using 20 ms PCM frames at 16 kHz."""

    def __init__(self, threshold):
        self.threshold = threshold
        self.frames = []
        self.onset = self.silence = 0

    def feed(self, frame, interrupt):
        import numpy as np

        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
        active = np.sqrt(np.mean(samples ** 2)) >= self.threshold
        if self.onset < 3:
            self.onset = self.onset + 1 if active else 0
            if not active:
                self.frames.clear()
                return None
            self.frames.append(frame)
            if self.onset == 3:
                interrupt()
            return None
        self.frames.append(frame)
        self.silence = 0 if active else self.silence + 1
        if self.silence >= 25 or len(self.frames) >= 500:
            result = b"".join(self.frames)
            self.frames.clear()
            self.onset = self.silence = 0
            return result
        return None


def microphone(voice, recognizer, dialogue, source, threshold):
    import numpy as np

    gate = VoiceGate(threshold)
    capture = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "pulse", "-fragment_size",
         "640", "-i", source, "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE,
    )
    player = None
    with tempfile.TemporaryDirectory() as directory:
        audio = Path(directory) / "reply.wav"

        def speak(message):
            voice.render(message, audio)
            return subprocess.Popen(["ffplay", "-loglevel", "error", "-nodisp",
                                     "-autoexit", str(audio)], stdin=subprocess.DEVNULL)

        try:
            player = speak(OPENING)
            while frame := capture.stdout.read(640):
                if len(frame) != 640:
                    break
                clip = gate.feed(frame, lambda: stop(player))
                if clip is None:
                    continue
                start = time.perf_counter()
                transcript = recognizer.transcribe(np.frombuffer(clip, dtype="<i2").astype(np.float32) / 32768)
                response = dialogue.respond(transcript)
                player = speak(response)
                print(json.dumps({"transcript": transcript, "response": response,
                                  "seconds_after_endpoint": round(time.perf_counter() - start, 3),
                                  "plaque_preview": dialogue.preview()}, ensure_ascii=False), flush=True)
                if dialogue.done:
                    player.wait()
                    return
            raise RuntimeError("Microphone stream closed.")
        finally:
            stop(player)
            stop(capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", type=Path, required=True)
    parser.add_argument("--whisper", type=Path)
    parser.add_argument("--pace", type=float, default=1.03, help="Piper duration multiplier")
    parser.add_argument("--output", type=Path, help="Render the last reply (or opening) to WAV")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", action="append", help="Repeat for multiple scripted turns")
    source.add_argument("--audio", type=Path, action="append", help="Repeat for multiple prerecorded turns")
    source.add_argument("--mic", nargs="?", const="default", help="PulseAudio input source. Use headphones.")
    parser.add_argument("--vad-threshold", type=int, default=400, help="RMS threshold on 16-bit PCM")
    args = parser.parse_args()
    if (args.audio or args.mic) and not (args.whisper and args.whisper.is_dir()):
        parser.error("--audio and --mic require a local --whisper model directory")
    if not (args.mic or args.output or args.text or args.audio):
        parser.error("select --output, --text, --audio or --mic")
    if not 0.6 <= args.pace <= 1.6 or not 0 < args.vad_threshold <= 32767:
        parser.error("pace or VAD threshold out of range")
    dialogue = Dialogue()
    voice = Voice(args.voice, args.pace) if args.output or args.mic else None
    recognizer = Recognizer(args.whisper) if args.audio or args.mic else None
    if args.mic:
        microphone(voice, recognizer, dialogue, args.mic, args.vad_threshold)
        return
    response = OPENING
    for turn in args.audio or args.text or []:
        start = time.perf_counter()
        if args.audio:
            import numpy as np

            pcm = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(turn),
                                           "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"])
            turn = recognizer.transcribe(np.frombuffer(pcm, dtype="<f4"))
        response = dialogue.respond(turn)
        print(json.dumps({"transcript": turn, "response": response,
                          "recognition_and_dialogue_seconds": round(time.perf_counter() - start, 4),
                          "plaque_preview": dialogue.preview()}, ensure_ascii=False))
        if dialogue.done:
            break
    if args.output:
        voice.render(response, args.output)


if __name__ == "__main__":
    main()
