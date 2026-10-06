"""
G903 feature 探测脚本 —— 确认设备支持哪些 HID++ feature（只读，无副作用）。

探测目标：
  0x2201 AdjustableDpi           改 DPI（经典）
  0x2202 ExtendedDpi             改 DPI（进阶，X/Y 独立 + LOD）
  0x8060 ReportRate              轮询率（经典，单位 ms）
  0x8061 ExtendedReportRate      轮询率（进阶，单位 Hz，游戏鼠标用）
  0x1001 Battery Voltage         电量电压（已有，做对照）
  0x1004 Battery Level Status    电量百分比（看是否也支持，供参考）
"""
import sys

import hid

from g903_app import g903_control as ctl

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FEATURES = [
    ("0x2201", 0x2201, "AdjustableDpi (改 DPI 经典)"),
    ("0x2202", 0x2202, "ExtendedDpi (进阶 X/Y DPI + LOD)"),
    ("0x8060", 0x8060, "ReportRate (轮询率 ms)"),
    ("0x8061", 0x8061, "ExtendedReportRate (轮询率 Hz)"),
    ("0x1001", 0x1001, "Battery Voltage (对照)"),
    ("0x1004", 0x1004, "Battery Level Status (百分比)"),
    ("0x0000", 0x0000, "Root"),
]


def query_feature_index(dev, feature_id):
    """返回 feature 索引（0 = 不支持），附带原始响应。"""
    fid_hi = (feature_id >> 8) & 0xFF
    fid_lo = feature_id & 0xFF
    try:
        resp = ctl.call(dev, 0x00, 0x00, [fid_hi, fid_lo, 0x00])
    except RuntimeError:
        return None, None
    return resp[4], resp


def main():
    paths = ctl.find_hidpp_paths()
    if not paths:
        print("未找到 G903 长报文 HID++ 接口")
        sys.exit(1)

    for path, pid in paths:
        print(f"接口路径: {path.decode('utf-8', 'replace')} (PID 0x{pid:04x})")
        dev = None
        try:
            dev = hid.device()
            dev.open_path(path)
            for hex_id, fid, name in FEATURES:
                idx, resp = query_feature_index(dev, fid)
                if idx is None:
                    print(f"  {hex_id}  {name:<36} -> 无响应")
                elif idx == 0:
                    print(f"  {hex_id}  {name:<36} -> 不支持 (idx=0)")
                else:
                    print(f"  {hex_id}  {name:<36} -> 支持, feature index = 0x{idx:02x} ({idx})")
        finally:
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
