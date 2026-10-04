"""Flight data recorder: crash-survivable circular store with a CRC per frame."""
from .recorder import FdrLogger, Frame, crc16, record_buses, replay
