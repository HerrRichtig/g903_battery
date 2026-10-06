"""Run with: python -m tests.test_control (no hardware access)."""
from g903_app import g903_control as ctl


class Device:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.writes = []

    def write(self, report):
        self.writes.append(report)

    def read(self, *_args, **_kwargs):
        return next(self.responses, [])


def main():
    request = ctl.build_request(1, 4, 2, [1])
    assert request[:5] == [0x11, 1, 4, 0x2A, 1]
    assert [ms for bit, ms in ctl.MS_BITMASK.items() if 0x8B & bit] == [1, 2, 4, 8]

    response = [0x11, 1, 0x0D, 0x2A, 1, 0, 0]
    dev = Device([response])
    assert ctl.call(dev, 0x0D, 2, [1, 0, 0]) == response

    dev = Device([[0x11, 1, 0xFF, 0x0D, 2, 2]])
    try:
        ctl.call(dev, 0x0D, 2, [1, 0, 0])
    except ctl.HidppError as error:
        assert error.code == 2
    else:
        raise AssertionError("HID++ error frame was not raised")

    # get_dpi_list: 普通值（高 3 位为 0）
    plain = [0x11, 1, 0x0A, 0x1A, 0x04, 0x03, 0xE8, 0x06, 0x40, 0x0C, 0x80, 0x19, 0x00]
    assert ctl.get_dpi_list(Device([plain]), 0x0A) == [1000, 1600, 3200, 6400]

    # get_dpi_list: range 编码（高 3 位 0b111，step + last 展开）
    rng = [0x11, 1, 0x0A, 0x1A, 0x04, 0x03, 0xE8, 0xE0, 0x64, 0x05, 0x14, 0x00]
    assert ctl.get_dpi_list(Device([rng]), 0x0A) == [1000, 1100, 1200, 1300]

    # set_dpi 写后读回一致则通过
    ok = Device([[0x11, 1, 0x0A, 0x3A, 0, 0, 0],
                [0x11, 1, 0x0A, 0x2A, 0, 0x06, 0x40]])
    ctl.set_dpi(ok, 0x0A, 1600)

    # set_dpi 读回不一致则报错
    bad = Device([[0x11, 1, 0x0A, 0x3A, 0, 0, 0],
                  [0x11, 1, 0x0A, 0x2A, 0, 0x03, 0xE8]])
    try:
        ctl.set_dpi(bad, 0x0A, 1600)
    except RuntimeError:
        pass
    else:
        raise AssertionError("set_dpi read-back mismatch was not raised")

    print("control checks passed")


if __name__ == "__main__":
    main()
