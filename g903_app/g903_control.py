"""
G903 HID++ 扩展模块 —— 新增 DPI 与轮询率读写（在电量基础上扩展）。

已实测 G903 无线(LIGHTSPEED)探测确认的 feature：
  0x2201 AdjustableDpi -> index 0x0a : 改 DPI（经典）
  0x8060 ReportRate     -> index 0x0d : 改轮询率（单位毫秒间隔）
  0x1001 Battery Voltage-> index 0x04 : 电量电压（原有）
不支持：0x2202/0x8061/0x1004

协议参考 AprilNEA/OpenLogi：
  crates/openlogi-hidpp/src/feature/adjustable_dpi.rs
  crates/openlogi-hidpp/src/feature/report_rate.rs
  crates/openlogi-hidpp/src/protocol/v20.rs (ErrorType)
"""
import sys
from contextlib import contextmanager

import hid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VID = 0x046D
PID_G903 = 0xC539
PID_G903_WIRED = 0xC086
REPORT_ID_LONG = 0x11
DEVICE_IDX = 0x01
SW_ID = 0x0A
REPORT_LEN = 20
TIMEOUT_MS = 800
PROBE_TIMEOUT_MS = 300   # 探测死路径用的短超时，单次探测避免对休眠接口空等
FRAME_ERROR = 0x8F

FEATURE_BATTERY_VOLTAGE = 0x1001
FEATURE_ADJUSTABLE_DPI = 0x2201
FEATURE_REPORT_RATE = 0x8060
FEATURE_ONBOARD_PROFILES = 0x8100

HIDPP20_ERRORS = {
    0: "NoError",
    1: "Unknown",
    2: "InvalidArgument（参数非法 / 值不受支持）",
    3: "OutOfRange（参数越界）",
    4: "HwError",
    5: "LogitechInternal",
    6: "InvalidFeatureIndex",
    7: "InvalidFunctionId",
    8: "Busy（设备忙）",
    9: "Unsupported（不支持该操作）",
}

MS_TO_HZ = {1: 1000, 2: 500, 4: 250, 8: 125}
MS_BITMASK = {0x01: 1, 0x02: 2, 0x08: 4, 0x80: 8}


class HidppError(RuntimeError):
    def __init__(self, code, function_id):
        self.code = code
        self.name = HIDPP20_ERRORS.get(code, f"0x{code:02x}")
        super().__init__(f"function {function_id} 返回错误: {self.name}")


def build_request(device_idx, feature_idx, function_id, params):
    if len(params) > 16:
        raise ValueError(f"params 长度超过 16: {len(params)}")
    func_sw = ((function_id & 0x0F) << 4) | (SW_ID & 0x0F)
    payload = list(params) + [0x00] * (16 - len(params))
    return [REPORT_ID_LONG, device_idx, feature_idx, func_sw] + payload


def _check_error(resp, function_id):
    if not resp or len(resp) < 6:
        return
    if resp[1] == DEVICE_IDX and (resp[2] == 0xFF or resp[2] == FRAME_ERROR):
        code = resp[5]
        raise HidppError(code, function_id)


def _read_matching(dev, feature_idx, function_id):
    expected_sw = ((function_id & 0x0F) << 4) | (SW_ID & 0x0F)
    for _ in range(10):
        resp = dev.read(REPORT_LEN, timeout_ms=TIMEOUT_MS)
        if not resp or len(resp) <= 4:
            continue
        if resp[1] != DEVICE_IDX:
            continue
        if resp[2] == 0xFF or resp[2] == FRAME_ERROR:
            return resp
        if resp[2] == feature_idx and resp[3] == expected_sw:
            return resp
    return None


def call(dev, feature_idx, function_id, params):
    report = build_request(DEVICE_IDX, feature_idx, function_id, params)
    dev.write(report)
    resp = _read_matching(dev, feature_idx, function_id)
    if not resp or len(resp) <= 4:
        raise RuntimeError(f"function {function_id} 无响应")
    _check_error(resp, function_id)
    return resp


