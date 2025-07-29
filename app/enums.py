from enum import Enum

class Project(Enum):
    """Azure DevOps Projects"""
    SHIPTECH = "Shiptech"
    # Add more projects here as needed
    # EXAMPLE_PROJECT = "ExampleProject"

class WorkItemType(Enum):
    """Azure DevOps Work Item Types"""
    REQUIREMENT = "Requirement"
    CHANGE_REQUEST = "Change Request"
    TASK = "Task"
    BUG = "Bug"
    FEATURE = "Feature"

class IterationPath(Enum):
    """Azure DevOps Iteration Paths"""
    ROADMAP = "Shiptech\\12.10.0\\Roadmap"
    # Add more iteration paths as needed
    # SPRINT_1 = "Shiptech\\12.10.0\\Sprint 1"
    # SPRINT_2 = "Shiptech\\12.10.0\\Sprint 2" 