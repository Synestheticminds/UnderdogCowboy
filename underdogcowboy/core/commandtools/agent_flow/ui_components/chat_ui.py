import logging
import os
import json
from typing import Tuple, Optional, Union

import re
import urllib.parse


from rich.markdown import Markdown

from textual import on
from textual.binding import Binding
  
from textual.widgets import Static, TextArea, Button
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual import events


from llm_response_markdown_renderer import LLMResponseRenderer
from llm_call_manager import LLMCallManager

# events
from events.chat_events import TextSubmitted
from events.llm_events import LLMCallComplete, LLMCallError
from events.action_events import ActionSelected

# uc
from underdogcowboy.core.config_manager import LLMConfigManager
from underdogcowboy.core.timeline_editor import Timeline, CommandProcessor
from underdogcowboy.core.dialog_manager import AgentDialogManager
from underdogcowboy.core.model import ModelManager, ConfigurableModel

renderer = LLMResponseRenderer(
    mdformat_config_path=None,  # Provide path if you have a custom config
)

class ChatTextArea(TextArea):
    BINDINGS = [
        Binding("ctrl+s", "submit", "Submit", key_display="Ctrl+s", priority=True),
    ]

    def action_submit(self) -> None:
        """Handle the submit action when Shift+Enter is pressed."""
        message = self.text
        logging.info(f"Submitting message: {message}")
        self.text = ""
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

        # TODO: Hard Coded default provider.
        model = ModelManager.initialize_model_with_id("anthropic", self.model_id)
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
        
        # Regular expression to detect file messages
        # file_message_pattern = re.compile(r'^File sent:\s*(.+)$')
        file_message_pattern = re.compile(r'^File sent:\s*([^\n]+)')

        
        if isinstance(self.processor, CommandProcessor):
            messages = self.processor.timeline.history 
            for message in messages:
                formatted_text = self._format_message_text(message.text, file_message_pattern)
                markdown_output += f"#### {message.role.capitalize()}:\n{formatted_text}\n\n"
        
        elif isinstance(self.processor, AgentDialogManager):
            # Get the active agent's CommandProcessor
            agent = self.processor.active_agent
            command_processor = self.processor.processors[agent]  # CommandProcessor instance
            
            # Access the message history
            messages = command_processor.timeline.history
            
            # Ensure hide_message_counter is within the bounds
            if not hasattr(self, 'hide_message_counter'):
                self.hide_message_counter = 0  # Default to 0 if not set
            
            if self.hide_message_counter < 0:
                self.hide_message_counter = 0  # Prevent negative indices
            
            if self.hide_message_counter > len(messages):
                self.hide_message_counter = len(messages)  # Cap at the list length
            
            # Filter messages after hide_message_counter
            filtered_messages = messages[self.hide_message_counter:]
            
            # Update hide_message_counter to current length to avoid reprocessing
            self.hide_message_counter += len(filtered_messages)
            
            for message in filtered_messages:
                formatted_text = self._format_message_text(message.text, file_message_pattern)
                markdown_output += f"#### {message.role.capitalize()}:\n{formatted_text}\n\n"
        
        else:
            logging.error("Unsupported processor type in ChatUI.")
        
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

    
class DialogChatUI(ChatUI):  

    BINDINGS = ChatUI.BINDINGS + [  
        Binding("ctrl+d", "save_dialog", "Save Dialog", key_display="Ctrl+D"),  
    ]

    def __init__(self, name: str, type: str, processor: Optional[Union[AgentDialogManager, CommandProcessor]] = None):
        super().__init__(name, type, processor)
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
        filename = f"{self.da_name}.json"  
          
        name = self.da_name.plain  
        description = "Saved Dialog from ChatUI" 

        self.processor.save_timeline_without_prompt(filename, name=name, description=description)  
        self.app.notify(f"Dialog '{self.da_name}' saved successfully.")  

class AgentChatUI(ChatUI):  
    
    def __init__(self, name: str, type: str, processor: Optional[Union[AgentDialogManager, CommandProcessor]] = None):
        super().__init__(name, type, processor)
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

