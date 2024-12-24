import json
import os
import yaml

from pathlib import Path
from getpass import getpass
import keyring

from typing import Any, Dict, List

from .tracing import TracingProxy

# Model definitions
GROQ_MODELS = [
    {'id': 'gemma-7b-it', 'name': 'Gemma 7b'},
    {'id': 'gemma2-9b-it', 'name': 'Gemma 9b'},
    {'id': 'llama-3.1-70b-versatile', 'name': 'Llama3.1 70b'},
    {'id': 'llama-3.1-8b-instant', 'name': 'Llama3.1 8b'},
    {'id': 'llama-guard-3-8b', 'name': 'Llama Guard 3 8b'},
    {'id': 'llama3-70b-8192	', 'name': 'Llama3 70b'},
    {'id': 'llama3-8b-8192', 'name': 'Llama3 8b'},
    {'id': 'llama3-groq-70b-8192-tool-use-preview', 'name': 'Llama3 Groq 70b '},
    {'id': 'llama3-groq-8b-8192-tool-use-preview', 'name': 'Llama3 Groq 8b'},
    {'id': 'mixtral-8x7b-32768', 'name': 'Mixtral 8x7b'},
]

GROK_MODELS = [
    {'id': 'grok-beta', 'name': 'Grok Beta'} 
]

CLAUDE_MODELS = [
    {'id': 'claude-3-5-sonnet-20241022', 'name': 'Claude 3.5 Sonnet (Upgrade)'},
    {'id': 'claude-3-5-sonnet-20240620', 'name': 'Claude 3.5 Sonnet'},
    {'id': 'claude-3-opus-20240229', 'name': 'Claude 3 Opus'},
    {'id': 'claude-3-sonnet-20240229', 'name': 'Claude 3 Sonnet'},
    {'id': 'claude-3-haiku-20240307', 'name': 'Claude 3 Haiku'},
]



