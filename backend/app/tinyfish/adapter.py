"""Base TinyFish Adapter Interface."""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class TinyFishAdapter(ABC):
    @abstractmethod
    def search(self, query: str, audit_id: str, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search the web for merchant, policy, or product pages."""
        pass

    @abstractmethod
    def fetch(self, urls: List[str], audit_id: str, ttl: int = 0, purpose: Optional[str] = None) -> Dict[str, Any]:
        """Fetch and extract clean page content."""
        pass

    @abstractmethod
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
        """Submit an async agent run. Returns provider_run_id."""
        pass

    @abstractmethod
    def poll_agent_run(self, provider_run_id: str, audit_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Poll the provider run status and return full run record."""
        pass

    @abstractmethod
    def download_screenshot(self, provider_run_id: str, step_id: str, audit_id: str, run_id: Optional[str] = None) -> bytes:
        """Download screenshot binary bytes for a given step."""
        pass

    @abstractmethod
    def create_browser_profile(self, name: str, audit_id: str) -> str:
        """Create an isolated Browser Context Profile. Returns profile_id."""
        pass

    @abstractmethod
    def delete_browser_profile(self, profile_id: str, audit_id: str) -> None:
        """Delete an isolated Browser Context Profile."""
        pass
