"""Live TinyFish API Client implementation with full provider logging."""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from .adapter import TinyFishAdapter
from ..db import crud


import socket

STATIC_HOSTS = {
    "agent.tinyfish.ai": "54.219.125.104",
    "api.search.tinyfish.ai": "65.9.130.55",
    "api.fetch.tinyfish.ai": "18.66.147.90",
}

_dns_patched = False
def _ensure_resilient_dns():
    """
    Ensure reliable DNS resolution for TinyFish endpoints.

    Rationale, Freshness & Failure Behavior:
    1. Standard Live DNS (IPv4 Preferred):
       Many Linux environments (systemd-resolved, dual-stack networks, NAT64) return synthesized
       IPv6 (NAT64 64:ff9b::) addresses ahead of IPv4. When host IPv6 routing is unavailable,
       connection handshakes hang until timeout. Querying AF_INET first ensures 100% dynamic
       upstream DNS resolution, receiving fresh, current IP addresses from authoritative resolvers.
    2. Fallback to Standard Resolution:
       If IPv4-specific lookup raises an error, fall back to standard family resolution.
    3. Last-Resort Static Fallback (STATIC_HOSTS):
       If both standard lookups fail with socket.gaierror (e.g. transient local resolver outage),
       fall back to last-known static IPv4 addresses to preserve audit execution continuity.
    """
    global _dns_patched
    if not _dns_patched:
        orig_getaddrinfo = socket.getaddrinfo
        def resilient_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            # Step 1: Attempt standard live DNS resolution with IPv4 preference
            try:
                res = orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
                if res:
                    return res
            except socket.gaierror:
                pass
            except Exception:
                pass

            # Step 2: Attempt standard resolution with original family
            try:
                return orig_getaddrinfo(host, port, family, type, proto, flags)
            except socket.gaierror:
                # Step 3: Last-resort fallback for known TinyFish hosts
                if host in STATIC_HOSTS:
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (STATIC_HOSTS[host], port))]
                raise

        socket.getaddrinfo = resilient_getaddrinfo
        _dns_patched = True

_ensure_resilient_dns()



