from .c import C_QUERIES
from .cpp import CPP_QUERIES
from .erlang import ERLANG_QUERIES
from .fsharp import FSHARP_QUERIES
from .haskell import HASKELL_QUERIES
from .iaccfg import DOCKERFILE_QUERIES, GRAPHQL_QUERIES, HCL_QUERIES, SQL_QUERIES, TOML_QUERIES, YAML_QUERIES
from .java import JAVA_QUERIES
from .javascript import JS_QUERIES
from .julia import JULIA_QUERIES
from .kotlin import KOTLIN_QUERIES
from .nim import NIM_QUERIES
from .ocaml import OCAML_QUERIES
from .perl import PERL_QUERIES
from .python import PYTHON_QUERIES
from .rust import RUST_QUERIES
from .typescript import TS_QUERIES
from .zig import ZIG_QUERIES

LANGUAGE_QUERIES = {
    "python": PYTHON_QUERIES,
    "javascript": JS_QUERIES,
    "typescript": TS_QUERIES,
    "tsx": TS_QUERIES,
    "rust": RUST_QUERIES,
    "java": JAVA_QUERIES,
    "c": C_QUERIES,
    "cpp": CPP_QUERIES,
    "kotlin": KOTLIN_QUERIES,
    "julia": JULIA_QUERIES,
    "perl": PERL_QUERIES,
    "erlang": ERLANG_QUERIES,
    "ocaml": OCAML_QUERIES,
    "nim": NIM_QUERIES,
    "fsharp": FSHARP_QUERIES,
    "haskell": HASKELL_QUERIES,
    "zig": ZIG_QUERIES,
    "sql": SQL_QUERIES,
    "graphql": GRAPHQL_QUERIES,
    "yaml": YAML_QUERIES,
    "toml": TOML_QUERIES,
    "dockerfile": DOCKERFILE_QUERIES,
    "hcl": HCL_QUERIES,
}

__all__ = ["LANGUAGE_QUERIES"]
