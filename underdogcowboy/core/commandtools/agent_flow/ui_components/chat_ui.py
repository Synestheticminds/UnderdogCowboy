import logging
import asyncio
import os
import json
import datetime
from typing import Tuple, Optional, Union

import re
import urllib.parse

import yaml

from rich.markdown import Markdown

from textual import on
from textual.binding import Binding
  
from textual.widgets import Static, TextArea
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual import events


from llm_response_markdown_renderer import LLMResponseRenderer
from llm_call_manager import LLMCallManager

# events
from events.chat_events import TextSubmitted, CommandSubmitted
from events.llm_events import LLMCallComplete, LLMCallError

# uc
from underdogcowboy.core.config_manager import LLMConfigManager
from underdogcowboy.core.timeline_editor import Timeline, CommandProcessor
from underdogcowboy.core.dialog_manager import AgentDialogManager
from underdogcowboy.core.model import ModelManager, ConfigurableModel

# uc interactive storage layer
from underdogcowboy.core.interactive_storage_layer.github import GithubAPI
from underdogcowboy.core.interactive_storage_layer.queue import TaskQueueManager

renderer = LLMResponseRenderer(
    mdformat_config_path=None,  
)

class ChatTextArea(TextArea):
    BINDINGS = [
        Binding("ctrl+s", "submit", "Submit", key_display="Ctrl+s", priority=True),
    ]

    def action_submit(self) -> None:
        """Handle the submit action."""
        message = self.text
        logging.info(f"Submitting message: {message}")
        self.text = ""
        if message.startswith('/'):  
            # This is a command  
            self.post_message(CommandSubmitted(message))  
        else:  
            # This is a regular message  
            self.post_message(TextSubmitted(message))

    def disable(self) -> None:
        self.disabled = True
        self.add_class("-disabled")

    def enable(self) -> None:
        self.disabled = False
        self.remove_class("-disabled")

