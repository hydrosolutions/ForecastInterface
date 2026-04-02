from enum import Enum, auto


class FailureCause(Enum):
    INPUT_DATA = auto()
    RESOURCE = auto()
    MODEL_ERROR = auto()
    CONFIGURATION = auto()
    DEPENDENCY = auto()
