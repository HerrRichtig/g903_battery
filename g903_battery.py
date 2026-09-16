"""
G903 LIGHTSPEED 电量查询脚本 v8（排除充电读数 + 有线/无线自适应）
设备约束（已实际探测确认）：
- 该 G903 固件只支持 Battery Voltage (feature 0x1001)，
  不支持 Battery Level Status (0x1004) 等百分比上报接口，
  因此电量 % 只能按锂电放电曲线估算。

v8 改动（相对 v7）：
- 趋势结论仅统计"未充电"的静置读数，排除充电/通道切换抬高的电��，
  使结论更准确反映真实耗电。
- 保留 v7 的有线/无线自适应 + 静默 CSV 记录。
"""

import csv
import io
import os
import sys
import time
from datetime import datetime

import hid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

VID = 0x046D
PID_PRIORITY = {0xC086: 0, 0xC539: 1}

REPORT_ID_LONG = 0x11
DEVICE_IDX = 0x01
FEATURE_ROOT = 0x0000
FEATURE_BATTERY_VOLTAGE = 0x1001
SW_ID = 0x0A

REPORT_LEN = 20
FRAME_ERROR = 0x8F

HISTORY_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "g903_battery_history.csv")
SAMPLES = 3
MIN_REAL_DELTA = 15

DISCHARGE_CURVE = [
    (4200, 100), (4100, 94), (4000, 88), (3950, 82), (3900, 76),
    (3850, 68), (3800, 60), (3770, 52), (3750, 47), (3720, 42),
    (3690, 36), (3660, 30), (3600, 22), (3500, 12), (3400, 5),
    (3300, 0),
]


def find_hidpp_long_paths():
    candidates = []
    for info in hid.enumerate(VID):
        if info.get("usage_page") == 0xFF00 and info.get("usage") == 0x0002:
            pid = info.get("product_id")
            priority = PID_PRIORITY.get(pid, 2)
            candidates.append((priority, info["path"], pid))
    candidates.sort(key=lambda x: x[0])
    return [(path, pid) for _, path, pid in candidates]


def probe_feature(path, feature_id):
    dev = None
    try:
        dev = hid.device()
        dev.open_path(path)

        def send_and_wait(report, timeout_ms=800):
            dev.write(report)
            resp = dev.read(REPORT_LEN, timeout_ms=timeout_ms)
            if resp and len(resp) >= 1 and resp[0] == REPORT_ID_LONG and resp[1] == report[1]:
                return resp
            return None

        fid_hi = (feature_id >> 8) & 0xFF
        fid_lo = feature_id & 0xFF
        resp = send_and_wait(build_request(DEVICE_IDX, 0x00, 0x00, [fid_hi, fid_lo, 0x00]))
        return bool(resp and len(resp) > 4 and resp[4] != 0)
    except Exception:
        return False
    finally:
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass


def find_active_hidpp_path():
    for path, pid in find_hidpp_long_paths():
        if probe_feature(path, FEATURE_BATTERY_VOLTAGE):
            return path, pid
    return None, None


def build_request(device_idx, feature_idx, function_id, params):
    if len(params) > 16:
        raise ValueError(f"params 长度超过 16 字节: {len(params)}")
    func_sw = ((function_id & 0x0F) << 4) | (SW_ID & 0x0F)
    payload = list(params) + [0x00] * (16 - len(params))
    return [REPORT_ID_LONG, device_idx, feature_idx, func_sw] + payload


def send_and_wait(dev, report, timeout_ms=800):
    dev.write(report)
    resp = dev.read(REPORT_LEN, timeout_ms=timeout_ms)
    if resp and len(resp) >= 1 and resp[0] == REPORT_ID_LONG and resp[1] == report[1]:
        return resp
    return None


def check_error(resp):
    if len(resp) > 2 and resp[2] == FRAME_ERROR:
        err_code = resp[5] if len(resp) > 5 else resp[-1]
        raise RuntimeError(f"设备返回错误，错误码 0x{err_code:02x}")


def get_feature_index(dev, feature_id):
    fid_hi = (feature_id >> 8) & 0xFF
    fid_lo = feature_id & 0xFF
    report = build_request(DEVICE_IDX, 0x00, 0x00, [fid_hi, fid_lo, 0x00])
    resp = send_and_wait(dev, report)
    if not resp:
        raise RuntimeError(f"查询 feature 0x{feature_id:04x} 无响应")
    check_error(resp)
    if len(resp) <= 4:
        raise RuntimeError(f"查询 feature 0x{feature_id:04x} 响应过短")
    feature_idx = resp[4]
    if feature_idx == 0:
        raise RuntimeError(f"设备不支持 feature 0x{feature_id:04x}")
    return feature_idx


def parse_battery_response(resp):
    if len(resp) <= 6:
        raise RuntimeError("电量响应过短，无法解析电压与充电状态")
    voltage_mv = int.from_bytes(bytes(resp[4:6]), "big")
    status_byte = resp[6]
    return voltage_mv, bool(status_byte & 0x80)


