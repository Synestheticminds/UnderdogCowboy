import logging
import time
import json
from pathlib import Path
from typing import Dict, Any, List
import aiohttp

# uc
from underdogcowboy.core.config_manager import LLMConfigManager
from underdogcowboy.core.interactive_storage_layer.github import GithubAPI


def create_github_api() -> GithubAPI:
    config_manager = LLMConfigManager()
    github_config = config_manager.get_github_config()
    api_key = github_config['api_key']
    logging.info(f"Creating GitHub API object... {api_key}")
    return GithubAPI(api_key)


class TaskQueueManager:
    def __init__(self):
        self.queue_file = Path.home() / ".underdogcowboy" / "task_queue.json"
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_file.exists():
            with open(self.queue_file, 'w') as f:
                json.dump({"tasks": []}, f)

        # Task type to method mapping
        self.task_methods = {
            "create_issue": self._create_issue,
            # Add more task types as needed
        }

        self.github_api: GithubAPI = create_github_api()

    def add_task(self, task_type: str, repo: str, payload: Dict[str, Any]) -> None:
        """
        Add a task to the queue.
        """
        with open(self.queue_file, 'r') as f:
            queue = json.load(f)

        task = {
            "id": str(int(time.time() * 1000)),  # Unique ID based on timestamp
            "type": task_type,
            "repo": repo,
            "payload": payload,
            "status": "pending",
            "timestamp": time.time()
        }
        queue["tasks"].append(task)

        with open(self.queue_file, 'w') as f:
            json.dump(queue, f, indent=2)
        logging.info(f"Task {task['id']} added to queue.")

    async def process_queue(self) -> None:
        """
        Process pending tasks in the queue asynchronously.
        """
        logging.info("Processing task queue...")
        with open(self.queue_file, 'r') as f:
            queue = json.load(f)

        for task in queue["tasks"]:
            if task["status"] == "pending":
                try:
                    # Call the specific task method dynamically
                    task_method = self.task_methods.get(task["type"])
                    if not task_method:
                        raise ValueError(f"Unknown task type: {task['type']}")
                    await task_method(task)
                    task["status"] = "completed"
                except Exception as e:
                    logging.error(f"Task {task['id']} failed: {e}")
                    # Leave the status as pending for retries

        with open(self.queue_file, 'w') as f:
            json.dump(queue, f, indent=2)

    async def _create_issue(self, task: Dict[str, Any]) -> None:
        """
        Create an issue in the specified GitHub repository asynchronously.
        """
        repo = task["repo"]
        payload = task["payload"]

        api_key = self.github_api.api_key
        if not api_key or api_key == "KEYRING_STORED":
            raise ValueError("GitHub API key is missing or not configured.")

        url = f"https://api.github.com/repos/{repo}/issues"
        headers = {"Authorization": f"token {api_key}"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 201:
                    raise ValueError(f"Failed to create issue: {response.status} - {await response.text()}")

                response_data = await response.json()
                logging.info(f"Issue created successfully in {repo}: {response_data['html_url']}")

