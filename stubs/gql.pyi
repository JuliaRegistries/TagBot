"""Type stubs for gql library."""

from typing import Any, Dict, Optional

class Client:
    def execute(self, query: Any, variable_values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...
