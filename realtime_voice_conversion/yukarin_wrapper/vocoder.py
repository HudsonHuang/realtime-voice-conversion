import numpy
import pyworld
from world4py.native import structures, apidefinitions, utils
from yukarin.acoustic_feature import AcousticFeature
from yukarin.param import AcousticParam
from yukarin.wave import Wave


class Vocoder(object):
    def __init__(
            self,
            acoustic_param: AcousticParam,
            out_sampling_rate: int,
    ):
        self.acoustic_param = acoustic_param
        self.out_sampling_rate = out_sampling_rate

    def encode(self, wave: Wave):
        return AcousticFeature.extract(
            wave,
            frame_period=self.acoustic_param.frame_period,
            f0_floor=self.acoustic_param.f0_floor,
            f0_ceil=self.acoustic_param.f0_ceil,
            fft_length=self.acoustic_param.fft_length,
            order=self.acoustic_param.order,
            alpha=self.acoustic_param.alpha,
            dtype=self.acoustic_param.dtype,
        )

    def decode(
            self,
            acoustic_feature: AcousticFeature,
    ):
        acoustic_feature = acoustic_feature.astype_only_float(numpy.float64)
        out = pyworld.synthesize(
            f0=acoustic_feature.f0.ravel(),
            spectrogram=acoustic_feature.spectrogram,
            aperiodicity=acoustic_feature.aperiodicity,
            fs=self.out_sampling_rate,
            frame_period=self.acoustic_param.frame_period,
        )
        return Wave(out, sampling_rate=self.out_sampling_rate)


class RealtimeVocoder(Vocoder):
    def __init__(
            self,
            acoustic_param: AcousticParam,
            out_sampling_rate: int,
            buffer_size: int,
            number_of_pointers: int,
    ):
        super().__init__(
            acoustic_param=acoustic_param,
            out_sampling_rate=out_sampling_rate,
        )

        self.buffer_size = buffer_size

        self._synthesizer = structures.WorldSynthesizer()
        apidefinitions._InitializeSynthesizer(
            self.out_sampling_rate,  # sampling rate
            self.acoustic_param.frame_period,  # frame period
            pyworld.get_cheaptrick_fft_size(out_sampling_rate),  # fft size
            buffer_size,  # buffer size
            number_of_pointers,  # number of pointers
            self._synthesizer,
        )
        self._before_buffer = []  # for holding memory

    def decode(
            self,
            acoustic_feature: AcousticFeature,
    ):
        length = len(acoustic_feature.f0)
        f0_buffer = utils.cast_1d_list_to_1d_pointer(acoustic_feature.f0.flatten().tolist())
        sp_buffer = utils.cast_2d_list_to_2d_pointer(acoustic_feature.sp.tolist())
        ap_buffer = utils.cast_2d_list_to_2d_pointer(acoustic_feature.ap.tolist())
        apidefinitions._AddParameters(f0_buffer, length, sp_buffer, ap_buffer, self._synthesizer)

        ys = []
        while apidefinitions._Synthesis2(self._synthesizer) != 0:
            y = numpy.array([self._synthesizer.buffer[i] for i in range(self.buffer_size)])
            ys.append(y)

        if len(ys) > 0:
            out_wave = Wave(
                wave=numpy.concatenate(ys),
                sampling_rate=self.out_sampling_rate,
            )
        else:
            out_wave = Wave(
                wave=numpy.empty(0),
                sampling_rate=self.out_sampling_rate,
            )

        self._before_buffer.append((f0_buffer, sp_buffer, ap_buffer))  # for holding memory
        if len(self._before_buffer) > 16:
            self._before_buffer.pop(0)
        return out_wave

    def warm_up(self, time_length: float):
        y = numpy.zeros(int(time_length * self.out_sampling_rate))
        w = Wave(wave=y, sampling_rate=self.out_sampling_rate)
        f = self.encode(w)
        self.decode(f)
