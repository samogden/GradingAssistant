#!env python
from __future__ import annotations

import argparse
import itertools
import json
import os.path
import pathlib

import logging
import pprint
import random
import re
import subprocess
import typing

import canvasapi
import dotenv
import pandas as pd
import yaml

import assignment

from flask import Flask, render_template, redirect, url_for

# Setting up a flask server
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class Submission():
  def __init__(self, user_id, user_name, path_to_file):
    self.user_id = user_id
    self.user_name = user_name
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
    log.debug(f"a1 : {a1}")
    log.debug(f"a2 : {a2}")
    for op1, op2 in operation_combinations:
      try:
        if op1(a1) == op2(a2):
          return True
      except AttributeError:
        pass
    if a2 in a1:
      return True
    return False

  def generate_results(self, rubric: typing.Dict):
    submission_contents = self.parse_submission()
    log.debug(f"rubric: {pprint.pformat(rubric)}")
    log.info(f"{self.path_to_file}")
    for question_number in rubric.keys():
      
      
      if question_number in submission_contents and self.__compare_answers(rubric[question_number]['key'], submission_contents[question_number]):
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
      overall_results = []
      for s in self.submissions:
      
        if self.type == "manual":
          log.debug(self.rubric)
          overall_results.extend([
            {
              "q_number": q_number,
              "assignment_part" : self.id,
              "assignment_part_name" : self.name,
              "user_id" : s.user_id,
              "user_name": s.user_name,
              "max_score" : self.rubric[q_number]
            }
            for q_number in self.rubric
          ])
        else:
          s.generate_results(self.rubric)
          submission_results = s.results
          
          for q_number, q_results in submission_results.items():
            q_results["assignment_part"] = self.id
            q_results["assignment_part_name"] = self.name
            q_results["user_id"] = s.user_id
            q_results["user_name"] = s.user_name
            q_results["q_number"] = q_number
            overall_results.append(q_results)
          
      df = pd.DataFrame(overall_results,
        columns=[
          "assignment_part",
          "assignment_part_name",
          "user_id",
          "user_name",
          "q_number",
          "max_score",
          "score",
          "feedback"
        ]
      )
    
      df["feedback"] = df["feedback"].fillna('')
      return df
    
    
    @classmethod
    def build_from_rubric_json(cls, rubric_dict: typing.Dict) -> AssignmentFromRubric.AssignmentPart:
      # log.debug(f"{cls.__name__}.build_from_rubric_json({path_to_rubric})")
      assignment_part_from_rubric = cls()
      
      log.debug(pprint.pformat(rubric_dict))
      
      assignment_part_from_rubric.files = []
      if "files" in rubric_dict:
        assignment_part_from_rubric.files.extend(rubric_dict["files"])
      if "file" in rubric_dict:
        assignment_part_from_rubric.files.append(rubric_dict["file"])
      
      if "problems" in rubric_dict:
        assignment_part_from_rubric.rubric = rubric_dict["problems"]
      elif "rubric" in rubric_dict:
        assignment_part_from_rubric.rubric = rubric_dict["rubric"]
      
      assignment_part_from_rubric.id = rubric_dict["id"]
      assignment_part_from_rubric.name = rubric_dict["name"]
      
      if "ordering" in rubric_dict:
        assignment_part_from_rubric.ordering = rubric_dict["ordering"]
      
      assignment_part_from_rubric.type = rubric_dict["type"]
      
      assignment_part_from_rubric.update_regexes()
      return assignment_part_from_rubric
    
    def save_scores(self, df: typing.Optional[pd.DataFrame] = None, working_dir=None):
      filename = f"scores.{self.id}.csv"
      if working_dir is not None:
        filename = os.path.join(working_dir, filename)
        
      if df is None:
        df : pd.DataFrame = self.grade_submissions()
      df["user_name"] = df["user_name"].apply(lambda u: str(u))
      df = df.sort_values(by=["user_name", "q_number"])
      df.to_csv(filename, index=False)

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
      if os.path.isdir(os.path.join(rubric_base_dir, entry["location"])):
        part_rubric = os.path.join(rubric_base_dir, entry["location"], "rubric.json")
      else:
        part_rubric = os.path.join(rubric_base_dir, entry["location"])
      
      log.debug(f"part_rubric: {part_rubric}")
      
      with open(part_rubric) as fid:
        if part_rubric.endswith("json"):
            rubric_dict = json.load(fid)
        elif part_rubric.endswith("yaml"):
          rubric_dict = yaml.safe_load(fid)
      assignment_from_rubric.parts.append((
        part_weight,
        AssignmentFromRubric.AssignmentPart.build_from_rubric_json(rubric_dict)
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


def generate_DFs_by_assignment(a: AssignmentFromRubric, student_submissions : typing.List[Submission], working_dir):
  unsorted = a.sort_files(student_submissions)
  
  dfs_by_assignment = {}
  for (weight, part) in a.parts:
    dfs_by_assignment[part.id] = part.grade_submissions()
    
  return dfs_by_assignment


def generate_CSVs(a: AssignmentFromRubric, student_submissions : typing.List[Submission], working_dir):
  unsorted = a.sort_files(student_submissions)
  
  for (weight, part) in a.parts:
    results_df = part.grade_submissions()
    print(results_df)
    part.save_scores(results_df, working_dir=working_dir)
  
  if len(unsorted) > 0:
    log.error(f"REMEMBER: THERE ARE {len(unsorted)} UNSORTED SUBMISSIONS")
    exit(127)

def read_CSVs(a: AssignmentFromRubric, csvs : typing.List[str]):
  df_by_assignment = {}
  for df in [pd.read_csv(csv) for csv in csvs]:
    df["feedback"] = df["feedback"].fillna('')
    df_by_assignment[df["assignment_part"].iloc[0]] = df.groupby("user_id").agg({
      'score' : 'sum',
      'max_score' : 'sum',
      'feedback' : lambda s: [f"Q{i+1}: {f}" for i, f in enumerate(s.tolist()) if len(f) > 0]
    })
  
  return df_by_assignment


def combine_DFs_into_feedback(a: AssignmentFromRubric, df_by_assignment : typing.Dict[pd.DataFrame]):
  user_ids = pd.concat([pd.Series(df.index) for df in df_by_assignment.values()]).unique()
  log.debug(user_ids)
   # todo: fix these variable names to make them less stupid
  feedback = []
  for user_id in user_ids:
    log.debug(f"Generating score and feedback for {user_id}")
    overall_score = 0.0
    overall_feedback = ""
    for weight, assignment_part in a.parts:
      percentage_score = 0.0
      try:
        row = df_by_assignment[assignment_part.id].loc[user_id]
        percentage_score = row["score"] / row["max_score"]
        if len(row["feedback"]) > 0:
          overall_feedback += f"Feedback for: {assignment_part.name}"
          if isinstance(row["feedback"], str):
            overall_feedback += "\n  - " +row["feedback"]
          else:
            overall_feedback += "\n  - " + '\n  - '.join(row["feedback"])
          overall_feedback += "\n\n"
      except KeyError:
        log.warning(f"No entry for {user_id} in {assignment_part.name}")
        overall_feedback += f"{assignment_part.name} is missing"
        overall_feedback += "\n\n"
      overall_score += percentage_score * weight
    
    log.debug(f"overall_score: {overall_score}")
    log.debug(f"overall_feedback: {overall_feedback}")
    feedback.append({
      "user_id" : user_id,
      "score" : overall_score,
      "feedback" : overall_feedback
    })
  return feedback


def combine_CSVs(a: AssignmentFromRubric, csvs : typing.List[str], fudge : float = 0.0):
  df_by_assignment = {}
  for df in [pd.read_csv(csv) for csv in csvs]:
    df["feedback"] = df["feedback"].fillna('')
    df_by_assignment[df["assignment_part"].iloc[0]] = df.groupby("user_id").agg({
      'score' : 'sum',
      'max_score' : 'sum',
      'feedback' : lambda s: [f"Q{i+1}: {f}" for i, f in enumerate(s.tolist()) if len(f) > 0]
    })
  
  
  user_ids = pd.concat([pd.Series(df.index) for df in df_by_assignment.values()]).unique()
  log.debug(user_ids)
  
  
  # todo: these variables are poorly named
  
  feedback = []
  for user_id in user_ids:
    log.debug(f"Generating score and feedback for {user_id}")
    overall_score = fudge
    overall_feedback = ""
    for weight, assignment_part in a.parts:
      percentage_score = 0.0
      try:
        row = df_by_assignment[assignment_part.id].loc[user_id]
        percentage_score = row["score"] / row["max_score"]
        if len(row["feedback"]) > 0:
          overall_feedback += f"Feedback for: {assignment_part.name}"
          overall_feedback += "\n  - " + '\n  - '.join(row["feedback"])
          overall_feedback += "\n\n"
      except KeyError:
        log.warning(f"No entry for {user_id} in {assignment_part.name}")
        overall_feedback += f"{assignment_part.name} is missing"
        overall_feedback += "\n\n"
      overall_score += percentage_score * weight
    
    log.debug(f"overall_score: {overall_score}")
    log.debug(f"overall_feedback: {overall_feedback}")
    feedback.append({
      "user_id" : user_id,
      "score" : overall_score,
      "feedback" : overall_feedback
    })
  return feedback

def get_submissions(course_id: int, assignment_id: int, prod: bool, limit=None):
  with assignment.CanvasAssignment(course_id, assignment_id, prod) as a:
    student_submissions = a.get_student_submissions(a.canvas_assignment, True)
    if limit != None:
      student_submissions = student_submissions[:limit]
    log.debug(f"Asking to download to: {os.path.join(os.getcwd(), 'files')}")
    submissions = a.download_submission_files(student_submissions, download_dir=os.path.join(os.getcwd(), "files"), overwrite=False, download_all_variations=False)
  
  assignment_submissions = []
  for (user_id, _, user_name), list_of_files in submissions.items():
    assignment_submissions.extend([
      Submission(user_id, user_name, path_to_file)
      for path_to_file in list_of_files
    ])
  
  return assignment_submissions

def submit_feedback(course_id: int, assignment_id: int, prod: bool, feedback: typing.List[typing.Dict], limit=None):
  log.debug(assignment.CanvasAssignment.canvas)
  with assignment.CanvasAssignment(course_id, assignment_id, prod) as a:
    for grading_response in feedback:
      a.push_feedback(
        grading_response["user_id"],
        grading_response["score"],
        grading_response["feedback"]
      )


def parse_args():
  
  parser = argparse.ArgumentParser()
  
  parser.add_argument("--assignment", dest="assignments", action="append", nargs=2)
  
  parser.add_argument("--course_id", type=int, default=25671)
  parser.add_argument("--assignment_id", type=int, default=402682)
  parser.add_argument("--push", action="store_true")
  parser.add_argument("--prod", action="store_true")
  parser.add_argument("--limit", type=int)
  parser.add_argument("--working_dir", default=None)
  parser.add_argument("--fudge", type=float, default=0.0, help="Add a small amount to every score to fix some weirdness in grading")
  parser.add_argument("--base_dir", required=True)
  
  parser.add_argument("--csvs", nargs='+', default=[])
  
  subparsers = parser.add_subparsers(dest="action")
  subparsers.add_parser("GENERATE")
  subparsers.add_parser("COMBINE")
  
  args, remaining_args = parser.parse_known_args()
  
  if args.working_dir is None:
    args.working_dir = os.getcwd()
  
  # If there are remaining arguments (e.g., global flags after subcommands), reparse them
  if remaining_args:
    args = parser.parse_args(remaining_args, namespace=args)
  
  return args


def main():
  args = parse_args()
  
  grading_base = os.getcwd() #"/Users/ssogden/scratch/grading"
  student_files_dir = os.path.join(grading_base, "files")
  assignment_files_dir = os.path.join(grading_base, args.base_dir)
  
  a = AssignmentFromRubric.build_from_rubric_json(os.path.join(assignment_files_dir, "rubric.json"))
  
  if args.action == "GENERATE":
    student_submissions = get_submissions(args.course_id, args.assignment_id, args.prod, limit=args.limit)
    generate_CSVs(a, student_submissions, args.working_dir)
  elif args.action == "COMBINE":
    feedback = combine_CSVs(a, args.csvs, args.fudge)
    submit_feedback(args.course_id, args.assignment_id, args.prod, feedback, limit=args.limit)
    
  return
  

if __name__ == "__main__":
  dotenv.load_dotenv()
  # log.debug(pprint.pformat(os.environ.__dict__))
  # exit()
  main()