import logging
import os
import json

from typing import Tuple, Union

from textual import on
from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Vertical, Horizontal
from textual.widgets import Label, Header, Footer, Collapsible
from textual.css.query import NoMatches

from uccli import StateMachine

# Storage Interface and SessionManager
from session_manager import SessionManager

# UI Components
from ui_factory import UIFactory
from ui_components.dynamic_container import DynamicContainer
from ui_components.state_button_grid_ui import StateButtonGrid
from ui_components.state_info_ui import StateInfo
from ui_components.center_content_ui import CenterContent
from ui_components.chat_ui import ChatUI
# from ui_components.left_side_ui import LeftSideContainer

from ui_components.load_agent_ui import LoadAgentUI
from ui_components.new_agent_ui import NewAgentUI
from ui_components.load_dialog_ui  import LoadDialogUI
from ui_components.new_dialog_ui import NewDialogUI

# Events
from events.button_events import UIButtonPressed
from events.agent_events import AgentSelected, NewAgentCreated, LoadAgent, AgentLoaded
from events.dialog_events import DialogSelected, NewDialogCreated, LoadDialog, DialogLoaded
from events.action_events import ActionSelected

# Screens
from screens.session_screen import SessionScreen

# State Machines
from state_machines.timeline_editor_state_machine import create_timeline_editor_state_machine

# uc
from underdogcowboy.core.config_manager import LLMConfigManager 
from underdogcowboy.core.timeline_editor import Timeline, CommandProcessor
from underdogcowboy.core.model import ModelManager, ConfigurableModel

""""
Under development, the use and none use of SessionScreen.
SessionScreen

"""

