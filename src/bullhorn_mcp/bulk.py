"""Bulk import orchestration for ClientCorporation and ClientContact entities."""

from .client import BullhornClient, BullhornAPIError
from .metadata import BullhornMetadata
from .fuzzy import score_company_match, score_contact_match, categorize_score


class BulkImporter:
    """Orchestrates bulk import of ClientCorporation and ClientContact entities.

    Processes companies first (deduplicating against Bullhorn), then contacts
    (resolving company references and owner names). Halts after 3 consecutive
    create errors to surface systemic issues early.
    """

    def __init__(self, client: BullhornClient, metadata: BullhornMetadata) -> None:
        self.client = client
        self.metadata = metadata
        self._consecutive_errors: int = 0

    def process(self, companies: list[dict], contacts: list[dict]) -> dict:
        """Process a batch of companies then contacts.

        Args:
            companies: List of company field dicts (must include "name").
            contacts: List of contact field dicts. Use "company_name" (str) to
                      reference a company by name, or "clientCorporation" (dict
                      with "id") to reference by ID directly.

        Returns:
            {"halted": bool, "summary": {...}, "details": {"companies": [...], "contacts": [...]}}
        """
        company_details: list[dict] = []
        company_id_map: dict[str, int] = {}  # input_name -> bullhorn_id
        halted = False

        for company in companies:
            detail, halted = self._process_single_company(company)
            company_details.append(detail)
            if detail.get("bullhorn_id") is not None:
                company_id_map[company.get("name", "")] = detail["bullhorn_id"]
            if halted:
                break

        contact_details: list[dict] = []
        if not halted:
            for contact in contacts:
                detail, halted = self._process_single_contact(contact, company_id_map)
                contact_details.append(detail)
                if halted:
                    break

        return {
            "halted": halted,
            "summary": self._build_summary(company_details, contact_details),
            "details": {
                "companies": company_details,
                "contacts": contact_details,
            },
        }

    # ------------------------------------------------------------------
    # Company processing
    # ------------------------------------------------------------------

    def _process_single_company(self, company: dict) -> tuple[dict, bool]:
        """Process one company record. Returns (detail, halted)."""
        name = company.get("name", "")
        input_name = name

        # Broad search for duplicates
        broad_term = name.split()[0] if name.strip() else name
        try:
            search_results = self.client.search(
                "ClientCorporation",
                query=f"name:{broad_term}*",
                fields="id,name,status,phone",
                count=50,
            )
        except BullhornAPIError as e:
            self._consecutive_errors += 1
            return (
                {"input_name": input_name, "status": "failed", "error": str(e)},
                self._consecutive_errors >= 3,
            )

        # Find best match
        best_match: dict | None = None
        best_score = 0.0
        for record in search_results:
            score = score_company_match(name, record.get("name", ""))
            if score > best_score:
                best_score = score
                best_match = record

        category = categorize_score(best_score) if best_match else "none"

        if category == "exact":
            self._consecutive_errors = 0
            return (
                {
                    "input_name": input_name,
                    "status": "existing",
                    "bullhorn_id": best_match["id"],  # type: ignore[index]
                    "match_confidence": round(best_score, 4),
                },
                False,
            )

        if category in ("likely", "possible"):
            self._consecutive_errors = 0
            return (
                {
                    "input_name": input_name,
                    "status": "flagged",
                    "bullhorn_id": best_match["id"],  # type: ignore[index]
                    "match_confidence": round(best_score, 4),
                    "match_category": category,
                },
                False,
            )

        # No meaningful match — create
        try:
            resolved = self.metadata.resolve_fields("ClientCorporation", company)
            result = self.client.create("ClientCorporation", resolved)
            self._consecutive_errors = 0
            return (
                {
                    "input_name": input_name,
                    "status": "created",
                    "bullhorn_id": result["changedEntityId"],
                },
                False,
            )
        except BullhornAPIError as e:
            self._consecutive_errors += 1
            return (
                {"input_name": input_name, "status": "failed", "error": str(e)},
                self._consecutive_errors >= 3,
            )

    # ------------------------------------------------------------------
    # Contact processing
    # ------------------------------------------------------------------

    def _process_single_contact(
        self, contact: dict, company_id_map: dict[str, int]
    ) -> tuple[dict, bool]:
        """Process one contact record. Returns (detail, halted)."""
        contact = dict(contact)
        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        input_name = f"{first} {last}".strip()

        # --- Resolve company ---
        company_name = contact.pop("company_name", None)
        if company_name and "clientCorporation" not in contact:
            company_id, halted = self._resolve_or_create_company(
                company_name, company_id_map
            )
            if halted or company_id is None:
                return (
                    {
                        "input_name": input_name,
                        "status": "failed",
                        "error": f"Could not resolve company '{company_name}'",
                    },
                    halted,
                )
            contact["clientCorporation"] = {"id": company_id}

        company_id_value = (
            contact.get("clientCorporation", {}).get("id")
            if isinstance(contact.get("clientCorporation"), dict)
            else None
        )

        # --- Resolve owner ---
        owner_raw = contact.get("owner")
        if owner_raw is not None:
            try:
                owner_result = self.client.resolve_owner(owner_raw)
            except ValueError as e:
                return (
                    {
                        "input_name": input_name,
                        "status": "failed",
                        "error": str(e),
                        "company_id": company_id_value,
                    },
                    False,
                )

            if isinstance(owner_result, list):
                # Ambiguous owner — flag for review, do not create
                return (
                    {
                        "input_name": input_name,
                        "status": "flagged",
                        "reason": "owner_ambiguous",
                        "owner_matches": owner_result,
                        "company_id": company_id_value,
                    },
                    False,
                )

            contact["owner"] = owner_result

        # --- Duplicate detection ---
        if company_id_value is not None:
            try:
                existing = self.client.search(
                    "ClientContact",
                    query=f"clientCorporation.id:{company_id_value}",
                    fields="id,firstName,lastName,email",
                    count=100,
                )
                for record in existing:
                    if score_contact_match(first, last, record) >= 0.95:
                        self._consecutive_errors = 0
                        return (
                            {
                                "input_name": input_name,
                                "status": "existing",
                                "bullhorn_id": record["id"],
                                "company_id": company_id_value,
                            },
                            False,
                        )
            except BullhornAPIError:
                pass  # Search failure is non-fatal; proceed to create attempt

        # --- Create contact ---
        try:
            resolved = self.metadata.resolve_fields("ClientContact", contact)
            result = self.client.create("ClientContact", resolved)
            self._consecutive_errors = 0
            return (
                {
                    "input_name": input_name,
                    "status": "created",
                    "bullhorn_id": result["changedEntityId"],
                    "company_id": company_id_value,
                },
                False,
            )
        except BullhornAPIError as e:
            self._consecutive_errors += 1
            return (
                {
                    "input_name": input_name,
                    "status": "failed",
                    "error": str(e),
                    "company_id": company_id_value,
                },
                self._consecutive_errors >= 3,
            )

    def _resolve_or_create_company(
        self, company_name: str, company_id_map: dict[str, int]
    ) -> tuple[int | None, bool]:
        """Resolve a company name to a Bullhorn ID, creating on-the-fly if needed.

        Returns (company_id, halted). company_id is None on failure.
        """
        # Check local map first
        if company_name in company_id_map:
            return company_id_map[company_name], False

        # Search Bullhorn
        broad_term = company_name.split()[0] if company_name.strip() else company_name
        try:
            results = self.client.search(
                "ClientCorporation",
                query=f"name:{broad_term}*",
                fields="id,name",
                count=50,
            )
        except BullhornAPIError as e:
            self._consecutive_errors += 1
            return None, self._consecutive_errors >= 3

        best: dict | None = None
        best_score = 0.0
        for r in results:
            s = score_company_match(company_name, r.get("name", ""))
            if s > best_score:
                best_score = s
                best = r

        if best and categorize_score(best_score) == "exact":
            company_id_map[company_name] = best["id"]
            return best["id"], False

        # Create on-the-fly
        try:
            resolved = self.metadata.resolve_fields(
                "ClientCorporation", {"name": company_name, "status": "Prospect"}
            )
            create_result = self.client.create("ClientCorporation", resolved)
            company_id = create_result["changedEntityId"]
            company_id_map[company_name] = company_id
            return company_id, False
        except BullhornAPIError as e:
            self._consecutive_errors += 1
            return None, self._consecutive_errors >= 3

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    def _build_summary(self, company_details: list[dict], contact_details: list[dict]) -> dict:
        """Aggregate status counts for companies and contacts."""

        def count_statuses(details: list[dict]) -> dict:
            counts = {"created": 0, "existing": 0, "flagged": 0, "failed": 0}
            for d in details:
                status = d.get("status", "")
                if status in counts:
                    counts[status] += 1
            return counts

        return {
            "companies": count_statuses(company_details),
            "contacts": count_statuses(contact_details),
        }