def load_config_yml() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), 'commandtools/agent_flow/config.yaml')

    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

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

        yml_config = load_config_yml()
        self.use_key_ring = yml_config['security']['use_key_ring']

        self.default_model_id = yml_config["llm"]["default_model_id"]
        
        self.config_file: Path = Path.home() / '.underdogcowboy' / 'config.json'
        self.config: Dict[str, Any] = self.load_config()
        self.models: Dict[str, Dict[str, Any]] = {
            'anthropic': {
                'api_key': {'question': 'Enter your Anthropic API key:', 'input_type': 'password'},
                'models':CLAUDE_MODELS,
                'api_url': {'question': 'Enter the Anthropic API URL:', 'input_type': 'text', 'default': 'https://api.anthropic.com/v1/messages'},
                'anthropic_version': {'question': 'Enter the Anthropic API version:', 'input_type': 'text', 'default': '2023-06-01'}
            },
            'google-vertex': {
                'service_account': {'question': 'Enter the path to your Google service account JSON file:', 'input_type': 'file'},
                'project_id': {'question': 'Enter the project id from your google cloud configuration', 'input_type': 'text' },
                'location': {'question': 'Enter the location from your google cloud configuration', 'input_type': 'text', 'default': 'us-central1' },
                'models': [
                    {'id': 'gemini-1.5-pro-preview-0514', 'name': 'Gemini 1.5 pro'}
                ]
            },
            'groq': {
                'api_key': {'question': 'Enter your Groq API key:', 'input_type': 'password'},
                'models':GROQ_MODELS
            },
            'grok': {
                'api_key': {'question': 'Enter your Grok API key:', 'input_type': 'password'},
                'models':GROK_MODELS
            }
        }
        self.general_config: Dict[str, Dict[str, Any]] = {
            'dialog_save_path': {'question': 'Enter the path to save dialogs:', 'input_type': 'path', 'default': str(Path.home() / 'llm_dialogs')},
            'message_export_path': {'question': 'Enter the path to export messages:', 'input_type': 'path', 'default': str(Path.home() / 'llm_exports')},
            'project_path': {'question': 'Enter the path your root project folder:', 'input_type': 'path', 'default': str(Path.home() / 'llm_projects')},
        }
        self.tracing_config: Dict[str, Dict[str, Any]] = {
            'use_langsmith': {'question': 'Use LangSmith for tracing? (yes/no):', 'input_type': 'boolean', 'default': 'no'},
            'langsmith_api_key': {'question': 'Enter your LangSmith API key:', 'input_type': 'password'},
        }

        # Add this to the __init__ method in the LLMConfigManager class
        self.interactive_storage_layer: Dict[str, Dict[str, Any]] = {
            'api_key': {
                'question': 'Enter your GitHub API key:',
                'input_type': 'password'
            }
        }


        self.migrate_config()
        self.get_github_config()
        self.get_general_config()  

    def get_github_config(self) -> Dict[str, Any]:
        """
        Retrieve or prompt for GitHub configuration settings.

        Returns:
            dict: A dictionary containing the GitHub configuration settings.
        """
        if 'github' not in self.config:
            self.config['github'] = {}

        updated = False

        # Check if the GitHub API key is stored securely
        if self.use_key_ring:
            api_key = keyring.get_password("underdogcowboy", "github_api_key")
            if not api_key:
                print("GitHub API key is missing. Please enter it now.")
                api_key = getpass("Enter your GitHub API key: ")
                keyring.set_password("underdogcowboy", "github_api_key", api_key)
                self.config['github']['api_key'] = "KEYRING_STORED"
                updated = True
        else:
            if 'api_key' not in self.config['github']:
                print("GitHub API key is missing. Please enter it now.")
                api_key = getpass("Enter your GitHub API key: ")
                self.config['github']['api_key'] = api_key
                updated = True

        if updated:
            self.save_config()

        return self.config['github']


    def get_provider_from_model(self, model_name: str) -> str:
        """
        Determine the provider from a given model name.

        Args:
            model_name (str): The name or ID of the model.

        Returns:
            str: The name of the provider for the given model.

        Raises:
            ValueError: If the model is not found in any provider's list.
        """
        # Check if the input is a tuple of (provider, model_id)
        if isinstance(model_name, tuple):
            provider, model_id = model_name
            # Verify that the provider and model_id exist in self.models
            if provider in self.models and any(model['id'] == model_id for model in self.models[provider]['models']):
                return provider

        # First, check if the model_name includes a provider prefix
        if ':' in model_name:
            provider, model_id = model_name.split(':', 1)
            if provider in self.models:
                # Verify that the model_id exists for this provider
                if any(model['id'] == model_id for model in self.models[provider]['models']):
                    return provider
        
        # If no provider prefix or the model wasn't found, search all providers
        for provider, details in self.models.items():
            for model in details['models']:
                if model['id'] == model_name:
                    return provider
        
        raise ValueError(f"Model '{model_name}' not found in any provider's list.")

    def load_config(self) -> Dict[str, Any]:        
        """
        Load the configuration from the JSON file.

        Returns:
            dict: The loaded configuration, or an empty dictionary if the file doesn't exist.
        """
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            return config
        return {}

    def swap_config_style() -> None:
        pass

    def save_config(self) -> None:
        """
        Save the current configuration to the JSON file.

        This method ensures that sensitive information (like API keys) is not stored directly in the file.
        Instead, it marks such information as "KEYRING_STORED" in the saved config.
        """        
        safe_config = self.config.copy()
        for provider, provider_config in safe_config.items():
            if provider in self.models:
                for prop, details in self.models[provider].items():
                    if prop != 'models' and isinstance(details, dict) and details.get('input_type') == 'password':
                        if prop in provider_config:
                            provider_config[prop] = "KEYRING_STORED"
        
        if 'tracing' in safe_config:
            for prop, details in self.tracing_config.items():
                if details.get('input_type') == 'password':
                    safe_config['tracing'][prop] = "KEYRING_STORED"

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(safe_config, f, indent=2)

    def get_credentials(self, provider: str) -> Dict[str, Any]:
        if ':' in provider:
            provider, model_id = provider.split(':', 1)
        else:
            model_id = None

        # Ensure config file exists and has basic structure
        if not self.config_file.exists():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            self.config = {}
            print(f"Creating new configuration file at {self.config_file}")

        # Initialize provider config if not exists or ensure all properties from model definition exist
        needs_config = False
        if provider not in self.config:
            self.config[provider] = {}
            needs_config = True
        else:
            # Check if any required properties from model definition are missing
            for prop, details in self.models[provider].items():
                if prop != 'models':
                    if details['input_type'] == 'password':
                        if not keyring.get_password("underdogcowboy", f"{provider}_{prop}"):
                            needs_config = True
                            break
                    elif prop not in self.config[provider]:
                        needs_config = True
                        break

        if needs_config:
            print(f"Configuring {provider} settings.")
            
            # Initialize provider config if not exists
            if provider not in self.config:
                self.config[provider] = {}

            # Handle API key first
            api_key_details = self.models[provider]['api_key']
            if 'api_key' not in self.config[provider] or not keyring.get_password("underdogcowboy", f"{provider}_api_key"):
                value = getpass(api_key_details['question'])
                keyring.set_password("underdogcowboy", f"{provider}_api_key", value)
                self.config[provider]['api_key'] = "KEYRING_STORED"

            # Set default values for other properties if not already set
            for prop, details in self.models[provider].items():
                if prop not in ['models', 'api_key'] and prop not in self.config[provider]:
                    if 'default' in details:
                        self.config[provider][prop] = details['default']

            # Set the model_id
            self.config[provider]['selected_model'] = model_id or self.default_model_id
            self.config[provider]['configured'] = True
            self.save_config()

        # Gather credentials including any defaults from model definition
        credentials = {}
        for prop, details in self.models[provider].items():
            if prop != 'models':
                if details['input_type'] == 'password':
                    value = keyring.get_password("underdogcowboy", f"{provider}_{prop}")
                else:
                    value = self.config[provider].get(prop)
                if not value and 'default' in details:
                    value = details['default']
                credentials[prop] = value

        credentials['model_id'] = model_id or self.config[provider]['selected_model']
        credentials['provider'] = provider
        return credentials        
    

    def get_general_config(self) -> Dict[str, Any]:
        """
        Retrieve or prompt for general configuration settings.

        Dynamically updates the configuration to include new properties
        that may not have been present in previous configurations.

        Returns:
            dict: A dictionary containing the general configuration settings.
        """
        if 'general' not in self.config:
            self.config['general'] = {}
        
        updated = False

        for prop, details in self.general_config.items():
            if prop not in self.config['general']:
                value = input(f"{details['question']} (default: {details.get('default', 'N/A')}): ")
                if not value and 'default' in details:
                    value = details['default']
                self.config['general'][prop] = value
                updated = True

        if updated:
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

    def select_model(self) -> tuple[str, str]:
        print("Available providers:")
        for i, provider in enumerate(self.models.keys(), 1):
            print(f"{i}. {provider}")
        
        while True:
            try:
                choice = int(input("Select a provider (enter the number): "))
                if 1 <= choice <= len(self.models):
                    selected_provider = list(self.models.keys())[choice - 1]
                    break
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number.")

        print(f"\nAvailable models for {selected_provider}:")
        for i, model in enumerate(self.models[selected_provider]['models'], 1):
            print(f"{i}. {model['name']} ({model['id']})")
        
        while True:
            try:
                choice = int(input("Select a model (enter the number): "))
                if 1 <= choice <= len(self.models[selected_provider]['models']):
                    selected_model = self.models[selected_provider]['models'][choice - 1]
                    self.config[selected_provider]['selected_model'] = selected_model['id']
                    # self.save_config()
                    return selected_provider, selected_model['id']
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number.")


    def get_available_models(self) -> List[str]:
        available_models = []
        for provider, details in self.models.items():
            for model in details['models']:
                available_models.append(f"{provider}:{model['id']}")
        return sorted(available_models)

    def update_model_property(self, provider_model: str, property_name: str, new_value: Any) -> None:
        if ':' in provider_model:
            provider, model_id = provider_model.split(':', 1)
        else:
            provider = provider_model
            model_id = None

        if provider not in self.models:
            raise ValueError(f"Provider '{provider}' does not exist.")
        
        if property_name not in self.models[provider] and property_name != 'selected_model':
            raise ValueError(f"Property '{property_name}' does not exist for provider '{provider}'.")
        
        if property_name == 'selected_model':
            available_models = [model['id'] for model in self.models[provider]['models']]
            if new_value not in available_models:
                raise ValueError(f"Model '{new_value}' is not available for provider '{provider}'.")
            self.config[provider]['selected_model'] = new_value
        elif self.models[provider][property_name]['input_type'] == 'password':
            keyring.set_password("underdogcowboy", f"{provider}_{property_name}", new_value)
            self.config[provider][property_name] = "KEYRING_STORED"
        else:
            self.config[provider][property_name] = new_value
        
        self.save_config()
        print(f"Updated {property_name} for {provider_model}.")        

    def remove_provider_config(self, provider: str) -> None:
        if provider not in self.config:
            raise ValueError(f"Provider '{provider}' does not exist in the configuration.")
        
        # Remove from keyring
        for prop, details in self.models[provider].items():
            if prop != 'models' and details['input_type'] == 'password':
                keyring.delete_password("underdogcowboy", f"{provider}_{prop}")
        
        # Remove from config
        del self.config[provider]
        self.save_config()
        print(f"Removed configuration for {provider}.")

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
    
    def migrate_config(self) -> None:
        """
        Migrate existing configuration to the new structure with multiple models per provider.
        """
        if not self.config:
            return  # No existing config to migrate

        migrated = False
        for provider, config in self.config.items():
            if provider not in self.models:
                continue  # Skip unknown providers

            if 'model_id' in config:
                # This is an old-style config that needs migration
                old_model_id = config['model_id']
                
                # Find the corresponding model in the new structure
                matching_model = next((model for model in self.models[provider]['models'] 
                                    if model['id'] == old_model_id), None)
                
                if matching_model:
                    # Update to new structure
                    config['selected_model'] = matching_model['id']
                    del config['model_id']
                    migrated = True
                else:
                    # If the old model doesn't exist in the new structure, 
                    # select the first available model as default
                    config['selected_model'] = self.models[provider]['models'][0]['id']
                    del config['model_id']
                    migrated = True
                    print(f"Warning: Previously selected model '{old_model_id}' for {provider} "
                        f"is no longer available. Default model '{config['selected_model']}' "
                        "has been selected.")

        if migrated:
            self.save_config()
            print("Configuration has been migrated to the new structure.") 