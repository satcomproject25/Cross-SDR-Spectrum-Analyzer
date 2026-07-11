import numpy as np

from .models import IQBuffer
from .models import IQFrame


class IQReader:

    def load(self, filename, sample_rate, center_frequency):

        raw = np.fromfile(filename, dtype=np.int8)

        i = raw[0::2].astype(np.float32)

        q = raw[1::2].astype(np.float32)

        samples = i + 1j * q

        return IQBuffer(
            samples=samples,
            sample_rate=sample_rate,
            center_frequency=center_frequency
        )

    def frames(self, buffer, frame_size=4096):

        total = len(buffer.samples)

        frame = 0

        for start in range(0, total - frame_size + 1, frame_size):

            yield IQFrame(

                samples=buffer.samples[start:start+frame_size],

                frame_number=frame,

                sample_rate=buffer.sample_rate,

                center_frequency=buffer.center_frequency

            )

            frame += 1
