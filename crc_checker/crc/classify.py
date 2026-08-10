"""Auto-classify fx12fl-style checksum algorithms from DBC signal comments.

The fx12fl (Chery FX12) DBC describes the per-message checksum algorithm in
CM_ SG_ comments (mirrored into the E2E CSV "Signal Description" column):

  * "Checksum(SAE J1850 CRC-8)" / "CRC (SAE J1850 CRC-8)" / plain "CRC"
      -> CRC-8 (CRC8/SAE-J1850)
  * "((Byte0+Byte1+...+Byte6) AND 0xFF) XOR 0xFF" (sum excludes the checksum
      byte itself, which the verifier already skips) -> SUM8/XOR-FF
  * "0x01 XOR 0x27 XOR Byte0 XOR ... XOR Byte6" (YAS radar) -> XOR8/SEED with
      seed = XOR of all literal 0xNN constants in the comment

This mirrors ``Fx12flHooks.classify_crc_algo`` / ``parse_crc_seed`` in the
mcu_app_j6 com_code_generator.
"""

from __future__ import annotations

import re

from crc_checker.crc.models import CRCParams
from crc_checker.crc.presets import get_preset

# Order matters: sum-XOR is matched before generic XOR-seed.
_LITERAL_HEX = re.compile(r'0[xX][0-9A-Fa-f]+')


def classify_crc_algo(comment: str) -> str:
    """Classify a checksum signal's algorithm from its DBC comment.

    Returns one of "crc8" | "sum_xor" | "xor_seed" ('' if not classified).
    """
    desc = comment or ''
    desc_u = desc.upper()
    if 'BYTE0' in desc_u and 'AND 0XFF' in desc_u:
        return 'sum_xor'
    if 'BYTE0' in desc_u and 'XOR' in desc_u:
        return 'xor_seed'
    if 'CRC' in desc_u or 'CHECKSUM' in desc_u:
        return 'crc8'
    return ''


def parse_crc_seed(comment: str) -> int:
    """XOR of all literal 0xNN constants in the comment (YAS style)."""
    seed = 0
    for m in _LITERAL_HEX.findall(comment or ''):
        seed ^= int(m, 16)
    return seed


def build_crc_params_from_comment(comment: str,
                                  default_params: CRCParams | None = None) -> CRCParams | None:
    """Build CRCParams for a checksum signal from its DBC comment.

    Returns None when the comment does not describe a known algorithm
    (caller should keep the default params).

    Args:
        comment: DBC CM_ SG_ comment of the checksum signal.
        default_params: Fallback params (used for the "crc8" class). If None,
            CRC8/SAE-J1850 is used (fx12fl default).
    """
    algo = classify_crc_algo(comment)
    if not algo:
        return None
    if algo == 'sum_xor':
        return get_preset('SUM8/XOR-FF')
    if algo == 'xor_seed':
        seed = parse_crc_seed(comment)
        base = get_preset('XOR8/SEED')
        return CRCParams(
            width=base.width, polynomial=base.polynomial,
            initial_value=seed, final_xor=base.final_xor,
            reflect_in=base.reflect_in, reflect_out=base.reflect_out,
            name=f'XOR8/SEED (seed=0x{seed:02X})', checksum_type='xor_seed',
        )
    # crc8
    return default_params or get_preset('CRC8/SAE-J1850')
