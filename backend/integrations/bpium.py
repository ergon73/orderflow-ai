from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)


@dataclass
class BpiumClient:
    base_url: str = field(default_factory=lambda: os.getenv("BPIUM_BASE_URL", "").rstrip("/"))
    login: str = field(default_factory=lambda: os.getenv("BPIUM_LOGIN", ""))
    password: str = field(default_factory=lambda: os.getenv("BPIUM_PASSWORD", ""))
    catalog_id: str = field(default_factory=lambda: os.getenv("BPIUM_CATALOG_ID", ""))
    api_prefix: str = field(default_factory=lambda: os.getenv("BPIUM_API_PREFIX", "/api/v1"))
    timeout: int = field(default_factory=lambda: int(os.getenv("BPIUM_TIMEOUT", "15")))
    field_map: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.field_map:
            raw_map = os.getenv("BPIUM_FIELD_MAP", "{}")
            try:
                self.field_map = json.loads(raw_map)
            except json.JSONDecodeError:
                self.field_map = {}
        self.session = requests.Session()
        if self.login and self.password:
            self.session.auth = (self.login, self.password)

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.login and self.password and self.catalog_id)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _is_empty_value(value) -> bool:
        return value is None or (isinstance(value, str) and value == "")

    def _map_payload(self, payload: dict) -> dict:
        filtered = {
            key: value
            for key, value in payload.items()
            if not self._is_empty_value(value)
        }
        if not self.field_map:
            return filtered
        return {
            self.field_map.get(key, key): value for key, value in filtered.items()
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.session.request(
            method=method,
            url=self._url(path),
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def _extract_record_id(self, response_data: dict) -> str | None:
        if not isinstance(response_data, dict):
            return None
        if "id" in response_data:
            return str(response_data["id"])
        record = response_data.get("record")
        if isinstance(record, dict) and "id" in record:
            return str(record["id"])
        return None

    def _extract_records(self, response_data: dict | list) -> list[dict]:
        if isinstance(response_data, list):
            return [item for item in response_data if isinstance(item, dict)]
        if not isinstance(response_data, dict):
            return []
        for key in ("records", "data", "items"):
            records = response_data.get(key)
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
        if "id" in response_data and isinstance(response_data.get("values"), dict):
            return [response_data]
        return []

    def find_record_id_by_field(self, field_id: str, value: str) -> str | None:
        if not field_id:
            return None
        data = self._request(
            "GET",
            f"{self.api_prefix}/catalogs/{self.catalog_id}/records",
            params={
                "limit": 1,
                "offset": 0,
                "filters[0][fieldId]": str(field_id),
                "filters[0][value]": value,
            },
        )
        records = self._extract_records(data)
        if not records:
            return None
        return self._extract_record_id(records[0])

    def find_record_by_external_id(self, external_id: str) -> str | None:
        value = str(external_id).strip()
        if not value:
            return None

        field_id = str(self.field_map.get("external_id", "")).strip()
        if field_id.isdigit():
            record_id = self.find_record_id_by_field(field_id=field_id, value=value)
            if record_id:
                return record_id

        # Fallback when mapping is absent or filters are not usable in this workspace.
        data = self._request(
            "GET",
            f"{self.api_prefix}/catalogs/{self.catalog_id}/records",
            params={"searchText": value, "limit": 100, "offset": 0},
        )
        records = self._extract_records(data)
        for record in records:
            values = record.get("values")
            if not isinstance(values, dict):
                continue
            candidate = values.get(field_id) if field_id else values.get("external_id")
            if candidate is not None and str(candidate).strip() == value:
                return self._extract_record_id(record)
        return None

    def create_record(self, payload: dict) -> str | None:
        mapped = self._map_payload(payload)
        data = self._request(
            "POST",
            f"{self.api_prefix}/catalogs/{self.catalog_id}/records",
            json={"values": mapped},
        )
        return self._extract_record_id(data)

    def update_record(self, record_id: str, payload: dict) -> str | None:
        mapped = self._map_payload(payload)
        data = self._request(
            "PATCH",
            f"{self.api_prefix}/catalogs/{self.catalog_id}/records/{record_id}",
            json={"values": mapped},
        )
        return self._extract_record_id(data) or record_id