class RealTinyFishClient(TinyFishAdapter):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TINYFISH_API_KEY", "")
        self.agent_base = "https://agent.tinyfish.ai"
        self.search_base = "https://api.search.tinyfish.ai"
        self.fetch_base = "https://api.fetch.tinyfish.ai"

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def search(self, query: str, audit_id: str, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
        req_at = datetime.now(timezone.utc).isoformat()
        encoded_q = urllib.parse.quote(query)
        url = f"{self.search_base}/?query={encoded_q}"
        if purpose:
            url += f"&purpose={urllib.parse.quote(purpose)}"

        req = urllib.request.Request(url, headers={"X-API-Key": self.api_key}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                crud.log_provider_call(
                    audit_id=audit_id,
                    operation="search",
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
                return results
        except urllib.error.HTTPError as e:
            crud.log_provider_call(
                audit_id=audit_id,
                operation="search",
                response_status=e.code,
                error_class=e.reason,
                result_usable=False,
                requested_at=req_at,
            )
            return []
        except Exception as e:
            crud.log_provider_call(
                audit_id=audit_id,
                operation="search",
                error_class=str(e),
                result_usable=False,
                requested_at=req_at,
            )
            return []

    def fetch(self, urls: List[str], audit_id: str, ttl: int = 0, purpose: Optional[str] = None) -> Dict[str, Any]:
        req_at = datetime.now(timezone.utc).isoformat()
        body: Dict[str, Any] = {
            "urls": urls[:10],
            "format": "markdown",
            "ttl": ttl,
        }
        if purpose:
            body["purpose"] = purpose

        req = urllib.request.Request(
            f"{self.fetch_base}/",
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                crud.log_provider_call(
                    audit_id=audit_id,
                    operation="fetch",
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
                return data
        except urllib.error.HTTPError as e:
            crud.log_provider_call(
                audit_id=audit_id,
                operation="fetch",
                response_status=e.code,
                error_class=e.reason,
                result_usable=False,
                requested_at=req_at,
            )
            return {"results": [], "errors": [{"error": str(e.reason), "status": e.code}]}
        except Exception as e:
            crud.log_provider_call(
                audit_id=audit_id,
                operation="fetch",
                error_class=str(e),
                result_usable=False,
                requested_at=req_at,
            )
            return {"results": [], "errors": [{"error": str(e)}]}

    def submit_agent_run(
        self,
        url: str,
        goal: str,
        audit_id: str,
        run_id: str,
        output_schema: Dict[str, Any],
        browser_profile: str = "lite",
        use_profile: bool = False,
        profile_id: Optional[str] = None,
    ) -> str:
        req_at = datetime.now(timezone.utc).isoformat()
        body: Dict[str, Any] = {
            "url": url,
            "goal": goal,
            "browser_profile": browser_profile,
            "capture_config": {
                "screenshots": True,
                "snapshots": True,
                "html": True,
            },
            "output_schema": output_schema,
        }
        if use_profile and profile_id:
            body["use_profile"] = True
            body["profile_id"] = profile_id

        req = urllib.request.Request(
            f"{self.agent_base}/v1/automation/run-async",
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                prov_run_id = data.get("run_id")
                crud.log_provider_call(
                    audit_id=audit_id,
                    run_id=run_id,
                    operation="agent_submit",
                    provider_request_id=prov_run_id,
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
                return prov_run_id
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            crud.log_provider_call(
                audit_id=audit_id,
                run_id=run_id,
                operation="agent_submit",
                response_status=e.code,
                error_class=err_body,
                result_usable=False,
                requested_at=req_at,
            )
            raise RuntimeError(f"TinyFish agent submission failed: {e.code} - {err_body}")

    def poll_agent_run(self, provider_run_id: str, audit_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        req_at = datetime.now(timezone.utc).isoformat()
        req = urllib.request.Request(
            f"{self.agent_base}/v1/runs/{provider_run_id}?screenshots=base64",
            headers={"X-API-Key": self.api_key},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                crud.log_provider_call(
                    audit_id=audit_id,
                    run_id=run_id,
                    operation="agent_poll",
                    provider_request_id=provider_run_id,
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
                return data
        except Exception as e:
            crud.log_provider_call(
                audit_id=audit_id,
                run_id=run_id,
                operation="agent_poll",
                provider_request_id=provider_run_id,
                error_class=str(e),
                result_usable=False,
                requested_at=req_at,
            )
            raise

    def download_screenshot(self, provider_run_id: str, step_id: str, audit_id: str, run_id: Optional[str] = None) -> bytes:
        req_at = datetime.now(timezone.utc).isoformat()
        req = urllib.request.Request(
            f"{self.agent_base}/v1/runs/{provider_run_id}/steps/{step_id}/screenshot",
            headers={"X-API-Key": self.api_key},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_bytes = resp.read()
                crud.log_provider_call(
                    audit_id=audit_id,
                    run_id=run_id,
                    operation="screenshot",
                    provider_request_id=f"{provider_run_id}/{step_id}",
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
                return raw_bytes
        except Exception as e:
            crud.log_provider_call(
                audit_id=audit_id,
                run_id=run_id,
                operation="screenshot",
                provider_request_id=f"{provider_run_id}/{step_id}",
                error_class=str(e),
                result_usable=False,
                requested_at=req_at,
            )
            raise

    def create_browser_profile(self, name: str, audit_id: str) -> str:
        req_at = datetime.now(timezone.utc).isoformat()
        req = urllib.request.Request(
            f"{self.agent_base}/v1/profiles",
            data=json.dumps({"name": name}).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                prof_id = data.get("id")
                crud.log_provider_call(
                    audit_id=audit_id,
                    operation="profile_create",
                    provider_request_id=prof_id,
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
                return prof_id
        except Exception as e:
            crud.log_provider_call(
                audit_id=audit_id,
                operation="profile_create",
                error_class=str(e),
                result_usable=False,
                requested_at=req_at,
            )
            raise

    def delete_browser_profile(self, profile_id: str, audit_id: str) -> None:
        req_at = datetime.now(timezone.utc).isoformat()
        req = urllib.request.Request(
            f"{self.agent_base}/v1/profiles/{profile_id}",
            headers={"X-API-Key": self.api_key},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                crud.log_provider_call(
                    audit_id=audit_id,
                    operation="profile_delete",
                    provider_request_id=profile_id,
                    response_status=resp.status,
                    result_usable=True,
                    requested_at=req_at,
                )
        except Exception as e:
            crud.log_provider_call(
                audit_id=audit_id,
                operation="profile_delete",
                provider_request_id=profile_id,
                error_class=str(e),
                result_usable=False,
                requested_at=req_at,
            )
