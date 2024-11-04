#!env python
import argparse
import logging
import os
import pprint
import subprocess
import tkinter as tk
from typing import List

import pandas as pd
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

  # Create a parent parser with shared arguments
  parent_parser = argparse.ArgumentParser(add_help=False)
  parent_parser.add_argument("--assignment", dest="assignments", action="append", nargs=2)
  parent_parser.add_argument("--course_id", type=int, default=25068)
  parent_parser.add_argument("--assignment_id", type=int, default=377043)
  parent_parser.add_argument("--name", default="PA1")
  parent_parser.add_argument("--regrade", action="store_true")
  parent_parser.add_argument("--online", action="store_true")
  parent_parser.add_argument("--prod", action="store_true")
  parent_parser.add_argument("--push", action="store_true")
  parent_parser.add_argument("--clobber", action="store_true")
  parent_parser.add_argument("--limit", type=int)
  parent_parser.add_argument("--user_id", type=int, default=None, help="Specific user_id to check submission for")
  
  # Main parser
  parser = argparse.ArgumentParser()
  
  # Subparsers
  subparsers = parser.add_subparsers(dest="action", required=True)
  
  # Each subcommand uses the parent parser to inherit shared arguments
  subparsers.add_parser("GRADE", parents=[parent_parser])
  subparsers.add_parser("MOSS", parents=[parent_parser])
  manual_parser = subparsers.add_parser("MANUAL", parents=[parent_parser])
  manual_parser.add_argument("--input_csv", required=True)
  manual_parser.add_argument("--upload_dir")
  
  stepbystep_parser = subparsers.add_parser("STEPBYSTEP", parents=[parent_parser])
  stepbystep_parser.add_argument("--rubric", required=True)
  stepbystep_parser.add_argument("--no_rollback_on_error", action="store_false", dest="rollback")
  
  # Parsing the arguments
  args = parser.parse_args()
  
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
  
def run_semi_manual_flow(
    course_id: int,
    assignment_id: int,
    csv_or_df: pd.DataFrame|str,
    upload_dir,
    prod: bool,
    limit=None,
    push_feedback=False,
    clobber_feedback=False
):
  if isinstance(csv_or_df, str):
    df = pd.read_csv(csv_or_df)
  else:
    df = csv_or_df
  df = df[df["user_id"].notna()]
  df["user_id"] = df["user_id"].astype(int)
  
  log.debug(df.user_id)
  
  student_ids = df["user_id"].unique().tolist()
  log.debug(student_ids)
  
  if limit is not None:
    student_ids = student_ids[:limit]
    log.debug(student_ids)
  
  with assignment.CanvasAssignment_manual(course_id, assignment_id, prod) as a:
    a.prepare_assignment_for_grading(student_ids=student_ids)
    a.check_student_names([(str(row.name), int(row.user_id)) for row in df.itertuples() if row.user_id in student_ids])
    
    confirmation = input("Do these names look good? (y/N)")
    if confirmation.lower() != "y":
      log.warning("Not continuing per instructions.")
      return
    
    a.grade(
      grader=grader.Grader_old_manual(df),
      push_feedback=push_feedback,
      to_upload_base_dir=upload_dir,
      clobber_feedback=clobber_feedback
    )
  

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
      run_semi_manual_flow(
        args.course_id,
        assignment_id,
        args.input_csv,
        args.upload_dir,
        args.prod,
        args.limit,
        push_feedback=args.push,
        clobber_feedback=args.clobber
      )
  else:
    
    log.debug(args.assignments)
    for assignment_name, assignment_id in args.assignments:
      assignment_id = int(assignment_id)
      log.debug(f"{assignment_name}, {assignment_id}")
      with assignment.CanvasProgrammingAssignment(args.course_id, assignment_id, args.prod) as a:
        # a = assignment.CanvasAssignment(args.course_id, assignment_id, args.prod)
        a.prepare_assignment_for_grading(limit=args.limit, regrade=args.regrade, user_ids=[args.user_id])
        if a.needs_grading:
          a.grade(grader.Grader_CST334(assignment_name, use_online_repo=args.online), push_feedback=args.push)
        else:
          log.info("No grading needed")
  return
  
  
if __name__ == "__main__":
  dotenv.load_dotenv()
  main()