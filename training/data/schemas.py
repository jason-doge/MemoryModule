"""Schema definitions for training samples and rollout entries."""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class MaintainerRolloutEntry:
    """Single teacher rollout entry for memory maintainer (model A)."""
    trajectory_id: str
    step_number: int
    obs_index: int
    slice_index: int
    context: Dict[str, Any]
    obs: Dict[str, Any]
    retrieved_memories: List[Dict[str, Any]]
    teacher_output: List[Dict[str, Any]]  # decisions JSON


@dataclass
class ConsolidatorRolloutEntry:
    """Single teacher rollout entry for memory consolidator (model B)."""
    trajectory_id: str
    step_number: int
    obs_index: int
    slice_index: int
    context: Dict[str, Any]
    obs: Dict[str, Any]
    retrieved_memories: List[Dict[str, Any]]
    teacher_output: Dict[str, Any]  # memories with mem_id, selected, reason


@dataclass
class MaintainerSFTExample:
    """SFT training example for maintainer model."""
    prompt: str  # formatted input for policy model
    target: str  # JSON string of decisions
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsolidatorSFTExample:
    """SFT training example for consolidator model."""
    prompt: str  # formatted input for policy model
    target: str  # JSON string of memories selection
    metadata: Dict[str, Any] = field(default_factory=dict)
