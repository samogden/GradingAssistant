#!env python
from __future__ import annotations

import abc
import dataclasses
import logging
import os
from typing import List, Dict

from openai.types import CompletionUsage

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def get_file_list(dir_to_deduplicate) -> List[str]:
  dir_to_deduplicate = os.path.expanduser(dir_to_deduplicate)
  return list(
    filter(
      (lambda f: not os.path.isdir(f) and not f.endswith(".part")),
      [
        os.path.join(dir_to_deduplicate, f)
        for f in os.listdir(dir_to_deduplicate)
      ]
    )
  )


class Costable(abc.ABC):
  
  class TokenCounts:
    def __init__(self, usage: CompletionUsage | None = None):
      self.completion_tokens = 0
      self.prompt_tokens = 0
      self.total_tokens = 0
      if usage is not None:
        self.completion_tokens = usage.completion_tokens
        self.prompt_tokens = usage.prompt_tokens
        self.total_tokens = usage.total_tokens
    
    def __str__(self):
      return f"(completion_tokens={self.completion_tokens}, prompt_tokens={self.prompt_tokens}, total_tokens={self.total_tokens})"
    
    def __add__(self, other: CompletionUsage):
      try:
        self.completion_tokens += other.completion_tokens
        self.prompt_tokens += other.prompt_tokens
        self.total_tokens += other.total_tokens
      except  AttributeError:
        pass
      return self
    
    def __radd__(self, other):
      return self.__add__(other)
  @abc.abstractmethod
  def get_token_count(self) -> TokenCounts:
    pass
  
@dataclasses.dataclass
class Feedback:
  overall_score: float = None
  overall_feedback: str = str()
  per_item_score: Dict[int, float] = dataclasses.field(default_factory=dict)
  per_item_feedback: Dict[int, str] = dataclasses.field(default_factory=dict)
  
  def __str__(self):
    return f"Feedback({self.overall_score}, ...)"
    # return f"Feedback({self.overall_score}, {self.overall_feedback}, {self.per_item_score}, {self.per_item_feedback})"
  
  def __lt__(self, other):
    if self.overall_score is None:
      return 1
    if other.overall_score is None:
      return -1
    return self.overall_score < other.overall_score
  
  def __le__(self, other):
    if self.overall_score is None:
      return 1
    if other.overall_score is None:
      return -1
    return self.overall_score <= other.overall_score
  
  def __gt__(self, other):
    if self.overall_score is None:
      return 1
    if other.overall_score is None:
      return -1
    return self.overall_score > other.overall_score
  
  def __ge__(self, other):
    if self.overall_score is None:
      return 1
    if other.overall_score is None:
      return -1
    return self.overall_score >= other.overall_score
  