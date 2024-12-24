
import time
import requests
import json
from pathlib import Path
from typing import Dict, Any, List

import aiofiles
import aiohttp


class GithubAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.github_cache_file = Path.home() / '.underdogcowboy' / 'github_cache.json'


    async def get_repositories(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch the list of GitHub repositories with adaptive caching (async version).

        Args:
            force_refresh (bool): If True, bypass the cache and fetch fresh data.

        Returns:
            List[Dict[str, Any]]: List of repositories.
        """
        # Allow debugging to override the cache via environment variable
        force_refresh = True 

        # Define base cache expiration (e.g., 30 minutes by default)
        base_cache_ttl = 30 * 60  # 30 minutes in seconds
        burst_cache_ttl = 5 * 60  # Shorter TTL during active use (5 minutes)
        idle_cache_ttl = 60 * 60  # Longer TTL during idle periods (1 hour)
        current_time = time.time()

        # Load cache and user activity state
        if self.github_cache_file.exists():
            async with aiofiles.open(self.github_cache_file, 'r') as f:
                cache = json.loads(await f.read())
        else:
            cache = {"repos": [], "last_updated": 0, "last_active": 0}

        # Determine cache TTL based on user activity
        if current_time - cache.get("last_active", 0) < burst_cache_ttl:
            cache_ttl = burst_cache_ttl
        elif current_time - cache.get("last_active", 0) > idle_cache_ttl:
            cache_ttl = idle_cache_ttl
        else:
            cache_ttl = base_cache_ttl

        # Check cache validity
        if not force_refresh and cache["last_updated"] and (current_time - cache["last_updated"] < cache_ttl):
            print("Using cached GitHub repositories.")
            return cache["repos"]

        # Fetch repositories from GitHub API
        print("Fetching repositories from GitHub API...")
        headers = {"Authorization": f"token {self.api_key}"}

        async with aiohttp.ClientSession() as session:
            org = 'Synestheticminds'
            url = f"https://api.github.com/orgs/{org}/repos"
            # url = "https://api.github.com/user/repos"
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise ValueError(f"Failed to fetch repositories: {response.status} - {await response.text()}")

                repos = await response.json()

        # Update cache with repositories and user activity
        cache = {
            "repos": repos,
            "last_updated": current_time,
            "last_active": current_time
        }

        self.github_cache_file.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(self.github_cache_file, 'w') as f:
            await f.write(json.dumps(cache, indent=2))

        return repos



    def get_open_issues(self, repo_owner, repo_name):
        url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/issues"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            issues = response.json()
            open_issues = [issue for issue in issues if issue.get('state') == 'open']
            return open_issues
        else:
            print(f"Failed to fetch issues: {response.status_code}")
            return []

    def comment_on_issue(self, repo_owner, repo_name, issue_number, comment):
        url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/issues/{issue_number}/comments"
        data = {"body": comment}
        response = requests.post(url, headers=self.headers, json=data)
        if response.status_code == 201:
            print(f"Successfully commented on issue #{issue_number}")
        else:
            print(f"Failed to comment on issue #{issue_number}: {response.status_code}, {response.text}")

    def create_issue(self, repo_owner, repo_name, title, body):
        url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/issues"
        data = {
            "title": title,
            "body": body,
            "assignees": [self.username]
        }
        response = requests.post(url, headers=self.headers, json=data)
        if response.status_code == 201:
            print(f"Successfully created issue '{title}'")
            return response.json()
        else:
            print(f"Failed to create issue '{title}': {response.status_code}, {response.text}")
            return None

    def list_labels(self, repo_owner, repo_name):
        url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/labels"
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            labels = response.json()
            return labels
        else:
            print(f"Failed to fetch labels: {response.status_code}")
            return []

    def add_labels_to_issue(self, repo_owner, repo_name, issue_number, labels):
        url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/issues/{issue_number}/labels"
        data = {"labels": labels}
        response = requests.post(url, headers=self.headers, json=data)
        if response.status_code == 200:
            print(f"Successfully added labels to issue #{issue_number}")
        else:
            print(f"Failed to add labels to issue #{issue_number}: {response.status_code}, {response.text}")

    def remove_label_from_issue(self, repo_owner, repo_name, issue_number, label):
        url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/issues/{issue_number}/labels/{label}"
        response = requests.delete(url, headers=self.headers)
        if response.status_code == 200:
            print(f"Successfully removed label '{label}' from issue #{issue_number}")
        else:
            print(f"Failed to remove label '{label}' from issue #{issue_number}: {response.status_code}, {response.text}")

    def get_projects(self, repo_owner, repo_name):
        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            projectsV2(first: 20) {
              nodes {
                id
                title
                shortDescription
                url
                closed
                items(first: 10) {
                  nodes {
                    id
                    type
                    fieldValues(first: 10) {
                      nodes {
                        ... on ProjectV2ItemFieldTextValue {
                          text
                          field {
                            ... on ProjectV2FieldCommon {
                              name
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {"owner": repo_owner, "name": repo_name}
        response = requests.post(self.graphql_url, headers=self.headers, json={"query": query, "variables": variables})
        if response.status_code == 200:
            result = response.json()
            if "errors" in result:
                print(f"GraphQL Errors: {result['errors']}")
                return []
            return result["data"]["repository"]["projectsV2"]["nodes"]
        else:
            print(f"Failed to fetch projects: {response.status_code}, {response.text}")
            return []

    def create_project(self, project_name, columns):
        mutation = """
        mutation($ownerId: ID!, $projectName: String!) {
          createProjectV2(input: {ownerId: $ownerId, title: $projectName}) {
            projectV2 {
              id
              title
              url
            }
          }
        }
        """
        variables = {
            "ownerId": self.owner_id,
            "projectName": project_name
        }
        response = requests.post(
            self.graphql_url,
            headers=self.headers,
            json={"query": mutation, "variables": variables}
        )
        if response.status_code == 200:
            result = response.json()
            if "errors" in result:
                print(f"GraphQL Errors: {result['errors']}")
                print(f"Full Response: {result}")  # For debugging
                return None
            project = result["data"]["createProjectV2"]["projectV2"]
            print(f"Successfully created project '{project_name}' with URL: {project['url']}")
            project_id = project["id"]
            print(f"Project ID: {project_id}")  # Debugging information

            # Add columns (fields) to the project using Project V2 mutation
            for column in columns:
                self.add_column_to_project_v2(project_id, column)

            return project
        else:
            print(f"Failed to create project: {response.status_code}, {response.text}")
            return None

    def add_column_to_project_v2(self, project_id, column_name):
        mutation = """
        mutation($projectId: ID!, $input: ProjectV2CreateFieldInput!) {
          projectV2CreateField(projectId: $projectId, input: $input) {
            projectV2Field {
              id
              name
              dataType
            }
          }
        }
        """
        variables = {
            "projectId": project_id,
            "input": {
                "name": column_name,
                "dataType": "SINGLE_SELECT"  # Adjust the dataType as needed
            }
        }
        response = requests.post(
            self.graphql_url,
            headers=self.headers,
            json={"query": mutation, "variables": variables}
        )
        if response.status_code == 200:
            result = response.json()
            if "errors" in result:
                print(f"GraphQL Errors: {result['errors']}")
                print(f"Full Response: {result}")  # For debugging
                return None
            field = result["data"]["projectV2CreateField"]["projectV2Field"]
            print(f"Successfully added field '{column_name}' to project")
            return field
        else:
            print(f"Failed to add field '{column_name}' to project: {response.status_code}, {response.text}")
            return None
