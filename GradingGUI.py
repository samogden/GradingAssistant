#! env python

import argparse
import logging
import tkinter as tk

import dotenv

import ai_helper
from assignment import ScannedExam

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def parse_flags():
  parser = argparse.ArgumentParser()
  
  parser.add_argument("--input_dir", default="~/Documents/CSUMB/grading/CST334/2024Spring/Exam3/00-base")
  parser.add_argument("--query_ai", action="store_true")
  parser.add_argument("--base_exam", default="../exam_randomization/exam_generation/exam.pdf")
  parser.add_argument("--autograde", action="store_true")
  
  parser.add_argument("--image_scale", default=1.0, type=float)
  parser.add_argument("--trim", action="store_true")
  
  parser.add_argument("--debug", action="store_true")
  
  return parser.parse_args()


def main():
  flags = parse_flags()
  dotenv.load_dotenv()
  
  assignment = ScannedExam(flags.base_exam, flags.input_dir, limit=4, **vars(flags))
  if flags.query_ai:
    grading_helper = ai_helper.AI_Helper()
  else:
    grading_helper = ai_helper.AI_Helper_fake()
  
  print(assignment)
  if flags.autograde:
    try:
      assignment.autograde(grading_helper, **vars(flags))
    finally:
      assignment.get_feedback()
      log.info(f"Total tokens: {assignment.get_token_count()}")
    return
  
  root = tk.Tk()

  menubar = tk.Menu(root)
  file_menu = tk.Menu(menubar, tearoff=0)
  file_menu.add_command(label="Save", command=(lambda: assignment.get_feedback()))
  file_menu.add_command(label="Exit", command=root.quit)
  menubar.add_cascade(label="File", menu=file_menu)
  
  root.config(menu=menubar)
  
  assignment.get_tkinter_frame(root, grading_helper)
  root.mainloop()
  

if __name__ == "__main__":
  main()
