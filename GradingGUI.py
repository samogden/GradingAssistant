#! env python

import argparse
import logging
import tkinter as tk

import dotenv

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
  
  a = ScannedExam(flags.base_exam, flags.input_dir, limit=2, **vars(flags))
  print(a)
  if flags.autograde:
    try:
      a.autograde(**vars(flags))
    finally:
      a.get_feedback()
      log.info(f"Total tokens: {a.get_token_count()}")
    return
  
  root = tk.Tk()

  menubar = tk.Menu(root)
  file_menu = tk.Menu(menubar, tearoff=0)
  file_menu.add_command(label="Save", command=(lambda: a.get_feedback()))
  file_menu.add_command(label="Exit", command=root.quit)
  menubar.add_cascade(label="File", menu=file_menu)
  
  root.config(menu=menubar)
  
  a.get_tkinter_frame(root)
  root.mainloop()
  

if __name__ == "__main__":
  main()
