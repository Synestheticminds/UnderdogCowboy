import json
from pathlib import Path
from getpass import getpass
import keyring

from typing import Any, Dict, List

from .tracing import TracingProxy


class LLMConfigManager:
    """
    A class for managing configurations for various Language Learning Models (LLMs).

    This class handles loading, saving, and retrieving credentials for different LLM providers.
    It also provides functionality to select a model from available options.
    """
    def __init__(self) -> None:
        """
        Initialize the LLMConfigManager.

        Sets up the configuration file path and loads existing configurations.
        Also defines the structure for different LLM models and their required credentials.
        """
        self.config_file: Path = Path.home() / '.underdogcowboy' / 'config.json'
        self.config: Dict[str, Any] = self.load_config()
        self.models: Dict[str, Dict[str, Dict[str, Any]]] = {
            'anthropic': {
                'api_key': {'question': 'Enter your Anthropic API key:', 'input_type': 'password'},
                'model_id': {'question': 'Enter the Anthropic model ID:', 'input_type': 'text', 'default': 'claude-3-5-sonnet-20240620'},
                'api_url': {'question': 'Enter the Anthropic API URL:', 'input_type': 'text', 'default': 'https://api.anthropic.com/v1/messages'},
                'anthropic_version': {'question': 'Enter the Anthropic API version:', 'input_type': 'text', 'default': '2023-06-01'}
            },
            'google-vertex': {
                'service_account': {'question': 'Enter the path to your Google service account JSON file:', 'input_type': 'file'},
                'project_id': {'question': 'Enter the project id from your google cloud configuration', 'input_type': 'text' },
                'location': {'question': 'Enter the location from your google cloud configuration', 'input_type': 'text', 'default': 'us-central1' },
                'model_id': {'question': 'Enter the model name (id from google LLM)', 'input_type': 'text', 'default': 'gemini-1.5-pro-preview-0514' }
            },
            'groq': {
                'api_key': {'question': 'Enter your Groq API key:', 'input_type': 'password'},
                'model_id': {'question': 'Enter the Groq model ID:', 'input_type': 'text', 'default': 'llama3-8b-8192'}
            }
        }
        self.general_config: Dict[str, Dict[str, Any]] = {
            'dialog_save_path': {'question': 'Enter the path to save dialogs:', 'input_type': 'path', 'default': str(Path.home() / 'llm_dialogs')},
            'message_export_path': {'question': 'Enter the path to export messages:', 'input_type': 'path', 'default': str(Path.home() / 'llm_exports')}
        }
        self.tracing_config: Dict[str, Dict[str, Any]] = {
            'use_langsmith': {'question': 'Use LangSmith for tracing? (yes/no):', 'input_type': 'boolean', 'default': 'no'},
            'langsmith_api_key': {'question': 'Enter your LangSmith API key:', 'input_type': 'password'},
        }

    def load_config(self) -> Dict[str, Any]:        
        """
        Load the configuration from the JSON file.

        Returns:
            dict: The loaded configuration, or an empty dictionary if the file doesn't exist.
        """
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}

    def save_config(self) -> None:
        """
        Save the current configuration to the JSON file.

        This method ensures that sensitive information (like API keys) is not stored directly in the file.
        Instead, it marks such information as "KEYRING_STORED" in the saved config.
        """        
        safe_config = self.config.copy()
        for model in safe_config:
            for prop, details in self.models.get(model, {}).items():
                if details.get('input_type') == 'password':
                    safe_config[model][prop] = "KEYRING_STORED"
        
        if 'tracing' in safe_config:
            for prop, details in self.tracing_config.items():
                if details.get('input_type') == 'password':
                    safe_config['tracing'][prop] = "KEYRING_STORED"
        

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(safe_config, f)
    
    def get_credentials(self, model: str) -> Dict[str, Any]:    
        """
        Retrieve or prompt for credentials for a specific model.

        If credentials are not already stored, this method will prompt the user to enter them.
        Sensitive information is stored securely using the keyring module.

        Args:
            model (str): The name of the model to get credentials for.

        Returns:
            dict: A dictionary containing the credentials for the specified model.
        """
        if model not in self.config or not self.config[model].get('configured', False):
            print(f"No stored credentials found for {model}. Please enter them now.")
            self.config[model] = {}
            for prop, details in self.models[model].items():
                if details['input_type'] == 'password':
                    value = getpass(details['question'])
                    keyring.set_password("underdogcowboy", f"{model}_{prop}", value)
                    # Don't store the password in the JSON config
                    self.config[model][prop] = "KEYRING_STORED"
                else:
                    value = input(f"{details['question']} (default: {details.get('default', 'N/A')}): ")
                    if not value and 'default' in details:
                        value = details['default']
                    self.config[model][prop] = value
            self.config[model]['configured'] = True
            self.save_config()

        credentials = {}
        for prop, details in self.models[model].items():
            if details['input_type'] == 'password':
                value = keyring.get_password("underdogcowboy", f"{model}_{prop}")
            else:
                value = self.config[model].get(prop)
            if not value and 'default' in details:
                value = details['default']
            credentials[prop] = value
        return credentials

    def get_general_config(self) -> Dict[str, Any]:
        """
        Retrieve or prompt for general configuration settings.

        If settings are not already stored, this method will prompt the user to enter them.

        Returns:
            dict: A dictionary containing the general configuration settings.
        """
        if 'general' not in self.config or not self.config['general'].get('configured', False):
            print("No stored general configuration found. Please enter them now.")
            self.config['general'] = {}
            for prop, details in self.general_config.items():
                value = input(f"{details['question']} (default: {details.get('default', 'N/A')}): ")
                if not value and 'default' in details:
                    value = details['default']
                self.config['general'][prop] = value
            self.config['general']['configured'] = True
            self.save_config()

        return {prop: self.config['general'].get(prop, details.get('default')) 
                for prop, details in self.general_config.items()}

    def update_general_config(self) -> None:
        """
        Update the general configuration settings.

        This method allows the user to update the dialog save path and message export path.
        """
        print("Updating general configuration settings:")
        for prop, details in self.general_config.items():
            current_value = self.config['general'].get(prop, details.get('default', 'N/A'))
            value = input(f"{details['question']} (current: {current_value}, press Enter to keep current): ")
            if value:
                self.config['general'][prop] = value
        self.save_config()
        print("General configuration updated successfully.")

    def select_model(self) -> str:
        """
        Prompt the user to select a model from the available options.

        This method displays a numbered list of available models and asks the user to choose one.

        Returns:
            str: The name of the selected model.

        Raises:
            ValueError: If the user enters an invalid input.
        """        
        print("Available models:")
        for i, model in enumerate(self.models.keys(), 1):
            print(f"{i}. {model}")
        
        while True:
            try:
                choice = int(input("Select a model (enter the number): "))
                if 1 <= choice <= len(self.models):
                    return list(self.models.keys())[choice - 1]
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number.")

    def get_available_models(self) -> List[str]:
        return sorted(self.models.keys())
    
    def update_model_property(self, model: str, property_name: str, new_value: Any) -> None:
        """
        Update a specific property for a given model.

        Args:
            model (str): The name of the model.
            property_name (str): The name of the property to update.
            new_value (str): The new value for the property.

        Raises:
            ValueError: If the model or property doesn't exist.
        """
        if model not in self.models:
            raise ValueError(f"Model '{model}' does not exist.")
        
        if property_name not in self.models[model]:
            raise ValueError(f"Property '{property_name}' does not exist for model '{model}'.")
        
        if self.models[model][property_name]['input_type'] == 'password':
            keyring.set_password("underdogcowboy", f"{model}_{property_name}", new_value)
            self.config[model][property_name] = "KEYRING_STORED"
        else:
            self.config[model][property_name] = new_value
        
        self.save_config()
        print(f"Updated {property_name} for {model}.")

    def remove_model_config(self, model: str) -> None:        
        """
        Remove the configuration for a specific model.

        Args:
            model (str): The name of the model to remove.

        Raises:
            ValueError: If the model doesn't exist in the configuration.
        """
        if model not in self.config:
            raise ValueError(f"Model '{model}' does not exist in the configuration.")
        
        # Remove from keyring
        for prop, details in self.models[model].items():
            if details['input_type'] == 'password':
                keyring.delete_password("underdogcowboy", f"{model}_{prop}")
        
        # Remove from config
        del self.config[model]
        self.save_config()
        print(f"Removed configuration for {model}.")

    def get_tracing_config(self) -> Dict[str, Any]:

        """
        Retrieve or prompt for tracing configuration settings.

        Returns:
            dict: A dictionary containing the tracing configuration settings.
        """
        if 'tracing' not in self.config or not self.config['tracing'].get('configured', False):
            print("No stored tracing configuration found. Please enter them now.")
            self.config['tracing'] = {}
            for prop, details in self.tracing_config.items():
                if details['input_type'] == 'boolean':
                    while True:
                        value = input(f"{details['question']} (default: {details.get('default', 'N/A')}): ").lower()
                        if value in ['yes', 'no', '']:
                            break
                        print("Please enter 'yes' or 'no'.")
                    value = 'yes' if value == 'yes' else 'no'
                elif details['input_type'] == 'password':
                    value = getpass(details['question'])
                    keyring.set_password("underdogcowboy", f"tracing_{prop}", value)
                    self.config['tracing'][prop] = "KEYRING_STORED"
                else:
                    value = input(f"{details['question']} (default: {details.get('default', 'N/A')}): ")
                if not value and 'default' in details:
                    value = details['default']
                if prop != 'langsmith_api_key':
                    self.config['tracing'][prop] = value
            self.config['tracing']['configured'] = True
            self.save_config()

        tracing_config = {}
        for prop, details in self.tracing_config.items():
            if details['input_type'] == 'password':
                value = keyring.get_password("underdogcowboy", f"tracing_{prop}")
            else:
                value = self.config['tracing'].get(prop)
            if not value and 'default' in details:
                value = details['default']
            tracing_config[prop] = value
        return tracing_config    
        
    def update_tracing_config(self) -> None:
        """
        Update the tracing configuration settings.

        This method allows the user to update the LangSmith tracing settings.
        """
        print("Updating tracing configuration settings:")
        for prop, details in self.tracing_config.items():
            if details['input_type'] == 'boolean':
                current_value = self.config['tracing'].get(prop, details.get('default', 'N/A'))
                while True:
                    value = input(f"{details['question']} (current: {current_value}, press Enter to keep current): ").lower()
                    if value in ['yes', 'no', '']:
                        break
                    print("Please enter 'yes' or 'no'.")
                if value:
                    self.config['tracing'][prop] = value
            elif details['input_type'] == 'password':
                value = getpass(f"{details['question']} (press Enter to keep current): ")
                if value:
                    keyring.set_password("underdogcowboy", f"tracing_{prop}", value)
                    self.config['tracing'][prop] = "KEYRING_STORED"
            else:
                current_value = self.config['tracing'].get(prop, details.get('default', 'N/A'))
                value = input(f"{details['question']} (current: {current_value}, press Enter to keep current): ")
                if value:
                    self.config['tracing'][prop] = value
        self.save_config()
        print("Tracing configuration updated successfully.")

    def get_tracing_proxy(self) -> 'TracingProxy':
        """
        Get a TracingProxy instance based on the current tracing configuration.

        Returns:
            TracingProxy: An instance of TracingProxy configured according to the current settings.
        """
        tracing_config = self.get_tracing_config()
        use_langsmith = tracing_config.get('use_langsmith', 'no').lower() == 'yes'
        api_key = tracing_config.get('langsmith_api_key', '')
          # Import your TracingProxy class
        return TracingProxy(use_langsmith=use_langsmith, api_key=api_key)