#!env python
import argparse
import logging
import os
import pprint
import tkinter as tk
from typing import List

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
  
def main():
  # log.debug(os.environ.get("CANVAS_API_KEY"))
  
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
  args = parser.parse_args()
  
  log.debug(args.assignments)
  for assignment_name, assignment_id in args.assignments:
    assignment_id = int(assignment_id)
    log.debug(f"{assignment_name}, {assignment_id}")
    with assignment.CanvasAssignment(args.course_id, assignment_id, args.prod) as a:
      # a = assignment.CanvasAssignment(args.course_id, assignment_id, args.prod)
      a.prepare_assignment_for_grading(limit=args.limit, regrade=args.regrade)
      if a.needs_grading:
        a.grade(grader.Grader_CST334(assignment_name, use_online_repo=args.online), push_feedback=args.push)
      else:
        log.info("No grading needed")
  return
  
  
  return
  
if __name__ == "__main__":
  dotenv.load_dotenv()
  main()