def find_hidpp_paths():
    out = []
    order = {PID_G903: 0, PID_G903_WIRED: 1}
    for info in hid.enumerate(VID):
        if info.get("usage_page") == 0xFF00 and info.get("usage") == 0x0002:
            pid = info.get("product_id")
            out.append((order.get(pid, 2), info["path"], pid))
    out.sort(key=lambda x: x[0])
    return [(p, pid) for _, p, pid in out]


def _probe_open_path(path, pid):
    # 在「同一句柄」上发送 0x1001 getFeature 并短超时读一次，判断该路径是否真正
    # 应答。返回 (dev, pid) 或 (None, None)。单开句柄可避免双开句柄造成的响应错位。
    dev = None
    try:
        dev = hid.device()
        dev.open_path(path)
        fid_hi = (FEATURE_BATTERY_VOLTAGE >> 8) & 0xFF
        fid_lo = FEATURE_BATTERY_VOLTAGE & 0xFF
        dev.write(build_request(DEVICE_IDX, 0x00, 0x00, [fid_hi, fid_lo, 0x00]))
        resp = dev.read(REPORT_LEN, timeout_ms=PROBE_TIMEOUT_MS)
        if resp and len(resp) > 4 and resp[4] != 0:
            return dev, pid
        dev.close()
        dev = None
    except Exception:
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
    return None, None


_LAST_GOOD_PATH = None   # 缓存上次真正应答的路径，避免每次对休眠死路径空等


def open_device():
    global _LAST_GOOD_PATH
    paths = find_hidpp_paths()
    # 先试缓存的上次活路径（瞬时命中），失败再回退全量探测。
    if _LAST_GOOD_PATH is not None:
        cached_path, cached_pid = _LAST_GOOD_PATH
        dev, pid = _probe_open_path(cached_path, cached_pid)
        if dev is not None:
            return dev, pid
    for path, pid in paths:
        dev, pid = _probe_open_path(path, pid)
        if dev is not None:
            _LAST_GOOD_PATH = (path, pid)
            return dev, pid
    return None, None


@contextmanager
def open_device_cm():
    dev, pid = open_device()
    if dev is None:
        yield None, None
        return
    try:
        yield dev, pid
    finally:
        try:
            dev.close()
        except Exception:
            pass


def get_index(dev, feature_id):
    fid_hi = (feature_id >> 8) & 0xFF
    fid_lo = feature_id & 0xFF
    resp = call(dev, 0x00, 0x00, [fid_hi, fid_lo, 0x00])
    idx = resp[4]
    if idx == 0:
        raise RuntimeError(f"设备不支持 feature 0x{feature_id:04x}")
    return idx


# ---------- 0x2201 AdjustableDpi ----------

def get_dpi_list(dev, dpi_idx, sensor_index=0):
    resp = call(dev, dpi_idx, 1, [sensor_index, 0, 0])
    payload = resp[4:]
    values = []
    i = 1
    n = len(payload)
    while i + 1 < n:
        v = int.from_bytes(bytes(payload[i:i + 2]), "big")
        if v == 0:
            break
        if (v >> 13) == 0b111:
            step = v & 0x1FFF
            if step == 0 or i + 3 >= n:
                raise RuntimeError("DPI 列表 range 编码异常")
            start = values[-1] if values else None
            if start is None:
                raise RuntimeError("DPI range 缺少起始值")
            last = int.from_bytes(bytes(payload[i + 2:i + 4]), "big")
            if last < start:
                raise RuntimeError("DPI range 降序异常")
            nxt = start + step
            while nxt < last:
                values.append(nxt)
                nxt += step
            values.append(last)
            i += 4
        else:
            values.append(v)
            i += 2
    if not values:
        raise RuntimeError("DPI 列表为空")
    return sorted(set(values))


def get_current_dpi(dev, dpi_idx, sensor_index=0):
    resp = call(dev, dpi_idx, 2, [sensor_index, 0, 0])
    return int.from_bytes(bytes(resp[5:7]), "big")