class ChatUI(Static):

    def __init__(self, name: str, type: str, processor: Optional[Union[AgentDialogManager, CommandProcessor]] = None):
        super().__init__()
        
        self.processor: Optional[Union[AgentDialogManager, CommandProcessor]] = processor
        self.task_queue_manager = TaskQueueManager()
        self.da_name = name
        self.loading_message_id = None  
        self.is_scroll_at_bottom = True 
        self.chat_history_text = ""  

        self.hide_message_counter = 0
        if isinstance(self.processor,AgentDialogManager):
            # Get the active agent's CommandProcessor
            agent = self.processor.active_agent
            command_processor = self.processor.processors[agent]  # CommandProcessor instance
            # Now, use command_processor to access the history
            history_len = len(command_processor.timeline.history)
            self.hide_message_counter = history_len - 1
            self.app.clarity_processor = self.processor

        logging.info(f"Init of ChatUI")
            
        self.llm_call_manager = LLMCallManager()
        self.llm_call_manager.set_message_post_target(self) 

        self.load_folder_aliases()
            
    def disable_input(self) -> None:
        text_area = self.query_one("#chat-textarea", ChatTextArea)
        text_area.disable()

    def enable_input(self) -> None:
        text_area = self.query_one("#chat-textarea", ChatTextArea)    
        text_area.enable()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat-scroll", disabled=False):
            yield Static(id="chat-history")
        yield ChatTextArea("", id="chat-textarea")

    def on_mount(self) -> None:
        self.render_chat()

    def _get_model_and_timeline(self) -> Tuple[ConfigurableModel, Timeline]:
        self.model_id = self.app.get_current_llm_config()["model_id"]
        self.provider = self.app.get_current_llm_config()["provider"]
        model = ModelManager.initialize_model_with_id(self.provider, self.model_id)
        timeline = Timeline()
        return model, timeline

    def _load_processor(self, file_name: str, path: str) -> None:
        """General method to load a timeline and initialize the command processor."""
        try:
            # Retrieve the model and timeline
            self.model, self.timeline = self._get_model_and_timeline()
            
            # Attempt to load the timeline from the specified JSON file
            self.timeline.load(file_name, path=path)
            
            # Initialize the CommandProcessor with the loaded timeline and model
            self.processor = CommandProcessor(self.timeline, self.model)
            
            logging.info(f"Loaded command processor for file: {file_name}")
        
        except FileNotFoundError:
            # Handle the case where the JSON file does not exist
            error_message = f"File '{file_name}' not found in '{path}'. Please ensure the file exists."
            logging.error(error_message)
            self.notify(error_message)  # Notify the user about the missing file
        
        except json.JSONDecodeError as e:
            # Handle JSON decoding errors specifically
            error_message = f"Failed to parse '{file_name}': Corrupted JSON."
            logging.error(f"{error_message} Details: {str(e)}")
            self.notify(error_message)  # Notify the user about the corrupted JSON
        
        except Exception as e:
            # Handle any other unforeseen exceptions
            error_message = f"An unexpected error occurred while loading '{file_name}': {str(e)}"
            logging.error(error_message)
            self.notify(error_message)  # Notify the user about the unexpected error

    def format_messages_to_markdown(self) -> str:
        """Unpacks the messages and returns a markdown-formatted string."""
        markdown_output = ""
        file_message_pattern = re.compile(r'^File sent:\s*([^\n]+)')
        model_response_count = 0

        if isinstance(self.processor, CommandProcessor):
            messages = self.processor.timeline.history 
        elif isinstance(self.processor, AgentDialogManager):
            agent = self.processor.active_agent
            command_processor = self.processor.processors[agent]
            messages = command_processor.timeline.history
        else:
            logging.error("Unsupported processor type in ChatUI.")
            return markdown_output

        # Ensure hide_message_counter is within bounds
        if not hasattr(self, 'hide_message_counter'):
            self.hide_message_counter = 0
        self.hide_message_counter = max(0, min(self.hide_message_counter, len(messages)))

        # Filter messages after hide_message_counter
        filtered_messages = messages[self.hide_message_counter:]

        for message in filtered_messages:
            formatted_text = self._format_message_text(message.text, file_message_pattern)
            
            if message.role.lower() == 'model':
                model_response_count += 1
                offset = model_response_count - 1
                markdown_output += f"#### Assistant (Offset: {offset}):\n{formatted_text}\n\n"
            else:
                markdown_output += f"#### {message.role.capitalize()}:\n{formatted_text}\n\n"

        return markdown_output

    def _format_message_text(self, text: str, pattern: re.Pattern) -> str:
        """
        Formats the message text. If the message contains a file reference,
        it converts the file path into a clickable Markdown link.
        
        Parameters:
        - text: The original message text.
        - pattern: The compiled regex pattern to detect file messages.
        
        Returns:
        - The formatted text.
        """
        match = pattern.match(text)
        if match:
            file_path = match.group(1).strip()
            # URL-encode the file path to handle spaces and special characters
            file_path_encoded = urllib.parse.quote(file_path)
            # Extract the file name from the path
            file_name = file_path.split('/')[-1]
            # Create a Markdown link with the file path using file:// protocol
            markdown_link = f"[{file_name}](file://{file_path_encoded})"
            # Replace the original file path with the Markdown link
            formatted_text = f"File sent: {markdown_link}"
            return formatted_text
        else:
            return text

    def render_chat(self):
        """Render chat history in the UI when available."""
        # Update the chat history from the processor's history

        self.chat_history_text = self.format_messages_to_markdown()
        chat_widget = self.query_one("#chat-history")
        chat_widget.update(Markdown(self.chat_history_text))

        # Scroll to the bottom of the chat
        chat_scroll = self.query_one("#chat-scroll")
        self.scroll_to_end(chat_scroll)

    def scroll_to_end(self, scrollable: VerticalScroll):
        """Scroll to the bottom of the scrollable widget immediately."""
        scrollable.scroll_end(animate=False, force=True)

    @on(TextSubmitted)
    async def handle_text_submission(self, event: TextSubmitted):

        if not event.text.startswith('/'):
            """Handle the submission of the text."""
            self.disable_input()
        
            # Update the chat history
            self.chat_history_text += f"\n#### User:\n{event.text}"
            chat_widget = self.query_one("#chat-history", Static)
            chat_widget.update(Markdown(self.chat_history_text))

            # Scroll to the bottom
            scroll_widget = self.query_one("#chat-scroll", VerticalScroll)
            scroll_widget.scroll_end(animate=False, force=True)

            # Append a loading indicator
            self.chat_history_text += f"\n#### Assistant:\n..."
            chat_widget.update(Markdown(self.chat_history_text))
            scroll_widget.scroll_end(animate=False, force=True)

            # Store the length of the loading indicator
            self.loading_indicator_length = len("\n#### Assistant:\n...")

            # Prepare arguments
            llm_config = self.app.get_current_llm_config()
            input_id = self.loading_indicator_length

            # Submit the LLM call
            await self.llm_call_manager.submit_llm_call(
                self.llm_processing_function,
                llm_config,
                self.processor,
                input_id,
                event.text
            )

    def llm_processing_function(self, llm_config, processor, message_text):
        """Function that processes the LLM call."""
        try:
            if isinstance(processor, AgentDialogManager):
                agent = processor.active_agent
                command_processor = processor.processors[agent]
            elif isinstance(processor, CommandProcessor):
                command_processor = processor
            else:
                logging.error("Unsupported processor type in llm_processing_function.")
                raise ValueError("Unsupported processor type.")

            # Process the message with the CommandProcessor
            response = command_processor._process_message(message_text)
            return response
        except Exception as e:
            logging.error(f"Error processing LLM call: {e}")
            raise

    @on(LLMCallComplete)
    def handle_llm_call_complete(self, event: LLMCallComplete):
        """Handle successful LLM call completion."""
        # Remove the loading indicator from the chat history
        self.chat_history_text = self.chat_history_text[:-self.loading_indicator_length]

        # Append the assistant's response
        self.chat_history_text += f"\n#### Assistant:\n{event.result}"

        # Update the widget with the new content
        chat_widget = self.query_one("#chat-history", Static)
        chat_widget.update(Markdown(self.chat_history_text))

        # Scroll to the bottom
        scroll_widget = self.query_one("#chat-scroll", VerticalScroll)
        scroll_widget.scroll_end(animate=False, force=True)
        self.enable_input()

    @on(LLMCallError)
    def handle_llm_call_error(self, event: LLMCallError):
        """Handle errors from the LLM call."""
        # Remove the loading indicator from the chat history
        self.chat_history_text = self.chat_history_text[:-self.loading_indicator_length]

        # Append the error message
        error_message = f"An error occurred: {event.error}"
        self.chat_history_text += f"\n#### Assistant:\n{error_message}"

        # Update the widget with the new content
        chat_widget = self.query_one("#chat-history", Static)
        chat_widget.update(Markdown(self.chat_history_text))

        # Scroll to the bottom
        scroll_widget = self.query_one("#chat-scroll", VerticalScroll)
        scroll_widget.scroll_end(animate=False, force=True)
        self.enable_input()

    @on(CommandSubmitted)
    async def handle_command_submission(self, event: CommandSubmitted):
        command_parts = event.command.split()
        base_command = command_parts[0].lower()

        if base_command == '/markdown':
            offset = 0
            folder_alias = None
            if len(command_parts) > 1:
                try:
                    offset = int(command_parts[1])
                    if len(command_parts) > 2:
                        folder_alias = command_parts[2]
                except ValueError:
                    if len(command_parts) > 2:
                        offset = 0
                        folder_alias = command_parts[1]
                    else:
                        folder_alias = command_parts[1]
            self.save_response_to_markdown(offset, folder_alias)
        
        elif base_command == '/setalias':
            if len(command_parts) < 3:
                self.app.notify("Usage: /setalias [alias] [folder_path]")
            else:
                alias = command_parts[1]
                folder_path = ' '.join(command_parts[2:])
                self.set_folder_alias(alias, folder_path)
        
        elif base_command == "/issue":
            if len(command_parts) < 2:
                self.app.notify("Usage: /issue [repository_name]")
            else:
                repo_name = command_parts[1]
                github_api = await self.create_github_api()
                
                # Notify the user the issue is being processed
                self.app.notify(f"Creating issue for repository: {repo_name} in the background...")

                async def create_issue_task():
                    repositories = await github_api.get_repositories()
                    for repo in repositories:
                        if repo['name'] == repo_name:  # Assuming `repo` is a dictionary
                            # Add issue creation task to queue
                            self.task_queue_manager.add_task("create_issue", repo['full_name'], {
                                "title": "Bug Report",
                                "body": "Description of the bug.",
                                "labels": ["bug"]
                            })
                            await self.task_queue_manager.process_queue()
                            self.app.notify(f"Issue successfully created in repository: {repo_name}")
                            break
                    else:
                        self.app.notify(f"Repository '{repo_name}' not found.")

                # Schedule the async task
                asyncio.create_task(create_issue_task())
                
        elif base_command == 'summarize':
            # simple ADM call with current agents as a json text file to a summarize agent.
            # get response and place
            # in a markdown file that we save in a project/[session]/[agent_name][utc].md 

            # make summarize agent and place in meta folder of agents
            # from underdogcowboy import adm , summarize
            #adm | [summarize]
            #file_ref = # path via something like the agent_name?
            #question = f"file {file_ref} "
            #response = summarize >> question
            
            pass

        else:
            self.app.notify("Unknown command")

    async def create_github_api(self) -> GithubAPI:
        config_manager = LLMConfigManager()
        github_config = config_manager.get_github_config()
        api_key = github_config['api_key']
        return GithubAPI(api_key)

    def set_folder_alias(self, alias: str, folder_path: str):
        """Set a folder alias in the YAML file."""
        config_path = os.path.expanduser("~/.folder_aliases")
        
        # Ensure the directory for the YAML file exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        # Load existing aliases from the YAML file
        try:
            with open(config_path, 'r') as file:
                aliases = yaml.safe_load(file) or {}
        except Exception as e:
            self.app.notify(f"Error loading folder aliases: {str(e)}")
            return

        # Expand user path
        folder_path = os.path.expanduser(folder_path)

        # If the path is relative, use the export path as base
        if not os.path.isabs(folder_path):
            config_manager = LLMConfigManager()
            export_path = config_manager.get_general_config().get('message_export_path', '')
            folder_path = os.path.join(export_path, folder_path)

        # Check if the folder exists, if not, create it
        if not os.path.exists(folder_path):
            try:
                os.makedirs(folder_path)
                self.app.notify(f"Folder '{folder_path}' created successfully.")
            except Exception as e:
                self.app.notify(f"Error creating folder '{folder_path}': {str(e)}")
                return

        # Update the alias
        aliases[alias] = folder_path

        # Write back to the YAML file
        try:
            with open(config_path, 'w') as file:
                yaml.dump(aliases, file)
            
            # Update the current session's aliases dictionary
            self.folder_aliases = aliases
            self.app.notify(f"Alias '{alias}' set to '{folder_path}'")
        except Exception as e:
            self.app.notify(f"Error saving folder alias: {str(e)}")



    def save_response_to_markdown(self, offset=0, folder_alias=None):  
        
        config_manager = LLMConfigManager()  
        
        if folder_alias and folder_alias in self.folder_aliases:
            dialogs_dir = os.path.expanduser(self.folder_aliases[folder_alias])
        else:
            dialogs_dir = config_manager.get_general_config().get('message_export_path', '')
        
        os.makedirs(dialogs_dir, exist_ok=True)
                
        if isinstance(self.processor, CommandProcessor):  
            messages = self.processor.timeline.history  
        elif isinstance(self.processor, AgentDialogManager):  
            agent = self.processor.active_agent  
            command_processor = self.processor.processors[agent]  
            messages = command_processor.timeline.history  
        else:  
            self.app.notify("Error: Unsupported processor type")  
            return
        
        model_responses = [msg for msg in reversed(messages) if msg.role.lower() == 'model']
        
        if offset < 0 or offset >= len(model_responses):
            self.app.notify(f"Invalid offset. There are only {len(model_responses)} model responses.")
            return
        
        response_to_save = model_responses[offset].text if model_responses else None
        
        if response_to_save:  
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  
            filename = f"llm_response_{timestamp}_offset_{offset}.md"  
            file_path = os.path.join(dialogs_dir, filename)
            with open(file_path, 'w', encoding='utf-8') as f:  
                f.write(response_to_save)
            self.app.notify(f"Response (offset: {offset}) saved to {file_path}")  
        else:  
            self.app.notify(f"No assistant response found at offset {offset}")    
            

    def append_to_chat(self, text: str, role: str, move_to_bottom: bool = False) -> int:
        """Append a new message to the chat."""
        # Update the chat history text
        self.chat_history_text += f"\n#### {role}:\n{text}"

        # Update the widget with the new Markdown content
        chat_widget = self.query_one("#chat-history", Static)
        chat_widget.update(Markdown(self.chat_history_text))

        if move_to_bottom:
            scroll_widget = self.query_one("#chat-scroll", VerticalScroll)
            scroll_widget.scroll_end(animate=False, force=True)

        return len(self.chat_history_text)  # Return the length of the chat history as a simple ID
    
    def load_folder_aliases(self):
        config_path = os.path.expanduser("~/.folder_aliases")
        self.folder_aliases = {}

        # Ensure the directory exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        # If the file doesn't exist, create an empty one
        if not os.path.exists(config_path):
            with open(config_path, 'w') as file:
                yaml.dump({}, file)

        try:
            with open(config_path, 'r') as file:
                self.folder_aliases = yaml.safe_load(file) or {}
        except Exception as e:
            self.app.notify(f"Error loading folder aliases: {str(e)}")

