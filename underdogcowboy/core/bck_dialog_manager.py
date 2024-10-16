import os
from typing import List, Type, Union, Dict, Optional, Any

from abc import ABC, abstractmethod
from .timeline_editor import Timeline, CommandProcessor
from .model import ModelManager
from .config_manager import LLMConfigManager
from .agent import Agent
from .tracing import TracingProxy
from .intervention import InterventionManager
from .response import Response


class AgentInitializationError(Exception):
    """Raised when an agent cannot be properly initialized or registered."""

class ModelConfigurationError(Exception):
    """Raised when the model configuration or initialization fails."""

class AgentNotPreparedError(Exception):
    """Raised when attempting to use an agent that has not been prepared."""

class InvalidAgentError(Exception):
    """Raised when an invalid agent instance or type is provided."""


class DialogManager(ABC):
 
    def __new__(cls, *args: Any, **kwargs: Any) -> Union['AgentDialogManager', 'BasicDialogManager']:
       
        if cls is AgentDialogManager:  # Check if the called class is AgentDialogManager
            return super().__new__(AgentDialogManager)  # Remove *args and **kwargs
        else:
            print("Creating BasicDialogManager")
            return super().__new__(BasicDialogManager)  # Remove *args and **kwargs

    def __pos__(self):
        """Activates the intervention mode."""
        if self.intervention_manager is None:
            self.intervention_manager = InterventionManager(self)
        self.intervention_manager.intervene()
        return self

    def __neg__(self):
        """Deactivates the intervention mode."""
        if self.intervention_manager is not None:
            # You might want to add a method to InterventionManager
            # to gracefully stop the intervention, if necessary.
            print("Intervention stopped.")
            self.intervention_manager = None
        return self

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.intervention_manager = None  # Initialize intervention_manager
        self.config_manager = LLMConfigManager()
        use_tracing = kwargs.get('use_tracing')
        
        if use_tracing is None:
            # Use the configuration from LLMConfigManager
            self.tracer = self.config_manager.get_tracing_proxy()
        else:
            # Override with the provided use_tracing parameter
            tracing_config = self.config_manager.get_tracing_config()
            api_key = tracing_config.get('langsmith_api_key', '')
            self.tracer = TracingProxy(use_langsmith=use_tracing, api_key=api_key)

        

    @abstractmethod 
    def message(self, *args: Any, **kwargs: Any) -> Any:
        pass    

class BasicDialogManager(DialogManager):

    def __init__(self, model_name: Optional[str] = None, use_tracing: bool = False) -> None:
        super().__init__(use_tracing=use_tracing)

        self.config_manager: LLMConfigManager = LLMConfigManager()
        self.dialogs: Dict[str, CommandProcessor] = {}
        self.dialog_save_path: str = self.config_manager.get_general_config().get('dialog_save_path', '')
        self.active_dialog: Optional[str] = None
        self.model_name: Optional[str] = model_name

    def load_dialog(self, filename: str) -> CommandProcessor:        
        if filename not in self.dialogs:
            if self.model_name == None:
                self.model_name = self.config_manager.select_model()

            model = ModelManager.initialize_model(self.model_name)
            timeline = Timeline()
            
            relative_path = os.path.join(self.dialog_save_path, filename)
            full_path = os.path.abspath(relative_path)
            
            if not os.path.exists(full_path):
                raise FileNotFoundError(f"Dialog file not found: {full_path}")
            
            timeline.load(full_path)
            processor = CommandProcessor(timeline, model)
            self.dialogs[filename] = processor
        
        self.active_dialog = filename
        return self.dialogs[filename]

    def message(self, processor: CommandProcessor, user_input: str) -> Response:  
        with self.tracer.trace(f"Dialog: {self.active_dialog}"):
            self.tracer.log("User Input", {"input": user_input})      
            if not isinstance(processor, CommandProcessor):
                raise TypeError("Expected a CommandProcessor instance")

            self.active_dialog = next((filename for filename, proc in self.dialogs.items() if proc == processor), None)
            if self.active_dialog is None:
                raise ValueError("The provided processor is not associated with any loaded dialog")
          
            result = processor.process_single_message(user_input)
            
            self.tracer.log("Model Output", {"output": result})
            self.tracer.log_metric("response_length", len(result))
            
            return Response(result)

    def get_active_processor(self) -> Optional[CommandProcessor]:    
        if self.active_dialog is None:
            return None
        return self.dialogs[self.active_dialog]

