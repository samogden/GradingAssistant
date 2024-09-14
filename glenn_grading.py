#!env python
from __future__ import annotations

import json
import os.path
import pathlib

import logging
import pprint
import re
import typing

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class Submission():
  def __init__(self, user_id, path_to_file):
    self.user_id = user_id
    self.path_to_file = path_to_file

class AssignmentFromRubric():
  # Has parts and values per part
  class AssignmentPart():
    # Has file, identifier (maybe), long name, and problems, and rubric
    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      
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
    
    
    @classmethod
    def build_from_rubric_json(cls, path_to_rubric) -> AssignmentFromRubric.AssignmentPart:
      log.debug(f"{cls.__name__}.build_from_rubric_json({path_to_rubric})")
      assignment_part_from_rubric = cls()
    
      with open(path_to_rubric) as fid:
        rubric = json.load(fid)
      log.debug(f"rubric: {pprint.pformat(rubric)}")
      
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
      print(f"{value} points : {part.files} : {pprint.pformat(part.rubric)}")
    
  def sort_files(self, files_to_sort):
    for f in files_to_sort:
      log.debug(f"Checking {f}")
      for (_, p) in self.parts:
        new_file_name = p.does_file_belong_to(f)
        if new_file_name:
          log.debug(f"{p} : {new_file_name}")
      log.debug("")

def main():
  grading_base = "/Users/ssogden/scratch/grading"
  student_files_dir = os.path.join(grading_base, "files")
  assignment_files_dir = os.path.join(grading_base, "hw2-lin-alg-pca")
  
  # rubric_files = find_rubrics(assignment_files_dir)
  # parse_rubrics(rubric_files)
  
  a = AssignmentFromRubric.build_from_rubric_json(os.path.join(assignment_files_dir, "rubric.json"))
  
  student_files = os.listdir(student_files_dir)
  
  a.sort_files(student_files)

  


if __name__ == "__main__":
  main()