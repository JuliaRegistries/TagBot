"""Tests for GraphQL client functionality."""

import pytest
from unittest.mock import Mock, patch
from github import GithubException
from tagbot.action.graphql import GraphQLClient


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
            {"data": {"repository": {"name": "test"}}}  # data
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
            {"errors": [{"message": "Field 'unknown' doesn't exist"}]}
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
                                "target": {"oid": "abc123"}  # Lightweight tag
                            },
                            {
                                "name": "v1.1.0",
                                "target": {
                                    # Annotated tag - has nested target
                                    "oid": "tag456",  # Tag object OID
                                    "target": {  # Nested target points to actual commit
                                        "oid": "commit789"  # Actual commit SHA
                                    }
                                }
                            }
                        ]
                    },
                    "releases": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {
                                "tagName": "v1.0.0",
                                "createdAt": "2024-01-01T00:00:00Z",
                                "tagCommit": {"oid": "abc123"}
                            }
                        ]
                    }
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)
        
        client = GraphQLClient(mock_gh)
        tags_dict, releases_list = client.fetch_tags_and_releases("owner", "repo")
        
        assert len(tags_dict) == 2
        assert tags_dict["v1.0.0"] == "abc123"  # Lightweight tag
        assert tags_dict["v1.1.0"] == "commit789"  # Annotated tag resolved to commit SHA
        
        assert len(releases_list) == 1
        assert releases_list[0]["tagName"] == "v1.0.0"

    def test_fetch_commits_metadata(self):
        """Test batch fetching commit metadata."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester
        
        # Mock GraphQL response with commit metadata
        mock_response = {
            "data": {
                "repository": {
                    "commit0": {
                        "oid": "abc123",
                        "committedDate": "2024-01-01T00:00:00Z",
                        "author": {"name": "John Doe", "email": "john@example.com"}
                    },
                    "commit1": {
                        "oid": "def456",
                        "committedDate": "2024-01-02T00:00:00Z",
                        "author": {"name": "Jane Doe", "email": "jane@example.com"}
                    }
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)
        
        client = GraphQLClient(mock_gh)
        metadata = client.fetch_commits_metadata("owner", "repo", ["abc123", "def456"])
        
        assert len(metadata) == 2
        assert metadata["abc123"]["oid"] == "abc123"
        assert metadata["def456"]["committedDate"] == "2024-01-02T00:00:00Z"

    def test_fetch_commits_metadata_empty_list(self):
        """Test fetch_commits_metadata returns empty dict for empty input."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester
        
        client = GraphQLClient(mock_gh)
        metadata = client.fetch_commits_metadata("owner", "repo", [])
        
        # Should return empty dict without making API call
        assert metadata == {}
        mock_requester.requestJsonAndCheck.assert_not_called()

    def test_search_issues_and_pulls(self):
        """Test searching issues and PRs by date range."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester
        
        # Mock GraphQL response with search results
        mock_response = {
            "data": {
                "search": {
                    "pageInfo": {"hasNextPage": False},
                    "nodes": [
                        {
                            "number": 123,
                            "title": "Fix bug",
                            "author": {"login": "user1"},
                            "labels": {"nodes": [{"name": "bug"}]},
                            "closedAt": "2024-01-01T00:00:00Z",
                            "url": "https://github.com/owner/repo/issues/123"
                        },
                        {
                            "number": 124,
                            "title": "Add feature",
                            "author": {"login": "user2"},
                            "labels": {"nodes": [{"name": "enhancement"}]},
                            "closedAt": "2024-01-02T00:00:00Z",
                            "url": "https://github.com/owner/repo/pull/124",
                            "mergedAt": "2024-01-02T00:00:00Z"
                        }
                    ]
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)
        
        client = GraphQLClient(mock_gh)
        items = client.search_issues_and_pulls(
            "owner", "repo", 
            "2024-01-01T00:00:00", "2024-01-03T00:00:00"
        )
        
        assert len(items) == 2
        assert items[0]["number"] == 123
        assert items[0]["labels"] == ["bug"]
        assert items[1]["number"] == 124
        assert items[1]["author_login"] == "user2"

    @patch("tagbot.action.graphql.logger")
    def test_fetch_tags_and_releases_pagination_warning_tags(self, mock_logger):
        """Test warning is logged when tags have more pages."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester
        
        # Mock response with hasNextPage=True for tags
        mock_response = {
            "data": {
                "repository": {
                    "refs": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor123"},
                        "nodes": [{"name": "v1.0.0", "target": {"oid": "abc123"}}]
                    },
                    "releases": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": []
                    }
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)
        
        client = GraphQLClient(mock_gh)
        tags_dict, _ = client.fetch_tags_and_releases("owner", "repo", max_items=100)
        
        # Verify warning was logged
        assert mock_logger.warning.called
        warning_message = mock_logger.warning.call_args[0][0]
        assert "more than 100 tags" in warning_message
        assert "pagination" in warning_message

    @patch("tagbot.action.graphql.logger")
    def test_fetch_tags_and_releases_pagination_warning_releases(self, mock_logger):
        """Test warning is logged when releases have more pages."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester
        
        # Mock response with hasNextPage=True for releases
        mock_response = {
            "data": {
                "repository": {
                    "refs": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [{"name": "v1.0.0", "target": {"oid": "abc123"}}]
                    },
                    "releases": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor456"},
                        "nodes": [{"tagName": "v1.0.0", "createdAt": "2024-01-01T00:00:00Z"}]
                    }
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)
        
        client = GraphQLClient(mock_gh)
        _, releases_list = client.fetch_tags_and_releases("owner", "repo", max_items=100)
        
        # Verify warning was logged
        assert mock_logger.warning.called
        warning_message = mock_logger.warning.call_args[0][0]
        assert "more than 100 releases" in warning_message
        assert "pagination" in warning_message

    @patch("tagbot.action.graphql.logger")
    def test_search_issues_pagination_warning(self, mock_logger):
        """Test warning is logged when search has more pages."""
        mock_gh = Mock()
        mock_requester = Mock()
        mock_gh._Github__requester = mock_requester
        
        # Mock response with hasNextPage=True
        mock_response = {
            "data": {
                "search": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor789"},
                    "nodes": [
                        {
                            "number": 123,
                            "title": "Test",
                            "author": {"login": "user1"},
                            "labels": {"nodes": []},
                            "closedAt": "2024-01-01T00:00:00Z",
                            "url": "https://github.com/owner/repo/issues/123"
                        }
                    ]
                }
            }
        }
        mock_requester.requestJsonAndCheck.return_value = ({}, mock_response)
        
        client = GraphQLClient(mock_gh)
        items = client.search_issues_and_pulls(
            "owner", "repo",
            "2024-01-01T00:00:00", "2024-01-03T00:00:00",
            max_items=100
        )
        
        # Verify warning was logged
        assert mock_logger.warning.called
        warning_message = mock_logger.warning.call_args[0][0]
        assert "More than 100 issues/PRs found" in warning_message
        assert "pagination" in warning_message

