from .c import C_QUERIES
from .cpp import CPP_QUERIES
from .java import JAVA_QUERIES
from .javascript import JS_QUERIES
from .python import PYTHON_QUERIES
from .rust import RUST_QUERIES
from .typescript import TS_QUERIES

LANGUAGE_QUERIES = {
    "python": PYTHON_QUERIES,
    "javascript": JS_QUERIES,
    "typescript": TS_QUERIES,
    "tsx": TS_QUERIES,
    "rust": RUST_QUERIES,
    "java": JAVA_QUERIES,
    "c": C_QUERIES,
    "cpp": CPP_QUERIES,
}

__all__ = ["LANGUAGE_QUERIES"]
