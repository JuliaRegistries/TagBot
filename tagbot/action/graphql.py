"""GraphQL query utilities for GitHub API batching.

This module provides optimized GraphQL queries to replace multiple REST API calls
with single batched requests.
"""

from typing import Any, Dict, List, Optional, Tuple
from github import Github, GithubException

from .. import logger


class GraphQLClient:
    """Client for executing GraphQL queries against GitHub API."""

    def __init__(self, github_client: Github) -> None:
        """Initialize GraphQL client with GitHub connection.

        Args:
            github_client: Authenticated PyGithub client instance.
        """
        self._github = github_client
        # Access the requester attribute (it's private but we need it)
        self._requester = github_client._Github__requester  # type: ignore

    def query(self, query_str: str, variables: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a GraphQL query.

        Args:
            query_str: GraphQL query string.
            variables: Optional variables dict for the query.

        Returns:
            Query result data.

        Raises:
            GithubException: If query fails.
        """
        payload: Dict[str, Any] = {"query": query_str}
        if variables:
            payload["variables"] = variables

        headers, data = self._requester.requestJsonAndCheck(
            "POST", "/graphql", input=payload
        )

        if "errors" in data:
            error_messages = [e.get("message", str(e)) for e in data["errors"]]
            raise GithubException(
                400, {"message": f"GraphQL errors: {'; '.join(error_messages)}"}, {}
            )

        return data.get("data", {})

    def fetch_tags_and_releases(
        self, owner: str, name: str, max_items: int = 100
    ) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
        """Fetch all tags and releases in a single query.

        This replaces separate calls to get_git_matching_refs("tags/")
        and get_releases().

        Args:
            owner: Repository owner.
            name: Repository name.
            max_items: Maximum number of items to fetch per type (default 100).

        Returns:
            Tuple of (tags_dict, releases_list) where:
            - tags_dict maps tag names to commit SHAs
            - releases_list contains release metadata dicts
        """
        query = """
        query($owner: String!, $name: String!, $maxItems: Int!) {
          repository(owner: $owner, name: $name) {
            refs(
              refPrefix: "refs/tags/",
              first: $maxItems,
              orderBy: {field: TAG_COMMIT_DATE, direction: DESC}
            ) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                name
                target {
                  oid
                  ... on Commit {
                    oid
                  }
                  ... on Tag {
                    target {
                      oid
                    }
                  }
                }
              }
            }
            releases(first: $maxItems, orderBy: {field: CREATED_AT, direction: DESC}) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                tagName
                createdAt
                tagCommit {
                  oid
                }
                isDraft
                isPrerelease
              }
            }
          }
        }
        """

        variables = {"owner": owner, "name": name, "maxItems": max_items}
        logger.debug(f"Fetching tags and releases via GraphQL for {owner}/{name}")

        result = self.query(query, variables)
        repo_data = result.get("repository", {})

        # Process tags
        tags_dict: Dict[str, str] = {}
        refs_data = repo_data.get("refs", {})
        for node in refs_data.get("nodes", []):
            tag_name = node["name"]
            target = node.get("target", {})

            # Handle both direct commits and annotated tags
            # Annotated tags have a nested target structure, lightweight tags don't
            nested_target = target.get("target")
            if nested_target:
                # Annotated tag - resolve to underlying commit SHA
                # GraphQL returns nested target: target.target.oid is the commit
                commit_sha = nested_target.get("oid")
                if commit_sha:
                    tags_dict[tag_name] = commit_sha
            else:
                # Lightweight tag - direct commit reference
                commit_sha = target.get("oid")
                if commit_sha:
                    tags_dict[tag_name] = commit_sha

        # Process releases
        releases_list: List[Dict[str, Any]] = []
        releases_data = repo_data.get("releases", {})
        for node in releases_data.get("nodes", []):
            if node:  # Skip None entries
                releases_list.append(node)

        # Check for pagination (log warning if data is truncated)
        if refs_data.get("pageInfo", {}).get("hasNextPage"):
            logger.warning(
                f"Repository has more than {max_items} tags, "
                "some may not be cached. Consider pagination."
            )

        if releases_data.get("pageInfo", {}).get("hasNextPage"):
            logger.warning(
                f"Repository has more than {max_items} releases, "
                "some may not be cached. Consider pagination."
            )

        logger.debug(
            f"GraphQL fetched {len(tags_dict)} tags and {len(releases_list)} releases"
        )

        return tags_dict, releases_list

