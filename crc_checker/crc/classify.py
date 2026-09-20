"""Auto-classify OEM-specific checksum algorithms from DBC signal comments.

Two OEM families are supported (mirroring the mcu_app_j6 com_code_generator
hooks):

fx12fl (Chery FX12, Fx12flHooks):
  * "Checksum(SAE J1850 CRC-8)" / "CRC (SAE J1850 CRC-8)" / plain "CRC"
      -> CRC-8 (CRC8/SAE-J1850)
  * "((Byte0+Byte1+...+Byte6) AND 0xFF) XOR 0xFF" -> SUM8/XOR-FF
  * "0x01 XOR 0x27 XOR Byte0 XOR ... XOR Byte6" (YAS radar) -> XOR8/SEED with
      seed = XOR of all literal 0xNN constants in the comment

b81vs (BAIC, BaicB81vsHooks):
  * "Checksum = (byte0+byte1+...+byteN) and 0xFF" -> SUM8 (sum AND 0xFF,
      no final XOR)
  * "CRC checksum. ...（Profile：1A；DataID：0x00EB）" -> Profile 1A
      (CRC8/SAE-J1850-ZERO + DataID parsed from the comment)
  * "算法另附文件"/"另附" or sub-byte checksum -> 'skip' (not auto-verifiable)
"""

from __future__ import annotations

import re

from crc_checker.crc.models import CRCParams
from crc_checker.crc.presets import get_preset

# Order matters: sum-XOR is matched before generic XOR-seed.
_LITERAL_HEX = re.compile(r'0[xX][0-9A-Fa-f]+')
# b81vs Profile 1A DataID: "DataID：0x00EB" (full-width colon tolerated)
_DATAID_RE = re.compile(r'DataID\s*[：:=]?\s*0[xX]([0-9A-Fa-f]+)', re.IGNORECASE)


def classify_crc_algo(comment: str) -> str:  # pylint: disable=too-many-return-statements
    """Classify a checksum signal's algorithm from its DBC comment.

    Returns one of "crc8" | "sum_xor" | "xor_seed" | "p01" | "p05" | "skip"
    ('' if not classified).
    """
    desc = comment or ''
    desc_u = desc.upper()

    # b81vs: algorithm described in an external file or a sub-byte (nibble)
    # checksum — not auto-generatable
    if '另附' in desc or 'NIBBLE' in desc_u:
        return 'skip'

    # b81vs Profile 1A (E2E): description mentions Profile 1A + DataID
    if 'PROFILE' in desc_u and '1A' in desc_u:
        return 'p01'

    # AUTOSAR E2E Profile 5 (GAC DBCs: "E2E Profile 5 CRC"): the description
    # names a profile, not a CRC polynomial. The algorithm/range/DataID layout
    # come from the profile table (crc/profiles.py), so this must not fall
    # through to the generic "CRC" → crc8 branch below.
    if 'PROFILE' in desc_u and re.search(r'PROFILE[^0-9]{0,12}5', desc_u):
        return 'p05'

    # Chery multi-project comment: "HH12_PT_26款项目:((Byte0+...+Byte6) AND
    # 0xFF) XOR 0xFF\nEEA4.01其他项目:SAE J1850 CRC-8" — the first branch is a
    # different vehicle project; fx12fl is an EEA4.01 project, so the EEA4.01
    # branch (J1850 CRC-8) wins over the other project's sum-XOR heuristics.
    eea401_crc = 'EEA4.01' in desc_u and 'CRC' in desc_u

    if not eea401_crc:
        # Sum checksums list the participating bytes ("byte0/byte1/...") and AND
        # the result with 0xFF. Note b81vs may start at byte1 when the CRC sits
        # in byte0, so match any 'BYTE' reference, not just BYTE0. The
        # fx12fl/EPB1 variant appends "XOR 0xFF" (sum then final XOR); b81vs
        # plain sum does not.
        if 'BYTE' in desc_u and ('AND 0XFF' in desc_u
                                 or ('XOR' in desc_u and '0XFF' in desc_u)):
            return 'sum_xor'
        if 'BYTE' in desc_u and 'XOR' in desc_u:
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


def parse_dataid_from_comment(comment: str) -> int | None:
    """Extract a b81vs Profile 1A DataID ("DataID：0x00EB") from a comment."""
    m = _DATAID_RE.search(comment or '')
    return int(m.group(1), 16) if m else None


def build_crc_params_from_comment(comment: str,
                                  default_params: CRCParams | None = None) -> CRCParams | None:
    """Build CRCParams for a checksum signal from its DBC comment.

    Returns None when the comment does not describe a known algorithm
    (caller should keep the default params). For 'p01'/'skip' the caller
    handles DataID/skipping separately (see DBCProtectionMap.
    apply_comment_classification).

    Args:
        comment: DBC CM_ SG_ comment of the checksum signal.
        default_params: Fallback params (used for the "crc8" class). If None,
            CRC8/SAE-J1850 is used (fx12fl default).
    """
    algo = classify_crc_algo(comment)
    if not algo:
        return None
    if algo in ('skip', 'p05'):
        # b81vs: algorithm described in an external file — caller keeps default.
        # p05: the comment names an E2E profile; params come from
        # DBCProtectionMap.apply_profiles (crc/profiles.py).
        return None
    if algo == 'sum_xor':
        # All crc_calculatecrcxor implementations (iNetE2E_Can.cpp, b70ks
        # NetCom_CRC.cpp) end with "uCRC ^= 0xFF", so the algorithm is
        # SUM8/XOR-FF even when the DBC comment omits the XOR (b81vs writes
        # "Checksum = (...) and 0xFF" but the firmware still XORs 0xFF).
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
    if algo == 'p01':
        # b81vs Profile 1A: CRC8/SAE-J1850-ZERO (DataID applied by caller)
        return get_preset('CRC8/SAE-J1850-ZERO')
    # crc8
    return default_params or get_preset('CRC8/SAE-J1850')
