from importlib import resources

from app.domain.glossary import BusinessGlossary, GlossaryTerm

GLOSSARY_RESOURCE_PACKAGE = "app.resources"
GLOSSARY_RESOURCE_NAME = "business_glossary.yaml"


class GlossaryLoadError(ValueError):
    """Raised when the bundled business glossary is malformed."""


class BusinessGlossaryLoader:
    """Load the bundled business glossary resource.

    The parser intentionally accepts only the small YAML subset used by the
    repository resource: top-level scalar fields, a top-level `terms` list,
    term scalar fields, and list-of-string fields.
    """

    def __init__(
        self,
        resource_package: str = GLOSSARY_RESOURCE_PACKAGE,
        resource_name: str = GLOSSARY_RESOURCE_NAME,
    ) -> None:
        self._resource_package = resource_package
        self._resource_name = resource_name

    def load(self) -> BusinessGlossary:
        resource = resources.files(self._resource_package).joinpath(self._resource_name)
        return parse_business_glossary(resource.read_text(encoding="utf-8"))


def parse_business_glossary(content: str) -> BusinessGlossary:
    version: int | None = None
    terms: list[dict[str, object]] = []
    current_term: dict[str, object] | None = None
    current_list_key: str | None = None

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            current_list_key = None
            if stripped.startswith("version:"):
                version = int(parse_scalar_value(stripped, "version"))
            elif stripped == "terms:":
                continue
            else:
                raise GlossaryLoadError(f"Unsupported glossary field: {stripped}")
        elif indent == 2 and stripped.startswith("- "):
            current_term = {}
            terms.append(current_term)
            current_list_key = None
            field = stripped[2:]
            if field:
                key, value = parse_key_value(field)
                current_term[key] = value
        elif indent == 4:
            if current_term is None:
                raise GlossaryLoadError("Glossary term field found before a term")
            key, value = parse_key_value(stripped)
            if value == "":
                current_term[key] = []
                current_list_key = key
            else:
                current_term[key] = value
                current_list_key = None
        elif indent == 6 and stripped.startswith("- "):
            if current_term is None or current_list_key is None:
                raise GlossaryLoadError("Glossary list item found outside a list field")
            values = current_term[current_list_key]
            if not isinstance(values, list):
                raise GlossaryLoadError("Glossary list field was not initialized as a list")
            values.append(unquote(stripped[2:]))
        else:
            raise GlossaryLoadError(f"Unsupported glossary indentation: {raw_line}")

    if version is None:
        raise GlossaryLoadError("Glossary version is required")

    parsed_terms = tuple(parse_term(term) for term in terms)
    if not parsed_terms:
        raise GlossaryLoadError("At least one glossary term is required")

    return BusinessGlossary(
        version=version,
        terms=tuple(sorted(parsed_terms, key=lambda term: term.name)),
    )


def parse_term(term: dict[str, object]) -> GlossaryTerm:
    required_fields = ("name", "definition", "expression")
    missing = [field for field in required_fields if not term.get(field)]
    if missing:
        raise GlossaryLoadError(f"Glossary term missing required fields: {', '.join(missing)}")

    return GlossaryTerm(
        name=str(term["name"]),
        definition=str(term["definition"]),
        expression=str(term["expression"]),
        related_tables=string_list(term.get("related_tables", [])),
        related_columns=string_list(term.get("related_columns", [])),
    )


def parse_key_value(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise GlossaryLoadError(f"Expected key/value field: {value}")
    key, scalar = value.split(":", 1)
    return key.strip(), unquote(scalar.strip())


def parse_scalar_value(value: str, key: str) -> str:
    parsed_key, scalar = parse_key_value(value)
    if parsed_key != key:
        raise GlossaryLoadError(f"Expected {key}, got {parsed_key}")
    return scalar


def string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise GlossaryLoadError("Expected a list of strings in glossary term")
    return tuple(str(item) for item in value)


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
