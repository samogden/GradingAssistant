#!env python
import time
from typing import List, Tuple

import misc


class Grader:
  def __init__(self, *args, **kwargs):
    pass
  
  # todo: change this so it is more general -- it takes an interable as input and produces a grade.
  #   The idea being that it can be either a HumanGrader, AIGrader, or CodeGrader
  def grade_assignment(self, input_files: List[str], *args, **kwargs) -> misc.Feedback:
    # todo: will eventually take in assignment name and use my grading script, or something similar.
    time.sleep(1)
    return misc.Feedback(overall_score=42.0, overall_feedback="Excellent job!")