def get_battery(dev, battery_feature_idx):
    report = build_request(DEVICE_IDX, battery_feature_idx, 0x00, [0x00, 0x00, 0x00])
    resp = send_and_wait(dev, report)
    if not resp:
        raise RuntimeError("查询电量无响应")
    check_error(resp)
    return resp


def estimate_percent(voltage_mv):
    if voltage_mv >= DISCHARGE_CURVE[0][0]:
        return DISCHARGE_CURVE[0][1]
    if voltage_mv <= DISCHARGE_CURVE[-1][0]:
        return DISCHARGE_CURVE[-1][1]
    for (v_hi, p_hi), (v_lo, p_lo) in zip(DISCHARGE_CURVE, DISCHARGE_CURVE[1:]):
        if v_lo <= voltage_mv <= v_hi:
            frac = (voltage_mv - v_hi) / (v_lo - v_hi)
            return round(p_hi + frac * (p_lo - p_hi))
    return None


def measure(dev, batt_idx, samples=SAMPLES):
    values = []
    charging = False
    last_resp = None
    for _ in range(samples):
        resp = get_battery(dev, batt_idx)
        v, charging = parse_battery_response(resp)
        values.append(v)
        last_resp = resp
    values.sort()
    return values, values[samples // 2], charging, last_resp


def append_history(v1, v2, v3, median, charging, percent):
    new_file = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time", "v1", "v2", "v3", "voltage", "charging", "percent"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"),
                    v1, v2, v3, median, int(charging), percent])


def summarize_history():
    """读取历史记录，仅统计未充电的静置读数，生成趋势结论。"""
    if not os.path.exists(HISTORY_CSV):
        return None
    rows = []
    charging_excluded = 0
    with open(HISTORY_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
                v = int(r["voltage"])
                charging = int(r.get("charging", 0))
                if charging:
                    charging_excluded += 1
                    continue
                rows.append((t, v))
            except (KeyError, ValueError):
                continue
    n = len(rows)
    if n < 2:
        return f"静置记录仅 {n} 条（另 {charging_excluded} 条充电读数已排除），暂无法判断耗电趋势。"

    vols = [v for _, v in rows]
    lo, hi = min(vols), max(vols)
    span_h = (rows[-1][0] - rows[0][0]).total_seconds() / 3600

    if n < 4:
        return (f"静置 {n} 条 / 跨度 {span_h:.1f} 小时，电压 {lo}~{hi} mV"
                f"（波动 ±{(hi - lo) // 2} mV，已排除 {charging_excluded} 条充电读数），样本还太少。")

    k = 3
    first_avg = sum(v for _, v in rows[:k]) / k
    last_avg = sum(v for _, v in rows[-k:]) / k
    delta = round(last_avg - first_avg)

    if delta <= -MIN_REAL_DELTA:
        return f"结论：静置电压较初期下降约 {-delta} mV，可观察到真实耗电（静置 {n} 条 / 跨度 {span_h / 24:.1f} 天，已排除 {charging_excluded} 条充电读数）。"
    if delta >= MIN_REAL_DELTA:
        return f"结论：静置读数较初期升高 {delta} mV，但仍在噪声范围内（静置极差 {hi - lo} mV），不代表充电。"
    return f"结论：静置电压整体平稳（前后差 {abs(delta)} mV，噪声极差 {hi - lo} mV），暂未观察到明显耗电变化（静置 {n} 条 / 跨度 {span_h / 24:.1f} 天，已排除 {charging_excluded} 条充电读数）。"


def main():
    path, pid = find_active_hidpp_path()
    if not path:
        print("未找到��用的长报文 HID++ 接口")
        sys.exit(1)

    dev = None
    try:
        dev = hid.device()
        dev.open_path(path)
        channel = "有线" if pid == 0xC086 else ("无线" if pid == 0xC539 else f"PID 0x{pid:04x}")

        batt_idx = get_feature_index(dev, FEATURE_BATTERY_VOLTAGE)
        values, median, charging, last_resp = measure(dev, batt_idx)
        percent = estimate_percent(median)

        print(f"接口通道: {channel} (PID 0x{pid:04x})")
        print(f"原始响应字节: {[hex(b) for b in last_resp]}")
        print(f"\n电压: {median} mV (本次 {SAMPLES} 次采样: {values})")
        print(f"充电状态: {'充电中' if charging else '未充电'}")
        print(f"估算电量: 约 {percent}%")

        append_history(values[0], values[1], values[2], median, charging, percent)
        summary = summarize_history()
        if summary:
            print(f"\n{summary}")

    except (RuntimeError, OSError, ValueError) as e:
        print(f"出错: {e}")
    except Exception as e:
        print(f"未知错误: {e}")
    finally:
        if dev is not None:
            dev.close()


if __name__ == "__main__":
    main()
