#!env python
from __future__ import annotations

import itertools
import json
import os.path
import pathlib

import logging
import pprint
import random
import re
import typing

import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class Submission():
  def __init__(self, user_id, path_to_file):
    self.user_id = user_id
    self.path_to_file = path_to_file
    
    # Results dictionary that will be by question number and contain columns score, max_score, feedback
    self.results : typing.Dict[str, typing.Dict] = {}
    
  def parse_submission(self,
      line_combination_function : typing.Optional[typing.Callable[[typing.List[str]],str]] = None
  ) -> typing.Dict[int,str]:
    """
    
    Reads in the submission line-by-line, spliting when it recognizes the sequence that denotes a new answer.
    Uses the provided function, line_combination_function, to combine multiple student input lines from a list of individual lines
    :param line_combination_function:
    :return:
    """
    
    if line_combination_function is None:
      # A function to strip all of the lines to ensure empty lines are empty and then combine them all with newlines
      line_combination_function = (
        lambda lines:
        '\n'.join(
          filter(
            lambda s: len(s) > 0,
            map(
              lambda l: l.strip(),
              lines
            )
          )
        )
      )
    
    with open(self.path_to_file) as fid:
      lines = [l.strip() for l in fid.readlines()]
    question_line_regex = re.compile(r'^#@ (\d+).*$')
    
    responses = {}
    question_number = None
    student_response_lines = []
    current_line_index = 0
    while current_line_index < len(lines):
      line = lines[current_line_index]
      # Check to see if the current line starts a question
      match = re.match(question_line_regex, line)
      if match:
        # Then we are starting a new question
        if question_number is None:
          # Then this is actually the first question and we should probably skip it
          pass
        else:
          # Then we are in an existing question
          responses[question_number] = line_combination_function(student_response_lines)
        # Prepare for the next question
        question_number = match.group(1)
        student_response_lines = []
      else:
        student_response_lines.append(line)
      current_line_index += 1
    responses[question_number] = line_combination_function(student_response_lines)
    
    return responses
  
  @staticmethod
  def __compare_answers(a1, a2):
    def convert_to_float_or_nan(s):
      try:
        return float(s)
      except:
        return float('nan')
    
    cleaning_operations = [
      (lambda s: s), # Leave as it is (this is technically a subcase of the other two but whatever)
      (lambda s: s.lower()), # make everything lowercase
      (lambda s: ''.join(s.split(' '))), # remove all spaces
      (lambda s: convert_to_float_or_nan(s)) # Convert all to floats, if possible.  Note two NaNs are different
    ]
    
    # Now the tricky part.  I want to apply all cleaning operation to all of the inputs and see if any combinations match
    operation_combinations = itertools.product(cleaning_operations, repeat=2)
    return any(
      [ op1(a1) == op2(a2) for op1, op2 in operation_combinations]
    )

  def generate_results(self, rubric: typing.Dict):
    submission_contents = self.parse_submission()
    
    for question_number in rubric.keys():
      if self.__compare_answers(rubric[question_number]['key'], submission_contents[question_number]):
        score = rubric[question_number]["points"]
        feedback = f""
      else:
        score = 0.0
        feedback = f"{rubric[question_number]['explanation']}"
      self.results[question_number] = {
        "score" : score,
        "max_score" : rubric[question_number]["points"],
        "feedback": feedback
      }
      
  @classmethod
  def load_submissions(cls, path_to_submissions) -> typing.List[Submission]:
    submissions = []
    for i, f in enumerate([os.path.join(path_to_submissions, f) for f in os.listdir(path_to_submissions)]):
      submissions.append(cls(i, f))
    return submissions

