"""Bullhorn entity field metadata and label resolution."""

from .client import BullhornClient
from .joborder_config import get_joborder_aliases

# Hardcoded aliases for known cases where Bullhorn's metadata labels do not
# reliably map to the correct API field name. These supplement (and take
# precedence over) the dynamic metadata lookup in resolve_fields().
#
# Format: {entity: {alias_lower: api_field_name}}
#
# "job title" → "occupation" for ClientContact:
#   Bullhorn ClientContact has two easily-confused fields:
#     - `title`      — salutation/name prefix (Mr, Ms, Dr, etc.)
#     - `occupation` — the person's job title (e.g. "VP of Engineering")
#   Callers commonly say "job title" meaning the role; without this alias the
#   key would pass through as `title`, silently setting the salutation field.
#
# JobOrder aliases extend the hardcoded set with env-defined entries at module
# load. Env entries override hardcoded ones on conflict so operators can correct
# instance-specific mappings without code changes (BULLHORN_JOBORDER_ALIASES).
FIELD_ALIASES: dict[str, dict[str, str]] = {
    "ClientContact": {
        "job title": "occupation",
    },
    "JobOrder": {
        "published description": "publicDescription",
        "public description": "publicDescription",
        "publish on website": "customText12",
        **get_joborder_aliases(),
    },
}


class BullhornMetadata:
    """Cache and resolve Bullhorn entity field metadata.

    Caches metadata per entity type within a session to avoid repeated
    round-trips. Provides bidirectional resolution between API field names
    and user-facing display labels.
    """

    def __init__(self, client: BullhornClient):
        self._client = client
        self._cache: dict[str, list[dict]] = {}

    def get_fields(self, entity: str) -> list[dict]:
        """Get field metadata for an entity type, caching results.

        Args:
            entity: Entity type (e.g. ClientContact, ClientCorporation)

        Returns:
            List of dicts with keys: name, label, type, required
        """
        if entity not in self._cache:
            meta = self._client.get_meta(entity)
            raw_fields = meta.get("fields", [])
            self._cache[entity] = [
                {
                    "name": f.get("name", ""),
                    "label": f.get("label", ""),
                    "type": f.get("type", ""),
                    "required": bool(f.get("required", False)),
                }
                for f in raw_fields
                if f.get("name")
            ]
        return self._cache[entity]

    def resolve_label_to_api(self, entity: str, label: str) -> str | None:
        """Return API field name for a given display label (case-insensitive).

        Args:
            entity: Entity type
            label: Display label (e.g. "Consultant")

        Returns:
            API field name (e.g. "recruiterUserID") or None if not found
        """
        label_lower = label.lower()
        for field in self.get_fields(entity):
            if field["label"].lower() == label_lower:
                return field["name"]
        return None

    def resolve_api_to_label(self, entity: str, api_name: str) -> str | None:
        """Return display label for a given API field name.

        Args:
            entity: Entity type
            api_name: API field name (e.g. "clientCorporation")

        Returns:
            Display label (e.g. "Company") or None if not found
        """
        for field in self.get_fields(entity):
            if field["name"] == api_name:
                return field["label"]
        return None

    def resolve_fields(self, entity: str, fields: dict) -> dict:
        """Resolve a dict of field keys to API names, passing through unknowns.

        Keys that match a display label are replaced with the corresponding
        API name. Keys that are already API names or are unrecognised pass
        through unchanged.

        Args:
            entity: Entity type
            fields: Dict of {field_name_or_label: value}

        Returns:
            New dict with all keys resolved to API field names where possible
        """
        entity_aliases = FIELD_ALIASES.get(entity, {})
        resolved = {}
        for key, value in fields.items():
            # Check hardcoded aliases first (handles known metadata gaps).
            alias = entity_aliases.get(key.lower())
            if alias is not None:
                resolved[alias] = value
            else:
                api_name = self.resolve_label_to_api(entity, key)
                resolved[api_name if api_name is not None else key] = value
        return resolved
