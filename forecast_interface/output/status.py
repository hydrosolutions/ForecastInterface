from enum import Enum, auto


class VariableStatus(Enum):
    SUCCESS = auto()
    FAILURE = auto()
    PARTIAL = auto()
