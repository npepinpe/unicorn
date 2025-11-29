import os
import struct
from machine import I2S, Pin

class WavPlayer:
    # Internal states
    PLAY = 0
    FLUSH = 1
    STOP = 2
    NONE = 3

    # Pins
    ID = 0
    SD_PIN = 9
    SCK_PIN = 10
    WS_PIN = 11
    AMP = 22

    # Default buffer length
    SILENCE_BUFFER_LENGTH = 1000
    WAV_BUFFER_LENGTH = 10000
    INTERNAL_BUFFER_LENGTH = 20000

    def __init__(self):
        self.__enable = Pin(self.AMP, Pin.OUT)
        self.__state = WavPlayer.NONE
        self.__wav_file = None
        self.__first_sample_offset = None
        self.__flush_count = 0
        self.__audio_out = None
        self.__silence_samples = bytearray(self.SILENCE_BUFFER_LENGTH)
        self.__wav_samples_mv = memoryview(bytearray(self.WAV_BUFFER_LENGTH))

    def play(self, wav_file):
        if os.listdir("/").count(wav_file) == 0:
            raise ValueError(f"'{wav_file}' not found")

        self.__stop_i2s()
        self.__wav_file = open("/" + wav_file, "rb")

        format, sample_rate, bits_per_sample, self.__first_sample_offset, self.sample_size = WavPlayer.__parse_wav(self.__wav_file)
        
        self.total_bytes_read = 0
        self.__wav_file.seek(self.__first_sample_offset)
        self.__start_i2s(bits=bits_per_sample,
                         format=format,
                         rate=sample_rate,
                         state=WavPlayer.PLAY)

    def stop(self):
        if self.__state == WavPlayer.PLAY:
            self.__state = WavPlayer.FLUSH
            self.__wav_file.close()

    def is_playing(self):
        return self.__state != WavPlayer.NONE and self.__state != WavPlayer.STOP

    def is_paused(self):
        return self.__state == WavPlayer.PAUSE

    def __start_i2s(self, bits=16, format=I2S.MONO, rate=44_100, state=STOP):
        import gc
        gc.collect()
        self.__audio_out = I2S(
            self.ID,
            sck=self.SCK_PIN,
            ws=self.WS_PIN,
            sd=self.SD_PIN,
            mode=I2S.TX,
            bits=bits,
            format=format,
            rate=rate,
            ibuf=self.INTERNAL_BUFFER_LENGTH,
        )

        self.__state = state
        self.__flush_count = self.INTERNAL_BUFFER_LENGTH // self.SILENCE_BUFFER_LENGTH + 1
        self.__audio_out.irq(self.__i2s_callback)
        self.__audio_out.write(self.__silence_samples)
        self.__enable.on()

    def __stop_i2s(self):
        self.stop()
        while self.is_playing():
            pass
        self.__enable.off()
        if self.__audio_out is not None:
            self.__audio_out.deinit()
        self.__state == WavPlayer.NONE

    def __i2s_callback(self, arg):
        if self.__state == WavPlayer.PLAY:
            num_read = self.__wav_file.readinto(self.__wav_samples_mv)
            self.total_bytes_read += num_read
            if num_read == 0:
                self.__wav_file.close()
                self.__state = WavPlayer.FLUSH
                self.__audio_out.write(self.__silence_samples)
            else:
                if num_read > 0 and num_read < self.WAV_BUFFER_LENGTH:
                    num_read = num_read - (self.total_bytes_read - self.sample_size)
                self.__audio_out.write(self.__wav_samples_mv[: num_read])
        elif self.__state == WavPlayer.STOP:
            self.__audio_out.write(self.__silence_samples)
        elif self.__state == WavPlayer.FLUSH:
            if self.__flush_count > 0:
                self.__flush_count -= 1
            else:
                self.__state = WavPlayer.STOP
            self.__audio_out.write(self.__silence_samples)
        elif self.__state == WavPlayer.NONE:
            pass

    @staticmethod
    def __parse_wav(wav_file):
        chunk_ID = wav_file.read(4)
        if chunk_ID != b"RIFF":
            raise ValueError("WAV chunk ID invalid")
        _ = wav_file.read(4)
        format = wav_file.read(4)
        if format != b"WAVE":
            raise ValueError("WAV format invalid")
        sub_chunk1_ID = wav_file.read(4)
        if sub_chunk1_ID != b"fmt ":
            raise ValueError("WAV sub chunk 1 ID invalid")
        _ = wav_file.read(4)
        _ = struct.unpack("<H", wav_file.read(2))[0]
        num_channels = struct.unpack("<H", wav_file.read(2))[0]

        if num_channels == 1:
            format = I2S.MONO
        else:
            format = I2S.STEREO

        sample_rate = struct.unpack("<I", wav_file.read(4))[0]
        _ = struct.unpack("<I", wav_file.read(4))[0]
        _ = struct.unpack("<H", wav_file.read(2))[0]
        bits_per_sample = struct.unpack("<H", wav_file.read(2))[0]

        binary_block = wav_file.read(200)
        offset = binary_block.find(b"data")
        if offset == -1:
            raise ValueError("WAV sub chunk 2 ID not found")

        wav_file.seek(40)
        sub_chunk2_size = struct.unpack("<I", wav_file.read(4))[0]

        return (format, sample_rate, bits_per_sample, 44 + offset, sub_chunk2_size)