class AgentDialogManager(DialogManager):
    
    def __init__(self, agent_inputs: List[Union[Type[Agent], Agent]], model_name: Optional[str] = None, use_tracing: bool = False, **kwargs: Any) -> None:
        # Initialize the base class with tracing and any additional arguments
        super().__init__(use_tracing=use_tracing, **kwargs)
        
        # Initialize agent-related attributes
        self.agents: List[Agent] = []
        self.processors: Dict[Agent, CommandProcessor] = {}
        self.active_agent: Optional[Agent] = None
        self.config_manager: LLMConfigManager = LLMConfigManager()
        self.model_name: Optional[str] = model_name        
    
        # Iterate over agent inputs and initialize agents
        for agent_input in agent_inputs:
            agent = self._initialize_agent(agent_input)
            # Register the agent with this dialog manager
            agent.register_with_dialog_manager(self)
            # Add the agent to the agents list
            self.agents.append(agent)

    def __or__(self, agents: List[Union[Type[Agent], Agent]]) -> 'AgentDialogManager':
        # Overload the '|' operator to add more agents to the dialog manager
        for agent_input in agents:
            agent = self._initialize_agent(agent_input)
            # Register the agent and prepare it
            agent.register_with_dialog_manager(self)
            self.prepare_agent(agent)
            # Add the agent to the agents list
            self.agents.append(agent)
        return self  # Return self for chaining

    def _initialize_agent(self, agent_input: Union[Type[Agent], Agent]) -> Agent:
        # Helper method to initialize an agent from the input
        if isinstance(agent_input, type) and issubclass(agent_input, Agent):
            # If it's an Agent subclass, instantiate it with its class name as identifier
            return agent_input(f"{agent_input.__name__}")
        elif isinstance(agent_input, Agent):
            # If it's already an Agent instance, use it directly
            return agent_input
        else:
            # Raise an error if the input is not an Agent or Agent subclass
            raise AgentInitializationError(f"Expected Agent subclass or instance, got {type(agent_input)}")

    def prepare_agent(self, agent: Agent) -> CommandProcessor:
        # Prepare the agent by setting up a CommandProcessor for it
        with self.tracer.trace(f"Prepare Agent: {agent.id}"):
            # Check if the agent already has a processor
            if agent not in self.processors:
                # If model_name is not set, select a model using the config manager
                if not self.model_name:
                    try:
                        self.model_name = self.config_manager.select_model()
                    except Exception:
                        raise ModelConfigurationError("Failed to select or configure the model.")

                # Get the provider for the selected model
                provider = self.config_manager.get_provider_from_model(self.model_name)    
                # TODO: Refactor model_name to better reflect its purpose and structure
                model = ModelManager.initialize_model_with_id(provider, self.model_name)
                timeline = Timeline()
                
                # Use the agent's content as the initial timeline content
                timeline.load(agent.content)
                
                # Create a CommandProcessor with the timeline and model
                processor = CommandProcessor(timeline, model)
                self.processors[agent] = processor

            # Register the agent with this dialog manager and set it as active
            agent.register_with_dialog_manager(self)
            self.active_agent = agent
            return self.processors[agent]

    def message(self, agent: Agent, user_input: str) -> 'Response':
        # Process a user input message using the specified agent
        with self.tracer.trace(f"Agent Dialog: {agent.name}"):
            self.tracer.log("User Input", {"input": user_input})
            
            # Ensure the provided agent is a valid Agent instance
            if not isinstance(agent, Agent):
                raise InvalidAgentError("Expected an Agent instance")

            # Ensure the agent has been prepared with a CommandProcessor
            if agent not in self.processors:
                raise AgentNotPreparedError("The provided agent is not prepared")

            # Set the active agent and get its processor
            self.active_agent = agent
            processor = self.processors[agent]
            
            # Process the user input message and get the result
            result = processor.process_single_message(user_input)
            
            # Log the output and response length for tracing
            self.tracer.log("Agent Output", {"output": result})
            self.tracer.log_metric("response_length", len(result))

            return Response(result)

    def get_agents(self) -> List[Agent]:
        # Return the list of agents managed by this dialog manager
        return self.agents

