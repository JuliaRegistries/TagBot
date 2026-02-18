"""Tests for GraphQL client functionality."""

import pytest
from unittest.mock import Mock, patch
from github import GithubException
from tagbot.action.graphql import GraphQLClient, GraphQLTruncationError


class TestGraphQLClient:
    """Test GraphQL client operations."""

    def test_query_success(self):
        """Test successful GraphQL query execution."""
        # Create mock GitHub client
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester

        # Mock successful response
        mock_requester.requestJsonAndCheck.return_value = (
            {},  # headers
            {"data": {"repository": {"name": "test"}}},  # data
        )

        client = GraphQLClient(mock_gh)
        result = client.query("query { repository { name } }")

        assert result == {"repository": {"name": "test"}}
        mock_requester.requestJsonAndCheck.assert_called_once()

    def test_query_with_errors(self):
        """Test GraphQL query with errors."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester

        # Mock error response
        mock_requester.requestJsonAndCheck.return_value = (
            {},
            {"errors": [{"message": "Field 'unknown' doesn't exist"}]},
        )

        client = GraphQLClient(mock_gh)

        with pytest.raises(GithubException) as exc_info:
            client.query("query { unknown }")

        assert "GraphQL errors" in str(exc_info.value)
        assert "Field 'unknown' doesn't exist" in str(exc_info.value)

    def test_fetch_tags_and_releases(self):
        """Test fetching tags and releases together."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester

        # Mock GraphQL response with tags and releases
        # Include both lightweight tags (direct commit) and annotated tags
        mock_response = {
            "data": {
                "repository": {
                    "refs": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {
                                "name": "v1.0.0",
                                "target": {"oid": "abc123"},  # Lightweight tag
                            },
                            {
                                "name": "v1.1.0",
                                "target": {
                                    # Annotated tag - has nested target
                                    "oid": "tag456",  # Tag object OID
                                    "target": {  # Nested target points to actual commit
                                        "oid": "commit789"  # Actual commit SHA
                                    },
                                },
                            },
                        ],
                    },
                    "releases": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {
                                "tagName": "v1.0.0",
                                "createdAt": "2024-01-01T00:00:00Z",
                                "tagCommit": {"oid": "abc123"},
                            }
                        ],
                    },
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)

        client = GraphQLClient(mock_gh)
        tags_dict, releases_list = client.fetch_tags_and_releases("owner", "repo")

        assert len(tags_dict) == 2
        assert tags_dict["v1.0.0"] == "abc123"  # Lightweight tag
        assert (
            tags_dict["v1.1.0"] == "commit789"
        )  # Annotated tag resolved to commit SHA

        assert len(releases_list) == 1
        assert releases_list[0]["tagName"] == "v1.0.0"

    @patch("tagbot.action.graphql.logger")
    def test_fetch_tags_and_releases_pagination_exception_tags(self, mock_logger):
        """Test exception is raised when tags have more pages."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester

        # Mock response with hasNextPage=True for tags
        mock_response = {
            "data": {
                "repository": {
                    "refs": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor123"},
                        "nodes": [{"name": "v1.0.0", "target": {"oid": "abc123"}}],
                    },
                    "releases": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)

        client = GraphQLClient(mock_gh)

        with pytest.raises(GraphQLTruncationError) as exc_info:
            client.fetch_tags_and_releases("owner", "repo", max_items=100)

        assert "more than 100 tags" in str(exc_info.value)
        assert "GraphQL cannot fetch all data" in str(exc_info.value)
