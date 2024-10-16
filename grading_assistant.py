#!env python
import argparse
import logging
import os
import pprint
import subprocess
import tkinter as tk
from typing import List

import yaml

import assignment

import canvasapi
import canvasapi.quiz
import dotenv

import ai_helper
import grader

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def GUI():
  # canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  quiz = course.get_quiz(87942)
  # grade_quiz(quiz, course)
  
  a = assignment.CanvasQuiz(quiz, course)
  grading_helper = ai_helper.AI_Helper_fake()
  
  root = tk.Tk()
  
  menubar = tk.Menu(root)
  file_menu = tk.Menu(menubar, tearoff=0)
  file_menu.add_command(label="Save", command=(lambda: canvas_assignment.get_feedback()))
  file_menu.add_command(label="Exit", command=root.quit)
  menubar.add_cascade(label="File", menu=file_menu)
  
  root.config(menu=menubar)
  
  canvas_assignment.get_tkinter_frame(root, grading_helper)
  root.mainloop()


def parse_args():
  
  parser = argparse.ArgumentParser()
  
  parser.add_argument("--assignment", dest="assignments", action="append", nargs=2)
  
  parser.add_argument("--course_id", type=int, default=25068)
  parser.add_argument("--assignment_id", type=int, default=377043)
  parser.add_argument("--name", default="PA1")
  parser.add_argument("--regrade", action="store_true")
  parser.add_argument("--online", action="store_true")
  parser.add_argument("--prod", action="store_true")
  parser.add_argument("--push", action="store_true")
  parser.add_argument("--limit", type=int)
  
  
  
  subparsers = parser.add_subparsers(dest="action")
  subparsers.add_parser("MOSS")
  subparsers.add_parser("MANUAL")
  stepbystep_parser = subparsers.add_parser("STEPBYSTEP")
  stepbystep_parser.add_argument("--rubric", required=True)
  stepbystep_parser.add_argument("--no_rollback_on_error", action="store_false", dest="rollback")
  
  
  
  args, remaining_args = parser.parse_known_args()
  
  # If there are remaining arguments (e.g., global flags after subcommands), reparse them
  if remaining_args:
    args = parser.parse_args(remaining_args, namespace=args)
  
  return args

def run_moss_flow(course_id: int, assignment_id: int, assignment_name: str, prod: bool, limit=None):
  with assignment.CanvasAssignment(course_id, assignment_id, prod) as a:
    student_submissions = a.get_student_submissions(a.canvas_assignment, False)
    if limit != None:
      student_submissions = student_submissions[:limit]
    submissions = a.download_submission_files(student_submissions)
    submission_c_files = [os.path.basename(item) for sublist in submissions.values() for item in sublist if item.endswith(".c")]
    
    command = [
      '/Users/ssogden/scripts/moss.pl',
      '-l', "c"
    ] + submission_c_files
    
    log.debug(f"command: {' '.join(command)}")
    
    # Run the process with the default environment
    result = subprocess.run(command, cwd=a.working_dir, capture_output=True, text=True)
    
    # Print the output
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    print("Return Code:", result.returncode)
  
def run_semi_manual_flow(course_id: int, assignment_id: int, prod: bool, limit=None):
  with assignment.CanvasAssignment(course_id, assignment_id, prod) as a:
    student_submissions = a.get_student_submissions(a.canvas_assignment, True)
    if limit != None:
      student_submissions = student_submissions[:limit]
    submissions = a.download_submission_files(student_submissions, download_dir=os.path.join(os.getcwd(), "files"))


def main():
  # log.debug(os.environ.get("CANVAS_API_KEY"))
  
  args = parse_args()
  
  
  log.debug(f"args.action: {args.action}")
  log.debug(f"args: {args}")
  
  if args.action == "STEPBYSTEP":
    log.debug(args.assignments)
    for assignment_name, assignment_id in args.assignments:
      assignment_id = int(assignment_id)
      log.debug(f"{assignment_name}, {assignment_id}")
      with assignment.CanvasProgrammingAssignment(args.course_id, assignment_id, args.prod) as a:
        a.prepare_assignment_for_grading(limit=args.limit, regrade=args.regrade)
        if a.needs_grading:
          a.grade(grader.Grader_stepbystep(rubric_file=args.rubric), push_feedback=args.push, rollback=args.rollback)
        else:
          log.info("No grading needed")
  
  elif args.action == "MOSS":
    for assignment_name, assignment_id in args.assignments:
      assignment_id = int(assignment_id)
      run_moss_flow(args.course_id, assignment_id, assignment_name, args.prod, args.limit)
  
  elif args.action == "MANUAL":
    for assignment_name, assignment_id in args.assignments:
      assignment_id = int(assignment_id)
      run_semi_manual_flow(args.course_id, assignment_id, args.prod, args.limit)
  else:
    
    log.debug(args.assignments)
    for assignment_name, assignment_id in args.assignments:
      assignment_id = int(assignment_id)
      log.debug(f"{assignment_name}, {assignment_id}")
      with assignment.CanvasProgrammingAssignment(args.course_id, assignment_id, args.prod) as a:
        # a = assignment.CanvasAssignment(args.course_id, assignment_id, args.prod)
        a.prepare_assignment_for_grading(limit=args.limit, regrade=args.regrade)
        if a.needs_grading:
          a.grade(grader.Grader_CST334(assignment_name, use_online_repo=args.online), push_feedback=args.push)
        else:
          log.info("No grading needed")
  return
  
  
if __name__ == "__main__":
  dotenv.load_dotenv()
  main()