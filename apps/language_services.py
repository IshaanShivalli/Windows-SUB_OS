"""Lightweight, local language support for the Operator terminal editor."""

import ast
import builtins
import keyword
import re
import sys

from prompt_toolkit.completion import Completer, Completion


_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_VYN_DECLARATION_RE = re.compile(
    r"^\s*(?:function\s+([A-Za-z_]\w*)|Class\s+(?:obj\s+)?([A-Za-z_]\w*)|"
    r"([A-Za-z_]\w*)\s*=\s*(?!=))",
    re.IGNORECASE | re.MULTILINE,
)
_PYTHON_TYPE_NAMES = {
    "bool": bool,
    "bytes": bytes,
    "bytearray": bytearray,
    "dict": dict,
    "float": float,
    "frozenset": frozenset,
    "int": int,
    "list": list,
    "set": set,
    "str": str,
    "tuple": tuple,
}


def python_syntax_diagnostic(source, filename="<buffer>"):
    try:
        compile(source, filename, "exec")
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        column = getattr(exc, "offset", None)
        message = getattr(exc, "msg", None) or str(exc)
        if line is not None:
            location = f"line {line}"
            if column is not None:
                location += f", column {column}"
            return f"{location}: {message}"
        return message
    return None


class LanguageCompleter(Completer):
    def __init__(self, extension):
        self.package_id = extension["package_id"]
        self.language = extension["language"]
        self.words = tuple(extension["completions"])

    def get_completions(self, document, _complete_event):
        prefix_match = re.search(r"[A-Za-z_]\w*$", document.text_before_cursor)
        prefix = prefix_match.group(0) if prefix_match else ""
        before_prefix = document.text_before_cursor[:-len(prefix)] if prefix else document.text_before_cursor
        source = document.text
        candidates = set(self.words)

        if self.package_id == "editor.lang.python":
            candidates.update(keyword.kwlist)
            candidates.update(
                name for name in dir(builtins) if not name.startswith("__")
            )
            candidates.update(sys.stdlib_module_names)
            candidates.update(_python_identifiers(source))
            attribute_match = re.search(
                r"([A-Za-z_]\w*)\.$",
                before_prefix.rstrip(),
            )
            if attribute_match:
                value_type = _infer_python_types(source).get(attribute_match.group(1))
                if value_type is not None:
                    candidates = {
                        name for name in dir(value_type) if not name.startswith("__")
                    }
        elif self.package_id == "editor.lang.vyn":
            candidates.update(_IDENTIFIER_RE.findall(source))
            candidates.update(
                name
                for declaration in _VYN_DECLARATION_RE.finditer(source)
                for name in declaration.groups()
                if name
            )

        case_sensitive = self.package_id == "editor.lang.python"
        comparison_prefix = prefix if case_sensitive else prefix.casefold()
        for candidate in sorted(candidates, key=str.casefold):
            comparison_candidate = candidate if case_sensitive else candidate.casefold()
            if not candidate or not comparison_candidate.startswith(comparison_prefix):
                continue
            yield Completion(
                candidate,
                start_position=-len(prefix),
                display=candidate,
                display_meta=self.language,
            )


def _python_identifiers(source):
    names = set(_IDENTIFIER_RE.findall(source))
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".", 1)[0])
    return names


def _infer_python_types(source):
    lines = source.splitlines()
    tree = None
    while lines:
        try:
            tree = ast.parse("\n".join(lines))
            break
        except SyntaxError:
            lines.pop()
    if tree is None:
        return {}
    inferred = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_type = _infer_builtin_type(value)
        if value_type is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                inferred[target.id] = value_type
    return inferred


def _infer_builtin_type(node):
    if isinstance(node, ast.Constant):
        return type(node.value)
    if isinstance(node, ast.List):
        return list
    if isinstance(node, ast.Dict):
        return dict
    if isinstance(node, ast.Set):
        return set
    if isinstance(node, ast.Tuple):
        return tuple
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return _PYTHON_TYPE_NAMES.get(node.func.id)
    return None
