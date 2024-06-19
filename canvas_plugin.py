#!env python
import logging
import os
import tkinter as tk

import assignment

import canvasapi
import dotenv

import ai_helper

logging.basicConfig()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def main():
  canvas = canvasapi.Canvas(os.environ.get("CANVAS_API_URL"), os.environ.get("CANVAS_API_KEY"))
  course = canvas.get_course(23751)
  log.debug(f"{course.name}")
  
  quiz = course.get_quiz(87942)
  # grade_quiz(quiz, course)
  
  canvas_assignment = assignment.CanvasQuiz(quiz, course)
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
  

if __name__ == "__main__":
  dotenv.load_dotenv()
  main()