class AssignmentFromRubric():
  # Has parts and values per part
  class AssignmentPart():
    # Has file, identifier (maybe), long name, and problems, and rubric
    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      self.submissions : typing.List[Submission] = []
      
      self.files = []
      self.id = None
      self.name = None
      self.name = None
      self.rubric = None
      self.type = None
      
      self.file_regexes = []
    
    def __str__(self):
      return self.name
    
    def update_regexes(self):
      for f in self.files:
        # Set up the match groups so we can keep both parts and throw out the extra from canvas
        file_path = pathlib.Path(f)
        self.file_regexes.append(re.compile(f"(.*{file_path.stem}).*({file_path.suffix})"))
        

    def does_file_belong_to(self, file_path):
      """
      Hahahahaha never do this.  At least not if you're a good person.
      :param file_path:
      :return:
      """
      for r in self.file_regexes:
        match = re.search(r, file_path)
        if match:
          return ''.join(match.groups()) #f"{match.group(1)}"
      return None
    
    def grade_submissions(self) -> pd.DataFrame:
      if self.type == "manual": return pd.DataFrame()
      overall_results = []
      for s in self.submissions:
        s.generate_results(self.rubric)
        submission_results = s.results
        for q_number, q_results in submission_results.items():
          q_results["assignment_part"] = self.id
          q_results["assignment_part_name"] = self.name
          q_results["user_id"] = s.user_id
          q_results["q_number"] = q_number
          overall_results.append(q_results)
      df = pd.DataFrame(overall_results,
        columns=[
          "assignment_part",
          "assignment_part_name",
          "user_id",
          "q_number",
          "max_score",
          "score",
          "feedback"
        ]
      )
      return df
    
    
    @classmethod
    def build_from_rubric_json(cls, path_to_rubric) -> AssignmentFromRubric.AssignmentPart:
      log.debug(f"{cls.__name__}.build_from_rubric_json({path_to_rubric})")
      assignment_part_from_rubric = cls()
    
      with open(path_to_rubric) as fid:
        rubric = json.load(fid)
      
      assignment_part_from_rubric.files = []
      if "files" in rubric:
        assignment_part_from_rubric.files.extend(rubric["files"])
      if "file" in rubric:
        assignment_part_from_rubric.files.append(rubric["file"])
      
      if "problems" in rubric:
        assignment_part_from_rubric.rubric = rubric["problems"]
      elif "rubric" in rubric:
        assignment_part_from_rubric.rubric = rubric["rubric"]
      
      assignment_part_from_rubric.id = rubric["id"]
      assignment_part_from_rubric.name = rubric["name"]
      
      if "ordering" in rubric:
        assignment_part_from_rubric.ordering = rubric["ordering"]
      
      assignment_part_from_rubric.type = rubric["type"]
      
      assignment_part_from_rubric.update_regexes()
      return assignment_part_from_rubric
    
    def save_scores(self, df: typing.Optional[pd.DataFrame] = None, working_dir=None):
      filename = f"scores.{self.id}.csv"
      if working_dir is not None:
        filename = os.path.join(working_dir, filename)
        
      if df is None:
        df : pd.DataFrame = self.grade_submissions()
      df.to_csv(filename)

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    
    # Store the different parts of the assignment
    self.parts : typing.List[typing.Tuple[float, AssignmentFromRubric.AssignmentPart]] = []
    
  @classmethod
  def build_from_rubric_json(cls, path_to_rubric) -> AssignmentFromRubric:
    assignment_from_rubric = AssignmentFromRubric()
    
    rubric_base_dir = os.path.dirname(path_to_rubric)
    log.debug(f"Using as a base: {rubric_base_dir}")
    
    with open(path_to_rubric) as fid:
      base_rubric = json.load(fid)
    log.debug(f"base_rubric: {base_rubric}")
    
    for key, entry in base_rubric.items():
      # Check to see if there's a sub-rubric that we're looking for -- and error if not
      if "location" not in entry:
        log.error("No location found -- manually check structure")
        continue
      
      part_weight = entry["weight"]
      part_rubric = os.path.join(rubric_base_dir, entry["location"], "rubric.json")
      
      assignment_from_rubric.parts.append((
        part_weight,
        AssignmentFromRubric.AssignmentPart.build_from_rubric_json(part_rubric)
      ))
    
    return assignment_from_rubric
  
  def describe(self):
    for value, part in self.parts:
      print(f"{value} points : {part.files} : {len(part.submissions)}")
    
  def sort_files(self, submissions_to_sort : typing.List[Submission]):
    unsorted = []
    for s in submissions_to_sort:
      found_placement = False
      for (_, p) in self.parts:
        new_file_name = p.does_file_belong_to(s.path_to_file)
        # If the previous returned something besides None, then we know it belongs to it
        if new_file_name:
          p.submissions.append(s)
          found_placement = True
          continue
      if not found_placement:
        unsorted.append(s)
    log.info(f"There are {len(unsorted)} unsorted submissions")
    if len(unsorted) > 0:
      for u in unsorted:
        log.info(f"{u.path_to_file}")
    return unsorted
  

def main():
  grading_base = "/Users/ssogden/scratch/grading"
  student_files_dir = os.path.join(grading_base, "files")
  assignment_files_dir = os.path.join(grading_base, "hw2-lin-alg-pca")
  
  # rubric_files = find_rubrics(assignment_files_dir)
  # parse_rubrics(rubric_files)
  
  a = AssignmentFromRubric.build_from_rubric_json(os.path.join(assignment_files_dir, "rubric.json"))
  
  student_submissions = Submission.load_submissions(student_files_dir)
  
  unsorted = a.sort_files(student_submissions)

  a.describe()
  
  
  for (weight, part) in a.parts:
    results_df = part.grade_submissions()
    print(results_df)
    part.save_scores(results_df, working_dir=grading_base)
  
  
  if len(unsorted) > 0:
    log.error(f"REMEMBER: THERE ARE {len(unsorted)} UNSORTED SUBMISSIONS")
    exit(127)
  


if __name__ == "__main__":
  main()