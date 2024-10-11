#!env python
import abc
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
  def grade_assignment(self, input_files: List[str], *args, **kwargs) -> misc.Feedback:
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
  
  @classmethod
  def run_docker_with_archive(
      cls,
      image : docker.models.images,
      files_to_copy : List[Tuple[str,str]] = None, # files to copy.  Format is [(src, target), ...]
      working_dir : str = "/", # working directory (i.e. where to grade from)
      grade_command : str = "make grade", # command to grade (e.g. `make grade`)
      results_file=None, # The results file, if you want one -- otherwise stdout should be returned
  ) -> str:
    
    def add_file_to_container(src_file, target_dir, container):
      # Prepare the files as a tarball to push into container
      tarstream = io.BytesIO()
      with tarfile.open(fileobj=tarstream, mode="w") as tarhandle:
        tarhandle.add(src_file, arcname=os.path.basename(src_file))
      tarstream.seek(0)
      
      # Push student files to image
      container.put_archive(f"{target_dir}", tarstream)
      
    
    # Start the container using the image
    container = cls.client.containers.run(
      image=image,
      detach=True,
      tty=True
    )
    
    try:
      for src_file, target_dir in files_to_copy:
        add_file_to_container(src_file, target_dir, container)
      
      # Set up the command to change to the working directory and run the grading command
      run_str = f"""
        bash -c '
          cd {working_dir} ;
          {grade_command} ;
        '
        """
      
      # Run the grading commands!
      exit_code, output = container.exec_run(run_str)
      
      # If we're not pulling from a file, just return stdout
      if results_file is None:
        # Just return stdout
        return output
      
      # otherwise we should read the results file
      try:
        # Try to find the file on the system
        bits, stats = container.get_archive(f"{results_file}")
      except docker.errors.NotFound as e:
        # default to asking what went wrong
        log.debug(e)
        return json.dumps({"score": None, "overall_feedback": "Error running in docker.  Likely due to timeout.  Please contact your professor if you have questions."})
      
      # Read file from docker
      f = io.BytesIO()
      for chunk in bits:
        f.write(chunk)
      f.seek(0)
    finally:
      container.stop(timeout=1)
      container.remove()
      
    
    # Open the tarball we just pulled and read the contents to a string buffer
    with tarfile.open(fileobj=f, mode="r") as tarhandle:
      results_f = tarhandle.getmember("results.json")
      f = tarhandle.extractfile(results_f)
      f.seek(0)
      results_str = f.read().decode()
    
    return results_str
    
  def start(
      self,
      image : docker.models.images,
  ):
    
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
  
  def execute(self, command, workdir=None) -> typing.Tuple[int, str, str]:
    log.debug(f"execute: {command}")
    extra_args = {}
    if workdir is not None:
      extra_args["workdir"] = workdir
    
    rc, (stdout, stderr) = self.container.exec_run(
      cmd=command,
      demux=True,
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

class Grader_CST334(Grader_docker):

  
  def __init__(self,
      assignment_path,
      use_online_repo=False
  ):
    super().__init__()
    if use_online_repo:
      github_repo="https://github.com/samogden/CST334-assignments-online.git"
    else:
      github_repo="https://github.com/samogden/CST334-assignments.git"
    self.assignment_path = assignment_path
    self.image = Grader_CST334.build_docker_image(base_image="samogden/cst334", github_repo=github_repo)
    
  
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
  
  @classmethod
  def grade_in_docker_old(cls, image, source_dir, tag_to_test, programming_assignment, lint_bonus=1) -> misc.Feedback:
    
    files_to_copy = [
      
      (
        f,
        f"/tmp/grading/programming-assignments/{programming_assignment}/{'src' if f.endswith('.c') else 'include'}"
      )
      for f in [os.path.join(source_dir, f_wo_path) for f_wo_path in os.listdir(source_dir)]
    ]
    
    # Run our parent docker class
    feedback_str = super().run_docker_with_archive(
      image = image,
      files_to_copy=files_to_copy,
      working_dir = f"/tmp/grading/programming-assignments/{programming_assignment}/",
      grade_command="git checkout {tag_to_test} ; timeout 120 python ../../helpers/grader.py --output /tmp/results.json",
      results_file="/tmp/results.json"
    )
    
    log.debug(f"feedback_str: {feedback_str}")
    # Load results that we asked for
    results_dict = json.loads(feedback_str)
    
    # Add in lint bonus, if applicable
    try:
      if results_dict["lint_success"]:
        results_dict["score"] += lint_bonus
    except KeyError:
      pass
    
    # Build feedback string
    feedback_str = cls.build_feedback(results_dict)
    
    # Create feedback object
    results = misc.Feedback(
      overall_score=results_dict["score"],
      overall_feedback=feedback_str
    )
    
    log.debug(f"results: {results}")
    
    return results

  def grade_in_docker(self, source_dir, programming_assignment, lint_bonus) -> misc.Feedback:
    
    files_to_copy = [
      (
        f,
        f"/tmp/grading/programming-assignments/{programming_assignment}/{'src' if f.endswith('.c') else 'include'}"
      )
      for f in [os.path.join(source_dir, f_wo_path) for f_wo_path in os.listdir(source_dir)]
    ]
    
    with self:
      self.add_files_to_docker(files_to_copy)
      rc, stdout, stderr = self.execute(
        command="timeout 120 python ../../helpers/grader.py --output /tmp/results.json",
        workdir=f"/tmp/grading/programming-assignments/{programming_assignment}/"
      )
      results = self.read_file("/tmp/results.json")
    if results is None:
      # Then something went awry in reading back feedback file
      return misc.Feedback(
        overall_score=0,
        overall_feedback="Something went wrong during grading, likely a timeout.  Please check your assignment for infinite loops and/or contact your professor."
      )
    results_dict = json.loads(results)
    if "lint_success" in results_dict and results_dict["lint_success"]:
      results_dict["score"] += 1
      
    return misc.Feedback(
      overall_score=results_dict["score"],
      overall_feedback=self.build_feedback(results_dict)
    )
  
  
  def grade_assignment(self, input_files: List[str], *args, **kwargs) -> misc.Feedback:
    
    # Legacy settings
    use_max = "use_max" in kwargs and kwargs["use_name"]
    tags = ["main"] if "tags" not in kwargs else kwargs["tags"]
    num_repeats = 3 if "num_repeats" not in kwargs else kwargs["num_repeats"]
    
    # Setup input files
    # todo: convert to using a temp file since I currently have to manually delete later on
    if os.path.exists("student_code"): shutil.rmtree("student_code")
    os.mkdir("student_code")
    
    # Copy the student code to the staging directory
    for file_extension in [".c", ".h"]:
      try:
        file_to_copy = list(filter(lambda f: f.endswith(file_extension), input_files))[0]
        shutil.copy(
          file_to_copy,
          f"./student_code/student_code{file_extension}"
        )
      except IndexError:
        log.warning("Single file submitted")
    
    # Define a comparison function to allow us to pick either the best or worst outcome
    def is_better(score1, score2):
      # log.debug(f"is_better({score1}, {score2})")
      if use_max:
        return score2 < score1
      return score1 < score2
    
    # Set up to be able to run multiple times
    # todo: I should probably move to the results format for this
    
    results = misc.Feedback()
    
    for tag_to_test in tags:
      # worst_results = {"score" : float('inf')}
      for i in range(num_repeats):
        new_results = self.grade_in_docker(
          os.path.abspath("./student_code"),
          self.assignment_path,
          1
        )
        if is_better(new_results, results):
          # log.debug(f"Updating to use new results: {new_results}")
          results = new_results
        log.info(f"new_results: {new_results}")
    if results.overall_score is None:
      results.overall_score = 0
    log.debug(f"final results: {results}")
    shutil.rmtree("student_code")
    return results



