"""Wire audio format and deterministic speech segmentation, independent of models."""

from collections import deque

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_MS = FRAME_SAMPLES / SAMPLE_RATE * 1000
LANGUAGES = {"en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu"}


class VoiceError(Exception):
    """Safe message that can be shown to a client without exposing model internals."""


class Segmenter:
    """Three-frame onset, 256ms pre-roll, 640ms silence, maximum 30s utterances."""

    def __init__(self):
        self.pre_roll = deque(maxlen=8)
        self.frames = []
        self.onset = 0
        self.silence = 0
        self.voiced = 0
        self.active = False

    def feed(self, frame, probability):
        if len(frame) != FRAME_BYTES:
            raise VoiceError("Send 512-sample mono PCM16 frames at 16000 Hz.")
        speech = probability >= 0.6
        started = False
        if not self.active:
            self.pre_roll.append(frame)
            self.onset = self.onset + 1 if speech else 0
            if self.onset < 3:
                return False, None
            self.active = started = True
            self.frames = list(self.pre_roll)
            self.voiced = self.onset
            self.pre_roll.clear()
        else:
            self.frames.append(frame)
            self.voiced += int(speech)
        self.silence = 0 if speech else self.silence + 1
        if self.silence >= 20 or len(self.frames) >= int(30 * SAMPLE_RATE / FRAME_SAMPLES):
            return started, self.flush()
        return started, None

    def flush(self):
        audio = b"".join(self.frames) if self.voiced >= 8 else None
        self.__init__()
        return audio
