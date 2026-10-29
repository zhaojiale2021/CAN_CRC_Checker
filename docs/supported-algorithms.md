# Supported algorithms — validation status

The tool ships several checksum presets. Only some of them have been checked
against captured CAN data; the rest are implemented and unit-tested against
published known-answer vectors, but have **not** been verified with real vehicle
data. `crc-check presets` prints the same status.

## Verified with real data

| Preset | How it was verified |
|--------|---------------------|
| `CRC16/CCITT` (E2E Profile 5) | Full E2E runs over captured CAN FD traces: expected values matched for every protected frame, including DataID append and CRC byte swap. |
| `CRC8/SAE-J1850-ZERO` (E2E Profile 1 / 1A) | Full E2E runs over captured traces, including prepended DataID and the 4-bit counter range 0..14. |
| `CRC8/SAE-J1850` | Per-message comment-driven classification over captured traces. |
| `SUM8/XOR-FF` | Sum-of-bytes-then-XOR checksums over captured traces, including multi-segment CAN FD frames. |
| `XOR8/SEED` | Byte-wise XOR with a seed constant over captured radar sensor frames. |
| `SUM8` | Plain additive sum over captured traces. Wider (16-bit) checksum fields in the same family have not been verified. |

## Not verified with real data

| Preset | Notes |
|--------|-------|
| `CRC8/AUTOSAR` | Known-answer vectors only. |
| `CRC8/H2F` | Known-answer vectors only. |
| `CRC16/ARC` | Known-answer vectors only. |
| `CRC16/MODBUS` | Known-answer vectors only. |
| `CRC32/AUTOSAR` | Known-answer vectors only. |
| `CRC32/ETHERNET` | Known-answer vectors only. |
| `XOR8` | Known-answer vectors only (the seeded variant `XOR8/SEED` is verified). |

Custom CRC parameters (`crc.custom`) are always unverified until you run them
against data you trust.

## Promotion checklist

To mark an algorithm as verified:

1. Capture a trace containing the message, with enough frames to cover counter
   wrap-around.
2. Configure the preset and the correct CRC byte range.
3. Confirm CRC and rolling-counter verdicts are clean over the whole trace
   (`fail_count == 0`, or failures explained by known sensor/test conditions).
4. Add a regression test with synthetic data that reproduces the same values,
   and update this table plus `VALIDATION` in `crc_checker/crc/presets.py`.

The shipped `examples/example` project exercises Profile 1A, Profile 5, plain
CRC-8 and SUM8/XOR-FF end to end on synthetic data.