class TimeLineEditorScreen(SessionScreen):
    """A screen for the timeline editor."""

    # CSS_PATH = "../state_machine_app.css"

    def __init__(self,
                 state_machine: StateMachine = None,
                 session_manager: SessionManager = None,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = "Timeline Editor"
        self.state_machine = state_machine or create_timeline_editor_state_machine()
        self.session_manager = session_manager
        self.ui_factory = UIFactory(self)
        self.screen_name = "TimeLineEditorScreen"
        self.config_manager = LLMConfigManager()
        self._pending_session_manager = None
        self.timeline = None
        self.processor = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="agent-centre", classes="dynamic-spacer"):
            yield DynamicContainer(id="center-dynamic-container-timeline-editor", classes="center-dynamic-spacer")        

        with Vertical(id="app-layout"):
            with Collapsible(title="Task Panel", id="state-info-collapsible", collapsed=False):
                yield StateInfo(id="state-info")
                yield StateButtonGrid(self.state_machine, id="button-grid", state_machine_active_on_mount=True)  
                
        yield Footer(id="footer", name="footer")

    def on_mount(self) -> None:
        logging.info("TimeLineEditorScreen on_mount called")
        state_info = self.query_one("#state-info", StateInfo)
        state_info.update_state_info(self.state_machine, "")
        self.update_header()

        # Apply pending session manager after widgets are ready
        if self._pending_session_manager:
            session_manager = self._pending_session_manager
            self._pending_session_manager = None
            self.call_later(self.set_session_manager, session_manager)

    def set_session_manager(self, new_session_manager: SessionManager):
        self.session_manager = new_session_manager
        if self.is_mounted:
            self.call_later(self.update_ui_after_session_load)
        else:
            self._pending_session_manager = new_session_manager


    def update_header(self, session_name=None, agent_name=None):
        if not session_name:
            session_name = self.session_manager.current_session_name
        if not agent_name:
            agent_name = "Timeline Editor"
        self.sub_title = f"{agent_name}"
        if session_name:
            self.sub_title += f" - Active Session: {session_name}"
        self.refresh(layout=True)

    on(DialogSelected)
    def on_dialog_selected(self, event: DialogSelected):
        self.current_dialog = event.dialog_name
        self.notify(f"Loaded Dialog: {event.dialog_name}")
        dynamic_container = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
        dynamic_container.clear_content()
        self.load_chat_ui(self.current_dialog,"dailog")
        #self.post_message(LoadDialog(self.current_dialog))
    
    on(AgentSelected)
    def on_agent_selected(self, event: AgentSelected):
        self.current_agent = event.agent_name.plain
        self.agent_name_plain = event.agent_name.plain
        self.notify(f"Loaded Agent: {event.agent_name.plain}")
        dynamic_container = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
        dynamic_container.clear_content()
        
        #self.post_message(LoadAgent( self.agent_name_plain))
        # Update header with current agent and session (if available)
        self.update_header(agent_name=event.agent_name.plain)
        self.load_chat_ui(self.agent_name_plain, "agent")

    def load_chat_ui(self, name: str, type: str):
        id = 'chat-gui'
        try:
            # Use the UI factory to get the corresponding UI class and action based on the id
            ui_class, action = self.ui_factory.ui_factory(id)

            # Load the UI component if the factory returns one
            if ui_class:
                ui_instance = ui_class(name=name,type=type)
                dynamic_container = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
                dynamic_container.load_content(ui_instance)

            # Execute the action if provided
            if action:
                action()

        except ValueError as e:
            logging.error(f"Error: {e}")
    
    @on(UIButtonPressed)
    def handle_event_and_load_ui(self, event: UIButtonPressed) -> None:
        # Determine the appropriate id based on the event type
        logging.debug(f"Handler 'handle_event_and_load_ui' invoked with button_id: {event.button_id}")
        button_id = event.button_id
       
        dynamic_container = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
        dynamic_container.clear_content()

        try:
            # Use the UI factory to get the corresponding UI class and action based on the id
            ui_class, action = self.ui_factory.ui_factory(button_id)

            # Load the UI component if the factory returns one
            if ui_class:
                if button_id == "load-session" and not self.session_manager.list_sessions():
                    self.notify("No sessions available. Create a new session first.", severity="warning")
                else:
                    ui_instance = ui_class()
                    dynamic_container.load_content(ui_instance)

            # Execute the action if provided
            if action:
                action()

        except ValueError as e:
            logging.error(f"Error: {e}")


    def update_ui_after_session_load(self):
        try:
            dynamic_container = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
            dynamic_container.clear_content()

            stored_state = self.session_manager.get_data("current_state", screen_name=self.screen_name)
            if stored_state and stored_state in self.state_machine.states:
                self.state_machine.current_state = self.state_machine.states[stored_state]
            else:
                self.state_machine.current_state = self.state_machine.states["initial"]

            self.query_one(StateInfo).update_state_info(self.state_machine, "")
            self.query_one(StateButtonGrid).update_buttons()
            self.update_header()
        except NoMatches:
            logging.warning("Dynamic container not found; scheduling UI update later.")
            self.call_later(self.update_ui_after_session_load)

    def transition_to_initial_state(self):
        initial_state = self.state_machine.states.get("initial")
        if initial_state:
            self.state_machine.current_state = initial_state
            logging.info(f"Set state to initial")
            self.query_one(StateInfo).update_state_info(self.state_machine, "")
            self.query_one(StateButtonGrid).update_buttons()
            # Store the current state in the session data
            self.session_manager.update_data("current_state", "initial", screen_name=self.screen_name)
        else:
            logging.error(f"Failed to set state to initial_state: State not found")



    @on(NewAgentCreated)
    def create_new_agent(self, event: NewAgentCreated):
        # Create agent in file system. 
        self._save_new_agent(event.agent_name)        
        dynamic_container: DynamicContainer = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
        dynamic_container.clear_content()

    def _get_model_and_timeline(self) -> Tuple[ConfigurableModel, Timeline]:        
       
        self.model_id = self.app.get_current_llm_config()["model_id"]

        # TODO: Hard Coded default provider. 
        model = ModelManager.initialize_model_with_id("anthropic",self.model_id)
        
        timeline = Timeline()
        return model, timeline    

    def _load_processor(self, file_name: str, path: str) -> None:
        """General method to load a timeline and initialize the command processor."""
        try:
            self.model, self.timeline = self._get_model_and_timeline()
            self.timeline.load(file_name, path=path)
            self.processor = CommandProcessor(self.timeline, self.model)
        except FileNotFoundError:
            logging.error(f"File {file_name} not found in {path}.")
        except Exception as e:
            logging.error(f"Failed to load processor: {str(e)}")

    
    @on(LoadDialog)
    def load_dialog(self, event: LoadDialog):
        # Dialog specific
        config_manager: LLMConfigManager = LLMConfigManager()
        dialog_path: str = config_manager.get_general_config().get('dialog_save_path', '')

        self._load_processor(event.dialog_name, dialog_path)
        self.post_message(DialogLoaded(processor=self.processor))

    @on(NewDialogCreated)
    def create_new_dialog(self, event: NewDialogCreated):
        # This is for dialog
        # dialog_save_path: str = self.config_manager.get_general_config().get('dialog_save_path', '')
        config_manager: LLMConfigManager = LLMConfigManager()
        dialog_path: str = config_manager.get_general_config().get('dialog_save_path', '')
        self._save_new_dialog(dialog_path, event.dialog_name)
        dynamic_container: DynamicContainer = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
        dynamic_container.clear_content()
      
    def _save_new_dialog(self,dialog_path, name):
        
        # Create the directory if it doesn't exist
        os.makedirs(dialog_path, exist_ok=True)
        file_path = os.path.join(dialog_path, f"{name}.json")        
        
        # Metadata now includes name and description
        metadata = {
            "frozenSegments": [],
            "startMode": 'interactive',
            "name": name,
            "description": ""
        }
        
        # Prepare the data dictionary with additional metadata
        data = {
            "history": [],
            "metadata": metadata,
            "system_message": ""
        }
        # Writing to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)    

    def _save_new_agent(self, agent_name):
        """Saves the current dialog as a user-defined agent."""
    
        # File path construction
        agents_dir = os.path.expanduser("~/.underdogcowboy/agents")
    
        # Create the directory if it doesn't exist
        os.makedirs(agents_dir, exist_ok=True)
        file_path = os.path.join(agents_dir, f"{agent_name}.json")
        

        # Metadata now includes name and description
        metadata = {
            "frozenSegments": [],
            "startMode": 'interactive',
            "name": agent_name,
            "description": ""
        }

        # Prepare the data dictionary with additional metadata
        data = {
            "history": [],
            "metadata": metadata,
            "system_message": ""
        }

        # Writing to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        # Reload agents to make the new agent available
        # from underdogcowboy import _reload_agents
        #_reload_agents() 

    def on_action_selected(self, event: ActionSelected) -> None:
        action = event.action

        #if action == "reset":
            #self.clear_session()

        dynamic_container = self.query_one("#center-dynamic-container-timeline-editor", DynamicContainer)
        dynamic_container.clear_content()

        # Mapping actions to their respective UI classes
        ui_class = {
            "load_agent": LoadAgentUI,
            "load_dialog": LoadDialogUI,
            "new_dialog": NewDialogUI,
            "new_agent": NewAgentUI,
        }.get(action)

        if ui_class:
            dynamic_container.mount(ui_class())
        else:
            # For other actions, load generic content as before
            dynamic_container.mount(CenterContent(action))