class __back__AgentDialogManager(DialogManager):
    
    def __init__(self, agent_inputs: List[Union[Type[Agent], Agent]], model_name: Optional[str] = None, use_tracing: bool = False, **kwargs: Any) -> None:
       
        super().__init__(use_tracing=use_tracing, **kwargs)
        self.agents: List[Agent] = []
        self.processors: Dict[Agent, CommandProcessor] = {}
        self.active_agent: Optional[Agent] = None
        self.config_manager: LLMConfigManager = LLMConfigManager()
        self.model_name: Optional[str] = model_name        
    
        for agent_input in agent_inputs:
            if isinstance(agent_input, type) and issubclass(agent_input, Agent):
                # If it's an Agent subclass, instantiate it
                agent = agent_input(f"{agent_input.__name__}")
            elif isinstance(agent_input, Agent):
                # If it's already an Agent instance, use it directly
                agent = agent_input
            else:
                raise TypeError(f"Expected Agent subclass or instance, got {type(agent_input)}")
            
            # Register the agent with this dialog manager
            agent.register_with_dialog_manager(self)
            
            self.agents.append(agent)

    def __or__(self, agents: List[Union[Type[Agent], Agent]]) -> 'AgentDialogManager':
        for agent_input in agents:
            if isinstance(agent_input, type) and issubclass(agent_input, Agent):
                # If it's an Agent subclass, instantiate it
                agent = agent_input(f"{agent_input.__name__}")
            elif isinstance(agent_input, Agent):
                # If it's already an Agent instance, use it directly
                agent = agent_input
            else:
                raise TypeError(f"Expected Agent subclass or instance, got {type(agent_input)}")
            
            # Register the agent with this dialog manager
            agent.register_with_dialog_manager(self)
            self.prepare_agent(agent)
            self.agents.append(agent)
        return self  # Return self for chaining


    def prepare_agent(self, agent: Agent) -> CommandProcessor:
        with self.tracer.trace(f"Prepare Agent: {agent.id}"):
            if agent not in self.processors:
                if not hasattr(self, 'model_name') or self.model_name is None:
                    self.model_name = self.config_manager.select_model()

                provider = self.config_manager.get_provider_from_model(self.model_name)    
                #TODO refactor model_name to better name and datastructure.
                model = ModelManager.initialize_model_with_id(provider,self.model_name)
                timeline = Timeline()
                
                # Use the agent's content as the initial timeline content
                timeline.load(agent.content)
                
                processor = CommandProcessor(timeline, model)
                self.processors[agent] = processor

            agent.register_with_dialog_manager(self)
            self.active_agent = agent
            return self.processors[agent]

    def message(self, agent: Agent, user_input: str) -> 'Response':
        with self.tracer.trace(f"Agent Dialog: {agent.name}"):
            self.tracer.log("User Input", {"input": user_input})
            if not isinstance(agent, Agent):
                raise TypeError("Expected an Agent instance")

            if agent not in self.processors:
                raise ValueError("The provided agent is not prepared")

            self.active_agent = agent
            processor = self.processors[agent]
            result = processor.process_single_message(user_input)
            
            self.tracer.log("Agent Output", {"output": result})
            self.tracer.log_metric("response_length", len(result))

            return Response(result)

    def get_agents(self) -> List[Agent]:
        return self.agents