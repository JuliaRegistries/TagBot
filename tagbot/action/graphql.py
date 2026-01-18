"""GraphQL query utilities for GitHub API batching.

This module provides optimized GraphQL queries to replace multiple REST API calls
with single batched requests.
"""

from typing import Any, Dict, List, Optional, Tuple
from github import Github

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
            raise Exception(f"GraphQL errors: {'; '.join(error_messages)}")

        return data.get("data", {})

    def fetch_tags_and_releases(
        self, owner: str, name: str, max_items: int = 100
    ) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
        """Fetch all tags and releases in a single query.

        This replaces separate calls to get_git_matching_refs("tags/") and get_releases().

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
            refs(refPrefix: "refs/tags/", first: $maxItems, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
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
            # Use same pattern as REST API: store annotated tags with prefix for lazy resolution
            if target.get("__typename") == "Tag":
                # Annotated tag - store with prefix for lazy resolution
                tag_sha = target.get("oid")
                if tag_sha:
                    tags_dict[tag_name] = f"annotated:{tag_sha}"
            else:
                # Direct commit reference
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

    def fetch_commits_metadata(
        self, owner: str, name: str, commit_shas: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch metadata for multiple commits in a single query.

        Args:
            owner: Repository owner.
            name: Repository name.
            commit_shas: List of commit SHAs to fetch.

        Returns:
            Dict mapping commit SHA to metadata (committedDate, author, etc).
        """
        if not commit_shas:
            return {}

        # GraphQL doesn't support variable number of fields easily,
        # so we'll use aliases for each commit
        # Limit to reasonable batch size to avoid query complexity limits
        batch_size = min(len(commit_shas), 50)
        commit_shas = commit_shas[:batch_size]

        # Build query with aliases for each commit and corresponding variables
        commit_fields: List[str] = []
        variable_definitions: List[str] = ["$owner: String!", "$name: String!"]
        variables: Dict[str, Any] = {"owner": owner, "name": name}

        for i, sha in enumerate(commit_shas):
            alias = f"commit{i}"
            sha_var_name = f"sha{i}"
            variable_definitions.append(f"${sha_var_name}: GitObjectID!")
            variables[sha_var_name] = sha
            commit_fields.append(
                f"{alias}: object(oid: ${sha_var_name}) {{ "
                f"... on Commit {{ oid committedDate author {{ name email }} }} }}"
            )

        query = f"""
        query({', '.join(variable_definitions)}) {{
          repository(owner: $owner, name: $name) {{
            {' '.join(commit_fields)}
          }}
        }}
        """

        logger.debug(f"Fetching metadata for {len(commit_shas)} commits via GraphQL")
        result = self.query(query, variables)
        repo_data = result.get("repository", {})

        # Parse results back into a dict
        commits_metadata: Dict[str, Dict[str, Any]] = {}
        for i, sha in enumerate(commit_shas):
            alias = f"commit{i}"
            commit_data = repo_data.get(alias)
            if commit_data and commit_data.get("oid"):
                commits_metadata[sha] = commit_data

        logger.debug(f"Retrieved metadata for {len(commits_metadata)} commits")
        return commits_metadata

    def search_issues_and_pulls(
        self,
        owner: str,
        name: str,
        start_date: str,
        end_date: str,
        max_items: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search for issues and PRs closed in a date range.

        Args:
            owner: Repository owner.
            name: Repository name.
            start_date: Start date in ISO 8601 format.
            end_date: End date in ISO 8601 format.
            max_items: Maximum items to return.

        Returns:
            List of issue/PR dicts with number, title, author, labels, etc.
        """
        query = """
        query($queryStr: String!, $maxItems: Int!) {
          search(query: $queryStr, type: ISSUE, first: $maxItems) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              ... on Issue {
                number
                title
                author {
                  login
                }
                labels(first: 10) {
                  nodes {
                    name
                  }
                }
                closedAt
                url
              }
              ... on PullRequest {
                number
                title
                author {
                  login
                }
                labels(first: 10) {
                  nodes {
                    name
                  }
                }
                closedAt
                url
                mergedAt
              }
            }
          }
        }
        """

        # Build search query string
        query_str = f"repo:{owner}/{name} is:closed closed:{start_date}..{end_date}"
        variables = {"queryStr": query_str, "maxItems": max_items}

        logger.debug(f"Searching issues/PRs via GraphQL: {query_str}")
        result = self.query(query, variables)
        search_data = result.get("search", {})

        items = []
        for node in search_data.get("nodes", []):
            if node:  # Skip None entries
                # Normalize labels
                labels = [
                    label["name"] for label in node.get("labels", {}).get("nodes", [])
                ]
                node["labels"] = labels

                # Add author login
                author = node.get("author", {})
                if author:
                    node["author_login"] = author.get("login")

                items.append(node)

        if search_data.get("pageInfo", {}).get("hasNextPage"):
            logger.warning(
                f"More than {max_items} issues/PRs found in range, "
                "some may be missing. Consider pagination."
            )

        logger.debug(f"Found {len(items)} issues/PRs via GraphQL")
        return items