def set_dpi(dev, dpi_idx, dpi, sensor_index=0):
    dpi_hi = (dpi >> 8) & 0xFF
    dpi_lo = dpi & 0xFF
    call(dev, dpi_idx, 3, [sensor_index, dpi_hi, dpi_lo])
    actual = get_current_dpi(dev, dpi_idx, sensor_index)
    if actual != dpi:
        raise RuntimeError(f"DPI 写入 {dpi} 后读回 {actual}，未生效")


# ---------- 0x8060 ReportRate ----------

def get_report_rate_list(dev, rr_idx):
    resp = call(dev, rr_idx, 0, [0, 0, 0])
    mask = resp[4]
    rates = [ms for bit, ms in MS_BITMASK.items() if mask & bit]
    if not rates:
        raise RuntimeError("轮询率列表为空")
    return rates


def get_report_rate(dev, rr_idx):
    resp = call(dev, rr_idx, 1, [0, 0, 0])
    return resp[4]


def set_report_rate(dev, rr_idx, rate_ms):
    if rate_ms not in MS_TO_HZ:
        raise ValueError(f"不支持的轮询率间隔 {rate_ms}ms（可选 1/2/4/8）")
    call(dev, rr_idx, 2, [rate_ms, 0, 0])
    actual = get_report_rate(dev, rr_idx)
    if actual != rate_ms:
        raise RuntimeError(f"轮询率写入 {rate_ms}ms 后读回 {actual}ms，未生效")


ONBOARD_MODE = 0x01
HOST_MODE = 0x02


def set_report_rate_with_host_mode(dev, rr_idx, rate_ms):
    try:
        set_report_rate(dev, rr_idx, rate_ms)
    except HidppError as e:
        if e.code != 2:
            raise
        onboard_idx = get_index(dev, FEATURE_ONBOARD_PROFILES)
        if get_onboard_mode(dev, onboard_idx) != ONBOARD_MODE:
            raise
        set_onboard_mode(dev, onboard_idx, HOST_MODE)
        set_report_rate(dev, rr_idx, rate_ms)


def get_onboard_mode(dev, onboard_idx):
    return call(dev, onboard_idx, 2, [0, 0, 0])[4]


def set_onboard_mode(dev, onboard_idx, mode):
    call(dev, onboard_idx, 1, [mode, 0, 0])


def snapshot(dev, dpi_idx, rr_idx):
    dpi_list = get_dpi_list(dev, dpi_idx)
    cur_dpi = get_current_dpi(dev, dpi_idx)
    rr_list = get_report_rate_list(dev, rr_idx)
    cur_ms = get_report_rate(dev, rr_idx)
    return {
        "dpi_list": dpi_list,
        "current_dpi": cur_dpi,
        "report_rate_ms": cur_ms,
        "report_rate_hz": MS_TO_HZ.get(cur_ms),
        "report_rate_list_ms": rr_list,
    }


if __name__ == "__main__":
    dev, pid = open_device()
    if dev is None:
        print("未找到 G903 长报文 HID++ 接口")
        sys.exit(1)
    try:
        dpi_idx = get_index(dev, FEATURE_ADJUSTABLE_DPI)
        rr_idx = get_index(dev, FEATURE_REPORT_RATE)
        s = snapshot(dev, dpi_idx, rr_idx)
        hz = [MS_TO_HZ[m] for m in s["report_rate_list_ms"]] if s["report_rate_list_ms"] else []
        print(f"PID 0x{pid:04x}")
        print(f"支持 DPI: {s['dpi_list']}")
        print(f"当前 DPI: {s['current_dpi']}")
        print(f"支持轮询率: {s['report_rate_list_ms']}ms -> {hz} Hz")
        print(f"当前轮询率: {s['report_rate_ms']}ms = {s['report_rate_hz']}Hz")
    finally:
        try:
            dev.close()
        except Exception:
            pass
