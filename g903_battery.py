"""
G903 LIGHTSPEED 电量查询脚本 v8（排除充电读数 + 有线/无线自适应）
设备约束（已实际探测确认）：
- 该 G903 固件只支持 Battery Voltage (feature 0x1001)，
  不支持 Battery Level Status (0x1004) 等百分比上报接口，
  因此电量 % 只能按锂电放电曲线估算。

v8 改动（相对 v7）：
- 趋势结论仅统计"未充电"的静置读数，排除充电/通道切换抬高的电压，
  使结论更准确反映真实耗电。
- 保留 v7 的有线/无线自适应 + 静默 CSV 记录。
"""

import csv
import os
import sys
import time
from datetime import datetime

from g903_app import g903_control as ctl

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HISTORY_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "g903_battery_history.csv")
SAMPLES = 3
MIN_REAL_DELTA = 15

# 标准单节锂电放电曲线（与 Solaar estimate_battery_level_percentage /
# OpenLogi voltage_battery_percentage 完全一致，严格单调 13 点）。
DISCHARGE_CURVE = [
    (4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60),
    (3811, 50), (3778, 40), (3751, 30), (3717, 20), (3671, 10),
    (3646, 5), (3579, 2), (3500, 0),
]

# 电池状态常量（来自 HID++ 0x1001 Battery Voltage 的 status 字节）。
BATTERY_DISCHARGING = "discharging"   # 放电 / 不充电（电平被动使用）
BATTERY_CHARGING = "charging"         # 正常充电
BATTERY_CHARGING_FAST = "charging_fast"  # 快充
BATTERY_CHARGING_SLOW = "charging_slow"  # 慢充（涓流）
BATTERY_FULL = "full"                 # 充满
BATTERY_NOT_CHARGING = "not_charging" # 插电但未在充电（如已充满/温度保护）
BATTERY_FAULT = "fault"               # 充电故障

# 状态 → 中文标签（GUI/CLI 展示用）。
BATTERY_STATUS_LABEL = {
    BATTERY_DISCHARGING: "放电（未充电）",
    BATTERY_CHARGING: "充电中",
    BATTERY_CHARGING_FAST: "快充中",
    BATTERY_CHARGING_SLOW: "慢充中",
    BATTERY_FULL: "已充满",
    BATTERY_NOT_CHARGING: "插电未充电",
    BATTERY_FAULT: "充电故障",
}


def decode_battery_status(status_byte):
    """按 HID++ 0x1001 status 字节解析充电状态（与 OpenLogi VoltageChargingStatus::from_flags 完全一致）。

    位定义：
      bit7          0 = 正在放电，1 = 已接外部电源
      bit1..0       0b01 或 0b11 = 已充满；0b10 = 未在充电（故障）；0b00 = 充电中
      bit3          1 = 快速充电
      bit4          1 = 慢速充电
    """
    if not (status_byte & 0x80):
        return BATTERY_DISCHARGING
    low2 = status_byte & 0x03
    if low2 == 0b01 or low2 == 0b11:
        return BATTERY_FULL
    if low2 == 0b10:
        return BATTERY_NOT_CHARGING  # 外部供电但未充电（故障/保护）
    # low2 == 0b00：充电中，看速度位。
    if status_byte & (1 << 3):
        return BATTERY_CHARGING_FAST
    if status_byte & (1 << 4):
        return BATTERY_CHARGING_SLOW
    return BATTERY_CHARGING


def parse_battery_response(resp):
    if len(resp) <= 6:
        raise RuntimeError("电量响应过短，无法解析电压与充电状态")
    voltage_mv = int.from_bytes(bytes(resp[4:6]), "big")
    status_byte = resp[6]
    return voltage_mv, decode_battery_status(status_byte)


def estimate_percent(voltage_mv):
    if voltage_mv >= DISCHARGE_CURVE[0][0]:
        return DISCHARGE_CURVE[0][1]
    if voltage_mv <= DISCHARGE_CURVE[-1][0]:
        return DISCHARGE_CURVE[-1][1]
    for (v_hi, p_hi), (v_lo, p_lo) in zip(DISCHARGE_CURVE, DISCHARGE_CURVE[1:]):
        if v_lo <= voltage_mv <= v_hi:
            frac = (voltage_mv - v_hi) / (v_lo - v_hi)
            return round(p_hi + frac * (p_lo - p_hi))


def measure(dev, batt_idx, samples=SAMPLES):
    values = []
    status = BATTERY_DISCHARGING
    last_resp = None
    for _ in range(samples):
        resp = ctl.call(dev, batt_idx, 0x00, [0x00, 0x00, 0x00])
        v, status = parse_battery_response(resp)
        values.append(v)
        last_resp = resp
    values.sort()
    return values, values[samples // 2], status, last_resp


def append_history(v1, v2, v3, median, status, percent):
    new_file = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time", "v1", "v2", "v3", "voltage", "status", "charging", "percent"])
        charging = 1 if status != BATTERY_DISCHARGING else 0
        row = [time.strftime("%Y-%m-%d %H:%M:%S"),
               v1, v2, v3, median, status]
        row.append(charging)
        row.append("" if percent is None else percent)
        w.writerow(row)


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


def read_once():
    """读取一次电量，返回 (info, summary, error)。"""
    dev, pid = ctl.open_device()
    if dev is None:
        return None, None, "未找到可用的长报文 HID++ 接口"
    try:
        channel = "有线" if pid == 0xC086 else ("无线" if pid == 0xC539 else f"PID 0x{pid:04x}")
        batt_idx = ctl.get_index(dev, ctl.FEATURE_BATTERY_VOLTAGE)
        values, median, status, last_resp = measure(dev, batt_idx)
        charging = status != BATTERY_DISCHARGING
        ipct = estimate_percent(median) if status == BATTERY_DISCHARGING else None
        append_history(values[0], values[1], values[2], median, status, ipct)
        return {
            "channel": channel, "pid": pid, "values": values,
            "voltage": median, "charging": charging, "status": status,
            "percent": ipct,
            "raw": [hex(b) for b in last_resp],
        }, summarize_history(), None
    except (RuntimeError, OSError, ValueError) as e:
        return None, None, f"出错: {e}"
    except Exception as e:
        return None, None, f"未知错误: {e}"
    finally:
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass


def main():
    info, summary, err = read_once()
    if err:
        print(err)
        sys.exit(1)

    print(f"接口通道: {info['channel']} (PID 0x{info['pid']:04x})")
    print(f"原始响应字节: {info['raw']}")
    print(f"\n电压: {info['voltage']} mV (本次 {SAMPLES} 次采样: {info['values']})")
    print(f"充电状态: {BATTERY_STATUS_LABEL.get(info['status'], info['status'])}")
    if info["percent"] is None:
        print("估算电量: —（充电时电压不稳定，不估算百分比）")
    else:
        print(f"估算电量: 约 {info['percent']}%")
    if summary:
        print(f"\n{summary}")


if __name__ == "__main__":
    main()
