#!env python
import abc
import json
import os
import pprint
import shutil
import tarfile
import textwrap
import time
from typing import List, Tuple
import io

import docker

import misc

import logging
logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

class Grader:
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

class GraderCode(Grader):

  client = docker.from_env()
  
  def __init__(self,
      assignment_path,
      github_repo="https://github.com/samogden/CST334-assignments.git"
  ):
    self.assignment_path = assignment_path
    self.image = GraderCode.build_docker_image(github_repo=github_repo)
    super().__init__()
  
  @classmethod
  def build_docker_image(cls, github_repo):
    log.info("Building docker image for grading...")
    
    docker_file = io.BytesIO(f"""
    FROM samogden/csumb:cst334
    RUN git clone {github_repo} /tmp/grading/
    WORKDIR /tmp/grading
    CMD ["/bin/bash"]
    """.encode())
    
    image, logs = cls.client.images.build(
      fileobj=docker_file,
      tag="grading",
      pull=True,
      nocache=False
    )
    # log.debug(logs)
    log.debug("Docker image built successfully")
    return image

  @staticmethod
  def build_feedback(results_dict) -> str:
    feedback_strs = [
      "##############",
      "## FEEDBACK ##",
      "##############",
      "",
    ]
    
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
    
    return '\n'.join(feedback_strs)
    

  @classmethod
  def run_docker_with_archive(cls, image, student_files_dir, tag_to_test, programming_assignment) -> misc.Feedback:
    # log.debug("Grading in docker...")
    tarstream = io.BytesIO()
    with tarfile.open(fileobj=tarstream, mode="w") as tarhandle:
      for f in [os.path.join(student_files_dir, f) for f in os.listdir(student_files_dir)]:
        tarhandle.add(f, arcname=os.path.basename(f))
    tarstream.seek(0)
    
    container = cls.client.containers.run(
      image=image,
      detach=True,
      tty=True
    )
    try:
      container.put_archive(f"/tmp/grading/programming-assignments/{programming_assignment}/src", tarstream)
      
      exit_code, output = container.exec_run(f"ls -l /tmp/grading/programming-assignments/{programming_assignment}/")
      # log.debug(output.decode())
      exit_code, output = container.exec_run(f"tree /tmp/grading/programming-assignments/{programming_assignment}/")
      # log.debug(output.decode())
      
      
      container.exec_run(f"bash -c 'git checkout {tag_to_test}'")
      
      run_str = f"""
        bash -c '
          cd /tmp/grading/programming-assignments/{programming_assignment} ;
          timeout 600 python ../../helpers/grader.py --output /tmp/results.json ;
        '
        """
      # log.debug(f"run_str: {run_str}")
      exit_code, output = container.exec_run(run_str)
      try:
        bits, stats = container.get_archive("/tmp/results.json")
      except docker.errors.NotFound:
        return misc.Feedback(overall_score=0, overall_feedback="Error running in docker")
      f = io.BytesIO()
      for chunk in bits:
        f.write(chunk)
      f.seek(0)
      
      with tarfile.open(fileobj=f, mode="r") as tarhandle:
        results_f = tarhandle.getmember("results.json")
        f = tarhandle.extractfile(results_f)
        f.seek(0)
        results_dict = json.loads(f.read().decode())
    finally:
      container.stop(timeout=1)
      container.remove()
    
    feedback_str = cls.build_feedback(results_dict)
    
    results = misc.Feedback(
      overall_score=results_dict["score"],
      overall_feedback=feedback_str
    )
    
    log.debug(f"results: {results}")
    # log.debug("Grading in docker complete")
    
    return results
  
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
        new_results = self.run_docker_with_archive(
          self.image,
          os.path.abspath("./student_code"),
          tag_to_test,
          self.assignment_path
        )
        if is_better(new_results, results):
          log.debug(f"Updating to use new results: {new_results}")
          results = new_results
    log.debug(f"final results: {results}")
    shutil.rmtree("student_code")
    return results