class DialogChatUI(ChatUI):  

    BINDINGS =  [  
        Binding("ctrl+d", "save_dialog", "Save Dialog", key_display="Ctrl+D"),  
    ]

    def __init__(self, name: str, type: str, processor: Optional[Union[AgentDialogManager, CommandProcessor]] = None):
        super().__init__(name, type, processor)
        # important do here, it loads the processor, essential for logic deeper for display of the chat messages
        self.load_dialog(name)

    def action_save_dialog(self) -> None:  
        """Handle the save dialog action when Ctrl+D is pressed."""  
        logging.info("Saving dialog...")  
        self.save_dialog()

    def load_dialog(self, dialog_name):
        # Dialog specific
        dialog_name = f"{dialog_name}.json"
        config_manager: LLMConfigManager = LLMConfigManager()
        dialog_path: str = config_manager.get_general_config().get('dialog_save_path', '')

        self._load_processor(dialog_name, dialog_path)
        self.BINDINGS 

    def save_dialog(self):  
        logging.info("Executing save_dialog logic in DialogChatUI.")  
        name = str(self.da_name)  
        filename = f"{name}.json"  
          
        description = "Saved Dialog from ChatUI" 

        self.processor.save_timeline_without_prompt(filename, name=name, description=description)  
        self.app.notify(f"Dialog '{name}' saved successfully.")  

class AgentChatUI(ChatUI):  
    
    def __init__(self, name: str, type: str, processor: Optional[Union[AgentDialogManager, CommandProcessor]] = None):
        super().__init__(name, type, processor)
        # important do here, it loads the processor, essential for logic deeper for display of the chat messages
        self.load_agent(name)

    def load_agent(self, agent_name):
        # Agent specific
        agents_dir = os.path.expanduser("~/.underdogcowboy/agents")
        agent_file = f"{agent_name}.json"

        self._load_processor(agent_file, agents_dir)

    def save_agent(self):
        logging.info("Executing save_agent logic in ChatUI.")
        # Use the da_name as filename
        filename = f"{self.da_name}.json"
        
        # Optional: Provide a name and description or leave as None
        name = self.da_name  
        description = "Saved Agent from ChatUI" 

        # Call the new method to save without prompt
        self.processor.save_agent_without_prompt(filename, name=name, description=description)

        # Notify the user (if you have a method for this)
        self.app.notify(f"Agent '{self.da_name}' saved successfully.")

