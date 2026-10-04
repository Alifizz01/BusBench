"""The ten modules, in one place. The runner, the Studio and the README all read this."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    id: str
    domain: str          # automotive | avionics
    standard: str
    title: str
    lesson: str          # the one thing worth reading it for


MODULES = [
    Module("can", "automotive", "ISO 11898 · DBC", "CAN signal decoder",
           "Intel and Motorola bit layouts walk the message in opposite directions"),
    Module("uds", "automotive", "ISO 14229 · ISO 15765-2", "UDS diagnostic tester",
           "0x78 responsePending is not an error, and the ISO-TP sequence number is how a dropped frame gets caught"),
    Module("autosar", "automotive", "AUTOSAR Classic", "Layered ECU",
           "The layering rule is enforced by a test that reads the source, not just documented"),
    Module("safety", "automotive", "ISO 26262", "Safety monitor",
           "A windowed watchdog treats too early as a fault as well as too late"),
    Module("doip", "automotive", "ISO 13400", "DoIP gateway",
           "The protocol state machine is kept off the sockets, so every awkward case is a plain buffer"),
    Module("arinc429", "avionics", "ARINC 429", "Avionics word analyzer",
           "The label is bit reversed on the wire, and a word can decode perfectly and still be meaningless"),
    Module("mil1553", "avionics", "MIL-STD-1553B", "Bus controller",
           "Word count 32 encodes as 0, unless the subaddress makes those bits a mode code"),
    Module("arinc653", "avionics", "ARINC 653", "Partition scheduler",
           "The frame advances on the clock, so a hung partition can only ever hurt itself"),
    Module("traceability", "avionics", "DO-178C", "Traceability matrix",
           "Reads the source back, because a requirement whose test was deleted still looks traced"),
    Module("fdr", "avionics", "ED-112A style", "Flight data recorder",
           "A CRC per frame, not per file, so one torn write costs one frame"),
]

BY_ID = {m.id: m for m in MODULES}
