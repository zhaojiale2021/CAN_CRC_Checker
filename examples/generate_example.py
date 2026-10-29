"""Generate the synthetic example project shipped under ``examples/example``.

Everything here is fabricated: message names, signal names, DataIDs and the
trace. It exists so the tool (and its test suite) has a runnable project with
known-good CRC/RC values without shipping any real customer data.

Run from the repository root:

    python examples/generate_example.py

It writes ``dbc/network.dbc``, ``dbc/dataid.json``, ``trace/example.blf``
(all checks pass), ``trace/example_bad.blf`` (deliberate CRC/RC errors) and
``config.json`` / ``config_bad.json`` next to this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import can

from crc_checker.crc.engine import CRCEngine
from crc_checker.crc.models import CRCRange
from crc_checker.crc.presets import get_preset
from crc_checker.trace.models import CanFrame

HERE = Path(__file__).resolve().parent / "example"

DBC_TEXT = '''VERSION ""

NS_ :
    NS_DESC_
    CM_
    BA_DEF_
    BA_
    VAL_
    CAT_DEF_
    CAT_
    FILTER
    BA_DEF_DEF_
    EV_DATA_
    ENVVAR_DATA_
    SGTYPE_
    SGTYPE_VAL_
    BA_DEF_SGTYPE_
    BA_SGTYPE_
    SIG_TYPE_REF_
    VAL_TABLE_
    SIG_GROUP_
    SIG_VALTYPE_
    SIGTYPE_VALTYPE_
    BO_TX_BU_
    BA_DEF_REL_
    BA_REL_
    BA_DEF_DEF_REL_
    BU_SG_REL_
    BU_EV_REL_
    BU_BO_REL_
    SG_MUL_VAL_

BS_:

BU_: ECU_A ECU_B

BO_ 256 MsgAlpha: 8 ECU_A
 SG_ Checksum_Alpha : 7|8@0+ (1,0) [0|255] "" ECU_B
 SG_ RollingCounter_Alpha : 15|4@0+ (1,0) [0|15] "" ECU_B
 SG_ AlphaPayload : 23|8@0+ (1,0) [0|255] "" ECU_B

BO_ 512 MsgBeta: 64 ECU_A
 SG_ Beta_CRC : 7|16@0+ (1,0) [0|65535] "" ECU_B
 SG_ Beta_Counter : 23|8@0+ (1,0) [0|255] "" ECU_B
 SG_ BetaPayload : 31|8@0+ (1,0) [0|255] "" ECU_B

BO_ 768 MsgGamma: 8 ECU_A
 SG_ Gamma_Checksum : 63|8@0+ (1,0) [0|255] "" ECU_B
 SG_ Gamma_MsgCntr : 15|4@0+ (1,0) [0|15] "" ECU_B
 SG_ GammaPayload : 23|8@0+ (1,0) [0|255] "" ECU_B

BO_ 1024 MsgDelta: 8 ECU_A
 SG_ Delta_CRC : 7|8@0+ (1,0) [0|255] "" ECU_B
 SG_ Delta_Counter : 15|4@0+ (1,0) [0|15] "" ECU_B
 SG_ DeltaPayload : 23|8@0+ (1,0) [0|255] "" ECU_B

CM_ SG_ 256 Checksum_Alpha "E2E Profile 1A CRC";
CM_ SG_ 512 Beta_CRC "E2E Profile 5 CRC";
CM_ SG_ 768 Gamma_Checksum "Checksum = ((Byte0+Byte1+Byte2+Byte3+Byte4+Byte5+Byte6) AND 0xFF) XOR 0xFF";
CM_ SG_ 1024 Delta_CRC "CRC (SAE J1850 CRC-8)";
'''

DATAID = {
    "format": "dataid_map_v2",
    "source": "synthetic",
    "mapping": "hi_lo_two_cols",
    "sheets": [],
    "entries": [
        {"frame_id": "0x100", "signal_name": "Checksum_Alpha", "dataid": "0x1234"},
        {"frame_id": "0x200", "signal_name": "Beta_CRC", "dataid": "0x0456"},
    ],
}

CONFIG = {
    "_comment": "Synthetic example. crc-check run -c examples/example/config.json -v",
    "dbc": "dbc",
    "traces": ["trace/example.blf"],
    "crc": {
        "preset": "CRC8/SAE-J1850",
        "auto_classify": True,
        "profile_by_width": True,
        "profiles": {
            "p01": {
                "preset": "CRC8/SAE-J1850-ZERO",
                "dataid_position": "prepend",
                "byte_swap": False,
                "counter_max_valid": 14,
                "range": {"mode": "exclude_crc"},
            }
        },
    },
    "range": {"mode": "exclude_crc"},
    "dataid": {
        "json": "dbc/dataid.json",
        "mapping": "hi_lo_two_cols",
        "position": "prepend",
        "byte_order": "lo_hi",
    },
    "filter": {"max_frames": 0},
    "output": {"format": "html", "file": "report.html"},
}


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _set_crc(data: bytearray, frame_id: int, start_bit: int, length: int,
             crc_range: CRCRange, engine: CRCEngine) -> None:
    """Compute the CRC over ``data`` and write it back big-endian."""
    frame = CanFrame(timestamp=0.0, arbitration_id=frame_id, dlc=len(data),
                     data=bytes(data))
    value = engine.compute_for_frame(frame, crc_range, start_bit, length,
                                     "big_endian")
    if crc_range.crc_byte_swap and length > 8:
        value = ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)
    byte = start_bit // 8
    if length > 8:
        data[byte] = (value >> 8) & 0xFF
        data[byte + 1] = value & 0xFF
    else:
        data[byte] = value & 0xFF


def _frames(bad: bool = False) -> list[tuple[float, int, bytes]]:  # pylint: disable=too-many-locals
    alpha_engine = CRCEngine(get_preset("CRC8/SAE-J1850-ZERO"))
    beta_engine = CRCEngine(get_preset("CRC16/CCITT"))
    gamma_engine = CRCEngine(get_preset("SUM8/XOR-FF"))
    delta_engine = CRCEngine(get_preset("CRC8/SAE-J1850"))

    alpha_range = CRCRange(mode="exclude_crc", dataid=0x1234,
                           dataid_position="prepend")
    beta_range = CRCRange(mode="custom_range", start_byte=0, end_byte=56,
                          dataid=0x0456, dataid_position="append",
                          crc_byte_swap=True)
    plain_range = CRCRange(mode="exclude_crc")

    frames: list[tuple[float, int, bytes]] = []
    timestamp = 0.0
    for index in range(40):
        counter = 5 if bad and 10 <= index <= 14 else index % 15
        timestamp += 0.01

        alpha = bytearray([0] * 8)
        alpha[1] = (counter << 4) | 0x02
        alpha[2] = index & 0xFF
        alpha[3] = (index * 3) & 0xFF
        _set_crc(alpha, 0x100, 0, 8, alpha_range, alpha_engine)
        if bad and index % 9 == 0:
            alpha[0] ^= 0xFF
        frames.append((timestamp, 0x100, bytes(alpha)))

        timestamp += 0.01
        beta = bytearray((index * 7 + i) & 0xFF for i in range(64))
        beta[2] = index & 0xFF
        _set_crc(beta, 0x200, 0, 16, beta_range, beta_engine)
        if bad and index % 11 == 0:
            beta[0] ^= 0xFF
        frames.append((timestamp, 0x200, bytes(beta)))

        timestamp += 0.01
        gamma = bytearray([0] * 8)
        gamma[1] = counter << 4
        gamma[2] = index & 0xFF
        gamma[6] = (index * 5) & 0xFF
        _set_crc(gamma, 0x300, 56, 8, plain_range, gamma_engine)
        frames.append((timestamp, 0x300, bytes(gamma)))

        timestamp += 0.01
        delta = bytearray([0] * 8)
        delta[1] = counter << 4
        delta[2] = index & 0xFF
        delta[5] = 0xA5
        _set_crc(delta, 0x400, 0, 8, plain_range, delta_engine)
        frames.append((timestamp, 0x400, bytes(delta)))
    return frames


def _write_trace(path: Path, bad: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with can.BLFWriter(str(path)) as writer:
        for timestamp, frame_id, data in _frames(bad):
            writer.on_message_received(can.Message(
                timestamp=timestamp, arbitration_id=frame_id,
                is_extended_id=False, is_fd=len(data) > 8,
                data=data, channel=1))


def main() -> None:
    """Write the example project files next to this script."""
    (HERE / "dbc").mkdir(parents=True, exist_ok=True)
    (HERE / "trace").mkdir(parents=True, exist_ok=True)
    (HERE / "dbc" / "network.dbc").write_text(DBC_TEXT, encoding="utf-8")
    (HERE / "dbc" / "dataid.json").write_text(
        json.dumps(DATAID, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (HERE / "config.json").write_text(
        json.dumps(CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    bad_config = dict(CONFIG, traces=["trace/example_bad.blf"])
    (HERE / "config_bad.json").write_text(
        json.dumps(bad_config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_trace(HERE / "trace" / "example.blf")
    _write_trace(HERE / "trace" / "example_bad.blf", bad=True)
    print(f"example written to {HERE}")


if __name__ == "__main__":
    main()
