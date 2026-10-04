"""ARINC 429: 32-bit avionics words, label dictionaries and capture analysis."""
from .analyzer import (Label, analyze, build_word, check_parity, get_label, get_sdi, get_ssm,
                       is_usable, load_dictionary, read_capture)
