import logging
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, Collapsible
from textual.css.query import NoMatches

from uccli import StateMachine

from session_manager import SessionManager


from ui_factory import UIFactory
from ui_components.session_dependent import SessionDependentUI
from ui_components.dynamic_container import DynamicContainer
from ui_components.state_button_grid_ui import StateButtonGrid
from ui_components.state_info_ui import StateInfo
from ui_components.left_side_ui import LeftSideContainer
from ui_components.category_list_ui import CategoryListUI
from ui_components.category_editor_ui import CategoryEditorUI
from ui_components.center_content_ui import CenterContent
from ui_components.load_agent_ui import LoadAgentUI

from events.button_events import UIButtonPressed
from events.action_events import ActionSelected
from events.category_events import CategorySelected, CategoryLoaded


from screens.session_screen import SessionScreen
from state_machines.agent_assessment_state_machine import create_agent_assessment_state_machine


class AgentAssessmentBuilderScreen(SessionScreen):
    """A screen for the agent assessment builder."""
    # CSS_PATH = "../state_machine_app.css"

    def __init__(self, state_machine: StateMachine = None, session_manager: SessionManager = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = "Agent Assessment Builder"
        self.state_machine = state_machine or create_agent_assessment_state_machine()
        self.session_manager = session_manager
        self.ui_factory = UIFactory(self)
        self.screen_name = "AgentAssessmentBuilderScreen"
        self._pending_session_manager = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="agent-centre", classes="dynamic-spacer"):
            yield LeftSideContainer(classes="left-dynamic-spacer")
            yield DynamicContainer(id="center-dynamic-container-agent-assessment-builder", classes="center-dynamic-spacer")

        with Vertical(id="app-layout"):
            with Collapsible(title="Task Panel", id="state-info-collapsible", collapsed=False):
                yield StateInfo(id="state-info")
                yield StateButtonGrid(self.state_machine, id="button-grid")

        yield Footer(id="footer", name="footer")

    def on_mount(self) -> None:
        """Called when the screen is mounted. It sets up the state and updates the UI based on session data."""
        logging.info("AgentAssessmentBuilderScreen on_mount called")
        state_info = self.query_one("#state-info", StateInfo)
        state_info.update_state_info(self.state_machine, "")
        self.update_header()

        if self._pending_session_manager:
            session_manager = self._pending_session_manager
            self._pending_session_manager = None
            self.call_later(self.set_session_manager, session_manager)

    def set_session_manager(self, new_session_manager: SessionManager):
        """Sets the session manager and loads the UI based on session data."""
        self.session_manager = new_session_manager
        if self.is_mounted:
            self.call_later(self.update_ui_after_session_load)
        else:
            self._pending_session_manager = new_session_manager

    def update_ui_after_session_load(self):
        """Updates the UI after loading session data."""
        try:
            dynamic_container = self.query_one("#center-dynamic-container-agent-assessment-builder", DynamicContainer)
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

    def update_header(self, session_name=None, agent_name=None):
        """Updates the header to reflect the current session and agent."""
        if not session_name:
            session_name = self.session_manager.current_session_name
        if not agent_name:
            agent_name = "Agent Assessment Builder"
        self.sub_title = f"{agent_name}"
        if session_name:
            self.sub_title += f" - Active Session: {session_name}"
        self.refresh(layout=True)

    @on(UIButtonPressed)
    def handle_ui_button_pressed(self, event: UIButtonPressed) -> None:
        """Handles button presses and dynamically loads UI components based on button actions."""
        logging.debug(f"Handler 'handle_ui_button_pressed' invoked with button_id: {event.button_id}")
        dynamic_container = self.query_one("#center-dynamic-container-agent-assessment-builder", DynamicContainer)
        dynamic_container.clear_content()

        try:
            ui_class, action = self.ui_factory.ui_factory(event.button_id)

            if ui_class:
                if event.button_id == "load-session" and not self.session_manager.list_sessions():
                    self.notify("No sessions available. Create a new session first.", severity="warning")
                else:
                    ui_instance = ui_class()
                    dynamic_container.load_content(ui_instance)

            if action:
                action()

        except ValueError as e:
            logging.error(f"Error: {e}")

    def transition_to_initial_state(self):
        """Transition the state machine to the initial state and update the session."""
        initial_state = self.state_machine.states.get("initial")
        if initial_state:
            self.state_machine.current_state = initial_state
            logging.info(f"Set state to initial")
            self.query_one(StateInfo).update_state_info(self.state_machine, "")
            self.query_one(StateButtonGrid).update_buttons()

            self.session_manager.update_data("current_state", "initial", screen_name=self.screen_name)
        else:
            logging.error(f"Failed to set state to initial: State not found")

    def clear_session(self):
        self.session_manager.current_session_data = None
        self.session_manager.current_session_name = None
        self.update_header()
        

    def on_action_selected(self, event: ActionSelected) -> None:
        action = event.action

        if action == "reset":
            self.clear_session()

        dynamic_container = self.query_one("#center-dynamic-container-agent-assessment-builder", DynamicContainer)
        dynamic_container.clear_content()

        # Mapping actions to their respective UI classes
        ui_class = {
            "load_agent": LoadAgentUI,
            "list_categories" : CategoryListUI
        }.get(action)

        if ui_class:
            # Instantiate with parameters if it's a subclass of SessionDependentUI
            if issubclass(ui_class, SessionDependentUI):
                dynamic_container.mount(ui_class(
                    session_manager=self.session_manager,
                    screen_name=self.screen_name,
                    agent_name_plain=self.agent_name_plain
                ))
            else:
                dynamic_container.mount(ui_class())
        else:
            # For other actions, load generic content as before
            dynamic_container.mount(CenterContent(action))


    @on(CategorySelected)
    def on_category_selected(self, message: CategorySelected) -> None:
        """Handle the CategorySelected event and load the CategoryEditorUI."""
        logging.info(f"Category selected: {message.category_name}")

        dynamic_container = self.query_one("#center-dynamic-container-agent-assessment-builder", DynamicContainer)
        dynamic_container.clear_content()

        category_editor_ui = CategoryEditorUI(self.session_manager)
        dynamic_container.mount(category_editor_ui)

        # we want to send message for the handler in the CategoryEditorUI
        self.post_message(CategoryLoaded(message.category_name))

