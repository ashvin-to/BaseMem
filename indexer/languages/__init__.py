from .c import C_QUERIES
from .bash import BASH_QUERIES
from .cpp import CPP_QUERIES
from .dart import DART_QUERIES
from .erlang import ERLANG_QUERIES
from .fsharp import FSHARP_QUERIES
from .haskell import HASKELL_QUERIES
from .csharp import CSHARP_QUERIES
from .go import GO_QUERIES
from .r import R_QUERIES
from .scala import SCALA_QUERIES
from .iaccfg import DOCKERFILE_QUERIES, GRAPHQL_QUERIES, HCL_QUERIES, SQL_QUERIES, TOML_QUERIES, YAML_QUERIES
from .java import JAVA_QUERIES
from .javascript import JS_QUERIES
from .julia import JULIA_QUERIES
from .kotlin import KOTLIN_QUERIES
from .lua import LUA_QUERIES
from .nim import NIM_QUERIES
from .ocaml import OCAML_QUERIES
from .objc import OBJC_QUERIES
from .perl import PERL_QUERIES
from .php import PHP_QUERIES
from .ruby import RUBY_QUERIES
from .python import PYTHON_QUERIES
from .rust import RUST_QUERIES
from .typescript import TS_QUERIES
from .swift import SWIFT_QUERIES
from .zig import ZIG_QUERIES

LANGUAGE_QUERIES = {
    "python": PYTHON_QUERIES,
    "javascript": JS_QUERIES,
    "typescript": TS_QUERIES,
    "tsx": TS_QUERIES,
    "rust": RUST_QUERIES,
    "java": JAVA_QUERIES,
    "bash": BASH_QUERIES,
    "c": C_QUERIES,
    "cpp": CPP_QUERIES,
    "kotlin": KOTLIN_QUERIES,
    "julia": JULIA_QUERIES,
    "perl": PERL_QUERIES,
    "csharp": CSHARP_QUERIES,
    "erlang": ERLANG_QUERIES,
    "ocaml": OCAML_QUERIES,
    "lua": LUA_QUERIES,
    "nim": NIM_QUERIES,
    "fsharp": FSHARP_QUERIES,
    "haskell": HASKELL_QUERIES,
    "swift": SWIFT_QUERIES,
    "zig": ZIG_QUERIES,
    "go": GO_QUERIES,
    "objc": OBJC_QUERIES,
    "php": PHP_QUERIES,
    "r": R_QUERIES,
    "ruby": RUBY_QUERIES,
    "scala": SCALA_QUERIES,
    "sql": SQL_QUERIES,
    "graphql": GRAPHQL_QUERIES,
    "yaml": YAML_QUERIES,
    "toml": TOML_QUERIES,
    "dart": DART_QUERIES,
    "dockerfile": DOCKERFILE_QUERIES,
    "hcl": HCL_QUERIES,
}

__all__ = ["LANGUAGE_QUERIES"]
