#!env python
import abc
import collections
import json
import os
import pprint
import shutil
import tarfile
import textwrap
import time
import typing
from abc import ABC
from typing import List, Tuple
import io

import docker
import docker.errors
import docker.models.images
import docker.models.containers
import yaml

import pandas as pd

import misc


import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class Grader:
  """A class that turns files to feedback.  Note: will probably be generalized to not just have files in the future"""
  def __init__(self, *args, **kwargs):
    pass
  
  # todo: change this so it is more general -- it takes an interable as input and produces a grade.
  #   The idea being that it can be either a HumanGrader, AIGrader, or CodeGrader
  @abc.abstractmethod
  def grade_assignment(self, *args, **kwargs) -> misc.Feedback:
    pass


class GraderDummy:
  @abc.abstractmethod
  def grade_assignment(self, input_files: List[str], *args, **kwargs) -> misc.Feedback:
    time.sleep(1)
    return misc.Feedback(overall_score=42.0, overall_feedback="Excellent job!")


class Grader_docker(Grader, ABC):
  client = docker.from_env()
  
  def __init__(self, image=None, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.image = image if image is not None else "ubuntu"
    self.container : docker.models.containers.Container = None
  
  @classmethod
  def build_docker_image(cls, base_image, github_repo):
    log.info("Building docker image for grading...")
    
    docker_file = io.BytesIO(f"""
    FROM samogden/cst334
    RUN git clone {github_repo} /tmp/grading/
    WORKDIR /tmp/grading
    CMD ["/bin/bash"]
    """.encode())
    
    image, logs = cls.client.images.build(
      fileobj=docker_file,
      tag="grading",
      pull=True,
      nocache=True
    )
    # log.debug(logs)
    log.debug("Docker image built successfully")
    return image
  
  def start(self, image : docker.models.images,):
    self.container = self.client.containers.run(
      image=image,
      detach=True,
      tty=True
    )
    
  def add_files_to_docker(self, files_to_copy : List[Tuple[str,str]] = None):
    """
    
    :param files_to_copy: Format is [(src, target), ...]):
    :return:
    """
    
    def add_file_to_container(src_file, target_dir, container):
      # Prepare the files as a tarball to push into container
      tarstream = io.BytesIO()
      with tarfile.open(fileobj=tarstream, mode="w") as tarhandle:
        tarhandle.add(src_file, arcname=os.path.basename(src_file))
      tarstream.seek(0)
      
      # Push student files to image
      container.put_archive(f"{target_dir}", tarstream)
    
    for src_file, target_dir in files_to_copy:
      add_file_to_container(src_file, target_dir, self.container)
  
  def execute(self, command="", container=None, workdir=None) -> typing.Tuple[int, str, str]:
    log.debug(f"execute: {command}")
    if container is None:
      container = self.container
    
    extra_args = {}
    if workdir is not None:
      extra_args["workdir"] = workdir
    
    rc, (stdout, stderr) = container.exec_run(
      cmd=f"bash -c \"{command}\"",
      demux=True,
      tty=True,
      **extra_args
    )
    
    return rc, stdout, stderr
  
  def read_file(self, path_to_file) -> str|None:
    
    try:
      # Try to find the file on the system
      bits, stats = self.container.get_archive(path_to_file)
    except docker.errors.APIError as e:
      log.error(f"Get archive failed: {e}")
      return None
    
    # Read file from docker
    f = io.BytesIO()
    for chunk in bits:
      f.write(chunk)
    f.seek(0)
    
    # Open the tarball we just pulled and read the contents to a string buffer
    with tarfile.open(fileobj=f, mode="r") as tarhandle:
      results_f = tarhandle.getmember("results.json")
      f = tarhandle.extractfile(results_f)
      f.seek(0)
      return f.read().decode()
   
  def stop(self):
    self.container.stop(timeout=1)
    self.container.remove()
    self.container = None
    
  def __enter__(self):
    log.info(f"Starting docker image {self.image} context")
    self.start(self.image)
  
  def __exit__(self, exc_type, exc_val, exc_tb):
    log.info(f"Exiting docker image context")
    self.stop()
    if exc_type is not None:
      log.error(f"An exception occured: {exc_val}")
      log.error(exc_tb)
    return False
  
  @abc.abstractmethod
  def execute_grading(self, *args, **kwargs):
    pass
  
  @abc.abstractmethod
  def score_grading(self, execution_results, *args, **kwargs) -> misc.Feedback:
    pass
  
  def grade_in_docker(self, files_to_copy=None, *args, **kwargs) -> misc.Feedback:
    with self:
      if files_to_copy is not None:
        self.add_files_to_docker(files_to_copy)
      execution_results = self.execute_grading(*args, **kwargs)
      return self.score_grading(execution_results,*args,  **kwargs)
    

class Grader_CST334(Grader_docker):

  def __init__(self, assignment_path, use_online_repo=False):
    super().__init__()
    if use_online_repo:
      github_repo="https://github.com/samogden/CST334-assignments-online.git"
    else:
      github_repo="https://github.com/samogden/CST334-assignments.git"
    self.assignment_path = assignment_path
    self.image = Grader_CST334.build_docker_image(base_image="samogden/cst334", github_repo=github_repo)
  
  def check_for_trickery(self, files_submitted) -> bool:
    for input_file in files_submitted:
      try:
        with open(input_file) as f:
          if "exit(0)" in f.read():
            return True
      except IsADirectoryError:
        pass
    if not any(map(lambda f: f.endswith(".c") and "student_code" in f, files_submitted)):
      return True
    return False
  
  @staticmethod
  def build_feedback(results_dict) -> str:
    feedback_strs = [
      "##############",
      "## FEEDBACK ##",
      "##############",
      "",
    ]
    
    if "overall_feedback" in results_dict:
      feedback_strs.extend([
        "## Overall Feedback ##",
        results_dict["overall_feedback"],
        "\n\n"
      ])
    
    feedback_strs.extend([
      "## Unit Tests ##",
    ])
    if "suites" in results_dict:
      for suite_name in results_dict["suites"].keys():
        
        if len(results_dict["suites"][suite_name]["PASSED"]) > 0:
          feedback_strs.extend([
            f"SUITE: {suite_name}",
            "  * passed:",
          ])
          feedback_strs.extend([
            textwrap.indent('\n'.join(results_dict["suites"][suite_name]["PASSED"]), '    '),
            ""
          ])
          
        if len(results_dict["suites"][suite_name]["FAILED"]) > 0:
          feedback_strs.extend([
            f"SUITE: {suite_name}",
            "  * failed:",
          ])
          feedback_strs.extend([
            textwrap.indent('\n'.join(results_dict["suites"][suite_name]["FAILED"]), '    '),
            ""
          ])
      feedback_strs.extend([
        "################",
        "",
      ])
    
    
    if "build_logs" in results_dict:
      feedback_strs.extend([
        "## Build Logs ##",
      ])
      feedback_strs.extend([
        "Build Logs:",
        ''.join(results_dict["build_logs"])[1:-1].encode('utf-8').decode('unicode_escape')
      ])
      feedback_strs.extend([
        "################",
      ])
    
    
    if "lint_logs" in results_dict:
      feedback_strs.extend([
        "## Lint Logs ##",
        f"Lint success: {results_dict['lint_success']}\n"
      ])
      feedback_strs.extend([
        "Lint Logs:",
        ''.join(results_dict["lint_logs"])[1:-1].encode('utf-8').decode('unicode_escape')
      ])
      feedback_strs.extend([
        "################",
      ])
    
    return '\n'.join(feedback_strs)
  
  def execute_grading(self, programming_assignment, *args, **kwargs) -> Tuple[int, str, str]:
    rc, stdout, stderr = self.execute(
      command="timeout 120 python ../../helpers/grader.py --output /tmp/results.json",
      workdir=f"/tmp/grading/programming-assignments/{programming_assignment}/"
    )
    return rc, stdout, stderr
  
  def score_grading(self, *args, **kwargs) -> misc.Feedback:
    results = self.read_file("/tmp/results.json")
    if results is None:
      # Then something went awry in reading back feedback file
      return misc.Feedback(
        overall_score=0,
        overall_feedback="Something went wrong during grading, likely a timeout.  Please check your assignment for infinite loops and/or contact your professor."
      )
    results_dict = json.loads(results)
    if "lint_success" in results_dict and results_dict["lint_success"] and "lint_bonus" in kwargs:
      results_dict["score"] += kwargs["lint_bonus"]
    
    return misc.Feedback(
      overall_score=results_dict["score"],
      overall_feedback=self.build_feedback(results_dict)
    )
  
  def grade_in_docker(self, source_dir, programming_assignment, lint_bonus) -> misc.Feedback:
    files_to_copy = [
      (
        f,
        f"/tmp/grading/programming-assignments/{programming_assignment}/{'src' if f.endswith('.c') else 'include'}"
      )
      for f in [os.path.join(source_dir, f_wo_path) for f_wo_path in os.listdir(source_dir)]
    ]
    return super().grade_in_docker(files_to_copy, programming_assignment=programming_assignment, lint_bonus=lint_bonus)
    
  def grade_assignment(self, input_files: List[str], *args, **kwargs) -> misc.Feedback:
    
    # Legacy settings
    use_max = "use_max" in kwargs and kwargs["use_name"]
    tags = ["main"] if "tags" not in kwargs else kwargs["tags"]
    num_repeats = 10 if "num_repeats" not in kwargs else kwargs["num_repeats"]
    
    # Setup input files
    # todo: convert to using a temp file since I currently have to manually delete later on
    if os.path.exists("student_code"): shutil.rmtree("student_code")
    os.mkdir("student_code")
    
    # Copy the student code to the staging directory
    files_copied = []
    for file_extension in [".c", ".h"]:
      try:
        file_to_copy = list(filter(lambda f: "student_code" in f and f.endswith(file_extension), input_files))[0]
        files_copied.append(file_to_copy)
        shutil.copy(
          file_to_copy,
          f"./student_code/student_code{file_extension}"
        )
      except IndexError:
        log.warning("Single file submitted")
    
    # Check for trickery, per Elijah's trials (so far)
    if self.check_for_trickery(files_copied):
      return misc.Feedback(
        overall_score=0.0,
        overall_feedback="It was detected that you might have been trying to game the scoring via exiting early from a unit test.  Please contact your professor if you think this was in error."
      )
    
    # Set up to be able to run multiple times
    # todo: I should probably move to the results format for this
    
    list_of_results : List[misc.Feedback] = []
    
    for i in range(num_repeats):
      result = self.grade_in_docker(
        os.path.abspath("./student_code"),
        self.assignment_path,
        1
      )
      log.debug(result)
      list_of_results.append(result)
    shutil.rmtree("student_code")
    
    # Select best feedback and add a little bit on
    final_feedback = min(list_of_results, key=(lambda f: f.overall_score))
    final_feedback.overall_feedback += "\n\n"
    final_feedback.overall_feedback += "###################\n"
    final_feedback.overall_feedback += "## Full results: ##\n"
    for i, result in enumerate(list_of_results):
      final_feedback.overall_feedback += f"test {i}: {result.overall_score} points\n"
    final_feedback.overall_feedback += "###################\n"
    
    return final_feedback


class Grader_stepbystep(Grader_docker):
  # todo:
  #  We will want to enable rollback, where we can "undo" a few instructions.  This will likely be done by restarting student container
  #  This will likely mean either overriding grade_in_docker, or a new function that restarts student and walks it forward again
  
  def __init__(self, rubric_file, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.rubric = self.parse_rubric(rubric_file)
    self.golden_container : docker.models.containers.Container = None
    self.student_container : docker.models.containers.Container = None
  
  def parse_rubric(self, rubric_file):
    with open(rubric_file) as fid:
      rubric = yaml.safe_load(fid)
    if not isinstance(rubric["steps"], list):
      rubric["steps"] = rubric["steps"].split('\n')
    return rubric
  
  def parse_student_file(self, student_file):
    with open(student_file) as fid:
      return [l.strip() for l in fid.readlines()]
      
  def rollback(self):
    # Stop and delete student container
    self.student_container.stop(timeout=1)
    self.student_container.remove()
    self.student_container = None
    
    # Make a copy of the golden_container
    rollback_image = self.golden_container.commit(repository="rollback", tag="latest")
    
    # Start student from the copy we just made
    self.student_container = self.client.containers.run(
      image=rollback_image.id,
      detach=True,
      tty=True
    )
  
  def start(self, image : docker.models.images,):
    self.golden_container = self.client.containers.run(
      image=image,
      detach=True,
      tty=True
    )
    self.student_container = self.client.containers.run(
      image=image,
      detach=True,
      tty=True
    )
  
  def stop(self):
    self.golden_container.stop(timeout=1)
    self.golden_container.remove()
    self.golden_container = None
    self.student_container.stop(timeout=1)
    self.student_container.remove()
    self.student_container = None
  
  
  def execute_grading(self, golden_lines=[], student_lines=[], rollback=True, *args, **kwargs):
    golden_results = collections.defaultdict(list)
    student_results = collections.defaultdict(list)
    def add_results(results_dict, rc, stdout, stderr):
      results_dict["rc"].append(rc)
      results_dict["stdout"].append(stdout)
      results_dict["stderr"].append(stderr)
    
    for i, (golden, student) in enumerate(zip(golden_lines, student_lines)):
      log.debug(f"commands: '{golden}' <-> '{student}'")
      rc_g, stdout_g, stderr_g = self.execute(container=self.golden_container, command=golden)
      rc_s, stdout_s, stderr_s = self.execute(container=self.student_container, command=student)
      add_results(golden_results, rc_g, stdout_g, stderr_g)
      add_results(student_results, rc_s, stdout_s, stderr_s)
      if (not self.outputs_match(stdout_g, stdout_s, stderr_g, stderr_s, rc_g, rc_s) ) and rollback:
        # Bring the student container up to date with our container
        self.rollback()
    
    return golden_results, student_results
  
  @staticmethod
  def outputs_match(stdout_g, stdout_s, stderr_g, stderr_s, rc_g, rc_s) -> bool:
    if stdout_g != stdout_s:
      return False
    if stderr_g != stderr_s:
      return False
    if rc_g != rc_s:
      return False
    return True
  
  def score_grading(self, execution_results, *args, **kwargs) -> misc.Feedback:
    log.debug(f"execution_results: {execution_results}")
    golden_results, student_results = execution_results
    num_lines = len(golden_results["stdout"])
    num_matches = 0
    for i in range(num_lines):
      if not self.outputs_match(
          golden_results["stdout"][i], student_results["stdout"][i],
          golden_results["stderr"][i], student_results["stderr"][i],
          golden_results["rc"][i], student_results["rc"][i]
      ):
        continue
      num_matches += 1
    
    return misc.Feedback(
      overall_score=(100.0 * num_matches / len(golden_results["stdout"])),
      overall_feedback=f"Matched {num_matches} out of {len(golden_results['stdout'])}"
    )
  
  
  def grade_assignment(self, input_files: List[str], *args, **kwargs) -> misc.Feedback:
    
    golden_lines = self.rubric["steps"]
    student_lines = self.parse_student_file(input_files[0])
    
    results = self.grade_in_docker(golden_lines=golden_lines, student_lines=student_lines, *args, **kwargs)
    
    log.debug(f"final results: {results}")
    return results


class Grader_manual(Grader):
  def __init__(self, df: pd.DataFrame, *args, **kwargs):
    """
    
    :param csv_or_df: CSV or DF, we assume there will be appropriate columsn (e.g. "total", "student_id")
    :param args:
    :param kwargs:
    """
    super().__init__(*args, **kwargs)
    self.df : pd.DataFrame = df.set_index("user_id")
  
  def grade_assignment(self, *args, student_id, to_upload_base_dir, **kwargs) -> misc.Feedback:
    # This will essentially look up the grade in the DF and return back a grade and feedback based on it
    # this will be how we can merge the two flows
    log.debug(f"Request to grade for {student_id}")
    student_row = self.df.loc[student_id]
    
    per_problem_feedback = student_row[student_row.index.str.startswith('Q')].to_dict()
    
    with open(os.path.join(to_upload_base_dir, student_row["file"]), 'rb') as fid:
      file_buffer = io.BytesIO(fid.read())
      file_buffer.name = '999.pdf'
      
    return misc.Feedback(
      overall_score=student_row["total"],
      overall_feedback='\n'.join([f"{q}: {per_problem_feedback[q]}" for q in per_problem_feedback.keys()]),
      attachments=[file_buffer]
    )
    


