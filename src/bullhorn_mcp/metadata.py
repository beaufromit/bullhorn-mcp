"""Bullhorn entity field metadata and label resolution."""

from .client import BullhornClient


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
        resolved = {}
        for key, value in fields.items():
            api_name = self.resolve_label_to_api(entity, key)
            resolved[api_name if api_name is not None else key] = value
        return resolved
